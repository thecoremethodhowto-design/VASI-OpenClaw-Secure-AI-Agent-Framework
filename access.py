"""Access katmani: yetkilendirme, siniflandirma ve guvenlik kontrolleri.

DACE mimarisinin Access katmani. "Izin var mi?" sorusunu yanitlayan
tum fonksiyonlar burada toplanir.

NOT: Bu modul kendi yapilandirmasini ve durumunu sahiplenir. Testlerde
bu degerleri degistirmek icin `vasi.access` uzerinden patch'leyin,
`vasi` uzerinden degil.
"""
import ipaddress
import logging
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from fnmatch import fnmatch
from urllib.parse import urlparse

import yaml
from telegram import Update

logger = logging.getLogger("vasi")

# ── YAPILANDIRMA ──────────────────────────────────────────────────────────────
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace")).resolve()
WEB_RADAR_ALLOWLIST_RAW = os.getenv("WEB_RADAR_ALLOWLIST", "")
GEMINI_DAILY_LIMIT_REQUESTS = int(os.getenv("GEMINI_DAILY_LIMIT_REQUESTS", "60"))

# ── SABITLER ─────────────────────────────────────────────────────────────────
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_REQUESTS = 20
GEMINI_RATE_LIMIT_REQUESTS = 5
ALLOWED_WRITE_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
WEB_RADAR_ALLOWLIST = tuple(
    domain.strip().lower()
    for domain in WEB_RADAR_ALLOWLIST_RAW.split(",")
    if domain.strip()
)
SANDBOX_SCOPES = {
    "general": ("notlar",),
    "youtube": ("youtube", "notlar", "skills/youtube_icerik.md", "skills/arastirma.md"),
    "code": ("projeler", "skills/kod_yardimcisi.md"),
}
ALLOWED_TOOL_NAMES = {"skill_get_time", "skill_web_radar"}

# ── DURUM ────────────────────────────────────────────────────────────────────
USER_RATE_LIMITS = {}
GEMINI_RATE_LIMITS = {}
GEMINI_DAILY_COUNTERS = {}

# ── RATE LIMIT & YETKILENDIRME ──────────────────────────────────────────

def check_rate_limit(user_id: str) -> bool:
    """Rate limiting kontrolü - hızlı spam'a karşı."""
    now = datetime.now()
    if user_id not in USER_RATE_LIMITS:
        USER_RATE_LIMITS[user_id] = []
    
    # Pencereyi temizle (eski talepleri kaldır)
    USER_RATE_LIMITS[user_id] = [
        t for t in USER_RATE_LIMITS[user_id]
        if (now - t).total_seconds() < RATE_LIMIT_WINDOW
    ]
    
    # Limit kontrolü
    if len(USER_RATE_LIMITS[user_id]) >= RATE_LIMIT_REQUESTS:
        logger.warning(f"⚠️ Rate limit aşımı: {user_id}")
        return False
    
    USER_RATE_LIMITS[user_id].append(now)
    return True

def check_gemini_rate_limit(user_id: str) -> bool:
    """Gemini arastirmalari icin daha dar maliyet/istismar limiti."""
    now = datetime.now()
    if user_id not in GEMINI_RATE_LIMITS:
        GEMINI_RATE_LIMITS[user_id] = []

    GEMINI_RATE_LIMITS[user_id] = [
        t for t in GEMINI_RATE_LIMITS[user_id]
        if (now - t).total_seconds() < RATE_LIMIT_WINDOW
    ]

    if len(GEMINI_RATE_LIMITS[user_id]) >= GEMINI_RATE_LIMIT_REQUESTS:
        logger.warning(f"⚠️ Gemini rate limit aşımı: {user_id}")
        return False

    GEMINI_RATE_LIMITS[user_id].append(now)
    return True

def check_gemini_daily_limit(user_id: str) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    if user_id not in GEMINI_DAILY_COUNTERS:
        GEMINI_DAILY_COUNTERS[user_id] = {"date": today, "count": 0}

    record = GEMINI_DAILY_COUNTERS[user_id]
    if record["date"] != today:
        record["date"] = today
        record["count"] = 0

    if record["count"] >= GEMINI_DAILY_LIMIT_REQUESTS:
        logger.warning(f"⚠️ Gemini günlük limit aşıldı: {user_id}")
        return False

    record["count"] += 1
    return True

def is_authorized(update: Update) -> bool:
    user_id = str(update.effective_user.id)
    if MY_TELEGRAM_ID and user_id != MY_TELEGRAM_ID:
        logger.warning(f"🚫 Yetkisiz erişim denemesi: {user_id}")
        return False
    if update.effective_chat.type != "private":
        logger.warning(f"🚫 Grup mesajı reddedildi: {update.effective_chat.id}")
        return False
    if update.message and update.message.forward_origin:
        logger.warning(f"🚫 Yönlendirilen mesaj reddedildi: {user_id}")
        return False
    if update.message:
        age = (datetime.now(timezone.utc) - update.message.date).total_seconds()
        if age > 60:
            logger.warning(f"🚫 Eski mesaj reddedildi (yaş: {age}s): {user_id}")
            return False
    return True

# ── DOSYA YOLU GUVENLIGI ──────────────────────────────────────────

def safe_path(filename: str) -> Path | None:
    """Path traversal saldırılarına karşı korunan güvenli path çözümü."""
    try:
        target = (WORKSPACE / filename).resolve()
        if not target.is_relative_to(WORKSPACE):
            logger.warning(f"🚫 Path traversal denemesi: {filename}")
            return None
        return target
    except Exception as e:
        logger.error(f"Path çözümleme hatası: {e}")
        return None

def is_scope_allowed(path: Path, scope: str) -> bool:
    allowed = SANDBOX_SCOPES.get(scope, SANDBOX_SCOPES["general"])
    rel_str = str(path.relative_to(WORKSPACE))
    for rule in allowed:
        if rel_str == rule or rel_str.startswith(f"{rule}/"):
            return True
    return False

def scoped_path(filename: str, scope: str = "general") -> Path | None:
    path = safe_path(filename)
    if path is None:
        return None
    if not is_scope_allowed(path, scope):
        logger.warning(f"🚫 Scope ihlali: scope={scope} path={filename}")
        return None
    return path

def is_allowed_write_file(path: Path) -> bool:
    return path.suffix.lower() in ALLOWED_WRITE_EXTENSIONS

# ── VERI SINIFLANDIRMA ──────────────────────────────────────────

def _load_classification_policy() -> dict:
    """policies/data_classification.yaml dosyasini okur."""
    policy_path = Path(__file__).parent / "policies" / "data_classification.yaml"
    if not policy_path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def classify_file(filepath: str | Path) -> str:
    """
    Dosya yoluna göre sınıf döndürür: PUBLIC, PRIVATE, PROJECT, SECRET.
    Eşleşme yoksa policy'deki varsayılan (PRIVATE) döner.
    """
    policy  = _load_classification_policy()
    default = policy.get("defaults", {}).get("unclassified", "PRIVATE")
    patterns = policy.get("patterns", {})

    path = Path(filepath)
    try:
        if path.is_absolute():
            rel = str(path.resolve().relative_to(WORKSPACE)).replace("\\", "/")
        else:
            rel = str(path).replace("\\", "/")
    except ValueError:
        rel = str(path).replace("\\", "/")

    import fnmatch
    for classification, globs in patterns.items():
        for pattern in globs:
            if fnmatch.fnmatch(rel, pattern):
                return classification

    return default


def is_gemini_allowed(filepath: str | Path) -> bool:
    """Bu dosya Gemini'ye gönderilebilir mi?"""
    policy         = _load_classification_policy()
    classification = classify_file(filepath)
    classes        = policy.get("classifications", {})
    return classes.get(classification, {}).get("gemini_allowed", False)

def classification_report_line(filepath: str | Path) -> str:
    classification = classify_file(filepath)
    gemini_state = "izinli" if is_gemini_allowed(filepath) else "kapalı"
    return f"{filepath}: {classification} (Gemini dosya aktarımı: {gemini_state})"

# ── AG GUVENLIGI (SSRF) ──────────────────────────────────────────

def is_public_hostname(hostname: str) -> bool:
    """Hostname'in yalnizca public IP adreslerine cozuldugunu dogrular."""
    if hostname.lower() in {"localhost"}:
        logger.warning(f"🚫 Localhost erişim engellendi: {hostname}")
        return False

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as e:
        logger.warning(f"🚫 Hostname çözümlenemedi: {hostname} ({e})")
        return False

    if not addresses:
        return False

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            logger.warning(f"🚫 Geçersiz IP çözümlemesi: {hostname} -> {address}")
            return False

        if not ip.is_global:
            logger.warning(f"🚫 Public olmayan IP engellendi: {hostname} -> {ip}")
            return False

    return True

def is_safe_url(url: str) -> bool:
    """SSRF ve kötü niyetli URL'lere karşı koruyan URL doğrulayıcı."""
    try:
        # Temel format kontrolü
        if not url or len(url) > 2048:
            return False
        
        parsed = urlparse(url)
        
        # Protokol kontrolü
        if parsed.scheme not in ["http", "https"]:
            logger.warning(f"🚫 Geçersiz protokol: {parsed.scheme}")
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False

        host_lc = hostname.lower()
        if WEB_RADAR_ALLOWLIST:
            allowlisted = any(
                host_lc == domain or host_lc.endswith(f".{domain}")
                for domain in WEB_RADAR_ALLOWLIST
            )
            if not allowlisted:
                logger.warning(f"🚫 Allowlist dışı host engellendi: {host_lc}")
                return False

        if parsed.username or parsed.password:
            logger.warning("🚫 URL kullanıcı bilgisi içeriyor")
            return False

        return is_public_hostname(hostname)
    except Exception as e:
        logger.error(f"URL doğrulama hatası: {e}")
        return False

# ── MODEL GIZLILIK PROFILI ──────────────────────────────────────

# litellm/config.yaml icindeki takma adlar bu iki onekten birini
# kullanmak ZORUNDADIR. Kural tests/test_architecture.py tarafindan
# dogrulanir; uymayan bir takma ad testte yakalanir.
YEREL_ONEK = "yerel-"
DIS_ONEK = "dis-"


def privacy_profile(model_alias: str) -> str:
    """Bir model takma adinin gizlilik profilini dondurur.

    Donen degerler:
        "yerel"    - Model bu makinede calisir, veri disari cikmaz.
        "dis"      - Model bir saglayicida calisir, veri makineden ayrilir.
        "bilinmiyor" - Takma ad kurala uymuyor.

    "bilinmiyor" bilincli olarak "dis" degil: cagiran taraf bunu
    ayirt edebilmeli. Ancak guvenli varsayilan icin is_local()
    kullanin; o, bilinmeyen bir adi asla yerel saymaz.
    """
    if model_alias.startswith(YEREL_ONEK):
        return "yerel"
    if model_alias.startswith(DIS_ONEK):
        return "dis"
    return "bilinmiyor"


def is_local(model_alias: str) -> bool:
    """Bu model bu makinede mi calisiyor?

    Guvenli varsayilan: yalnizca ACIKCA yerel olarak isaretlenmis
    takma adlar True doner. Bilinmeyen bir ad yerel SAYILMAZ --
    boylece yanlis isimlendirilmis bir model, veri sizdirma
    kontrolunu sessizce atlayamaz.
    """
    return privacy_profile(model_alias) == "yerel"


def leaves_machine(model_alias: str) -> bool:
    """Bu modele gonderilen veri makineden cikar mi?

    is_local()'in tersi degildir: bilinmeyen bir takma ad icin de
    True doner. Emin olunmayan durumda "veri cikiyor" kabul edilir.
    """
    return not is_local(model_alias)


# ── MODEL POLITIKA KAPISI ───────────────────────────────────────

def assert_model_allowed(
    model_alias: str,
    filepaths: list[str] | None = None,
) -> str | None:
    """Bu icerik bu modele gonderilebilir mi?

    Donen deger:
        None  - izin var
        str   - engellendi, kullaniciya gosterilecek mesaj

    Kural: veri makineden cikacaksa, gonderilecek her dosyanin
    disari aktarima izinli olmasi gerekir. Yerel modellerde
    kontrol yapilmaz cunku veri zaten makineden ayrilmaz.
    """
    if is_local(model_alias):
        return None

    if privacy_profile(model_alias) == "bilinmiyor":
        logger.warning(f"🚫 Tanimsiz model takma adi: {model_alias}")
        return (
            f"Güvenlik: '{model_alias}' tanımlı bir model değil. "
            f"Takma adlar 'yerel-' veya 'dis-' ile başlamalıdır."
        )

    for yol in filepaths or []:
        if not is_gemini_allowed(yol):
            sinif = classify_file(yol)
            logger.warning(
                f"🚫 Dis model engellendi: {model_alias} <- {yol} ({sinif})"
            )
            return (
                f"Güvenlik: '{yol}' dosyası {sinif} sınıfında ve dış "
                f"servislere aktarılamaz. Bu istek için yerel bir model kullanın."
            )

    return None

# ── ARAMA MOTORU TESPITI ────────────────────────────────────────

# Arama motoru sonuc sayfalari kazinamaz: bot isteklerine JavaScript'e
# bagimli bir kabuk ya da onay sayfasi donerler. Model bu neredeyse bos
# icerigi "arastirma yaptim" sanip kaynaksiz iddialar uretebilir.
# Bu, sessiz basarisizligin en tehlikeli turudur.
SEARCH_ENGINE_HOSTS = {
    "bing.com", "duckduckgo.com", "search.yahoo.com", "baidu.com",
    "search.brave.com", "ecosia.org", "startpage.com", "qwant.com",
    "yandex.com", "yandex.com.tr", "yandex.ru",
}


def is_search_engine(url: str) -> bool:
    """Bu adres bir arama motoru sonuc sayfasi mi?"""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    # google.com, google.com.tr, google.de ... hepsi
    if host == "google" or host.startswith("google."):
        return True
    return host in SEARCH_ENGINE_HOSTS