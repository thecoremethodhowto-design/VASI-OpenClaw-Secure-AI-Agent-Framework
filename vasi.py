import os
import json
import glob
import ipaddress
import socket
import requests
import logging
import html
from functools import wraps
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from ollama import Client, ResponseError
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes, CallbackQueryHandler
)

load_dotenv()

# ── ENVIRONMENT VALIDATION ────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace")).resolve()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")  # Optional güvenlik
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
WEB_RADAR_ALLOWLIST_RAW = os.getenv("WEB_RADAR_ALLOWLIST", "")
PENDING_ACTION_TTL_SECONDS = int(os.getenv("PENDING_ACTION_TTL_SECONDS", "600"))
GEMINI_DAILY_LIMIT_REQUESTS = int(os.getenv("GEMINI_DAILY_LIMIT_REQUESTS", "60"))
LOG_FILE = Path(os.getenv("VASI_LOG_FILE", "/tmp/vasi_audit.log"))
NOTES_FILE = os.getenv("VASI_NOTES_FILE", "notlar/NOTES.md")
CHANNEL_STYLE_FILE = os.getenv("VASI_CHANNEL_STYLE_FILE", "skills/youtube_icerik.md")
CODE_STYLE_FILE = os.getenv("VASI_CODE_STYLE_FILE", "skills/kod_yardimcisi.md")

if not TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN env variable zorunludur!")
if not MY_TELEGRAM_ID:
    raise ValueError("❌ MY_TELEGRAM_ID env variable zorunludur!")
if not WORKSPACE.exists():
    raise ValueError(f"❌ WORKSPACE_DIR mevcut değil: {WORKSPACE}")

# ── OLLAMA CLIENT SETUP (API KEY SECURITY) ────────────────────────────────────
# Ollama bağlantısını API key ile güvenli hale getir
ollama_headers = {}
if OLLAMA_API_KEY:
    ollama_headers["X-API-Key"] = OLLAMA_API_KEY
    logger_setup_msg = f"✅ Ollama API Key ile güvenli bağlantı"
else:
    logger_setup_msg = f"⚠️ Ollama API Key ayarlanmamış (localhost ortamında güvenli)"

LOCAL_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"}
parsed_ollama_host = urlparse(OLLAMA_HOST)
ollama_hostname = parsed_ollama_host.hostname or ""
if not OLLAMA_API_KEY and ollama_hostname not in LOCAL_OLLAMA_HOSTS:
    raise ValueError("❌ Uzak Ollama sunucusu için OLLAMA_API_KEY zorunludur!")

ollama_client = Client(host=OLLAMA_HOST, headers=ollama_headers if ollama_headers else None)
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── LOGGING SETUP ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('vasi')
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

# Log Ollama setup durumunu başta
logger.debug(logger_setup_msg)

# ── CONSTANTS ────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_CODE_CONTEXT_FILE_SIZE = 80 * 1024  # 80KB
MAX_WEB_TIMEOUT = 10  # saniye
MAX_WEB_BYTES = 2 * 1024 * 1024  # 2MB
RATE_LIMIT_WINDOW = 60  # saniye
RATE_LIMIT_REQUESTS = 20  # İstek sayısı
GEMINI_RATE_LIMIT_REQUESTS = 5  # İstek sayısı
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

# ── RATE LIMITING ───────────────────────────────────────────────────────────
USER_RATE_LIMITS = {}
GEMINI_RATE_LIMITS = {}
GEMINI_DAILY_COUNTERS = {}

# ── MODEL KADROSU ──────────────────────────────────────────────────────────────
MODELS = {
    "gatekeeper": os.getenv("VASI_MODEL_GATEKEEPER", "llama3.1:8b"),
    "strateji":   os.getenv("VASI_MODEL_STRATEJI", "llama3.1:8b"),
    "teknik":     os.getenv("VASI_MODEL_TEKNIK", "llama3.1:8b"),
    "kod":        os.getenv("VASI_MODEL_KOD", "qwen3-coder:30b"),
    "gorsel":     os.getenv("VASI_MODEL_GORSEL", "llama3.1:8b"),
}

# ── ALLOWED TOOLS WHITELIST ────────────────────────────────────────────────────
ALLOWED_TOOL_NAMES = {"skill_get_time", "skill_web_radar"}
CODE_CONTEXT_FILES = (
    "vasi.py",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    ".dockerignore",
    ".gitignore",
)
CODE_REVIEW_GUARDRAILS = """Bilinen guvenlik gercekleri:
- Gercek .env dosyasi kod baglamina dahil edilmez; .gitignore ve .dockerignore tarafindan korunur.
- .env.example gercek sir icermez ve kod inceleme baglamina verilmez.
- logger_setup_msg API key degerini degil, sadece var/yok durumunu soyler; bunu tek basina sir sizintisi sayma.
- safe_path, resolve() + is_relative_to(WORKSPACE) kullandigi icin klasik '..' path traversal engellenir.
- Workspace icinde alt klasor kullanimi bilincli olarak desteklenir; slash karakterini tek basina risk sayma.
- Telegram reply_text icin parse_mode verilmedikce HTML/JS calismaz; plain text XSS bulgusu yazma.
- is_safe_url zaten URL uzunlugu, protokol, hostname ve public IP kontrolu yapar; ayni kontrolleri tekrar onerme.
- Yazma/ekleme/silme sadece .md, .txt, .json, .yaml, .yml ve .csv uzantilarinda calisir.
- Model adlari .env/Docker environment ile sistem sahibi tarafindan belirlenir; Telegram kullanicisi model adini enjekte edemez.
- Workspace icinde alt klasor desteklendigi icin '/' karakterini yasaklamak dogru onerme degildir.
- Kullanicinin not icerigini sanitize etmek veri kaybidir; komut calistirma veya HTML parse yoksa guvenlik bulgusu sayma.
- Komut girdisini alfanumerik karakterlere indirgemek dosya yollari, Turkce metin, JSON/YAML ve not kullanimini bozar.

Bulgu kurali:
- Sadece somut guvenlik acigi veya anlamli risk varsa onler.
- Hardening/fazladan temizlik onerilerini 'acik' gibi sunma.
- Her bulgu icin mevcut koddan net kanit ver.
- Kanit guardrail ile celisiyorsa bulguyu cikarma.
"""
SECRET_KEYS = (
    "TOKEN",
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "PASS",
    "AUTH",
    "COOKIE",
)

HELP_TEXT = """Vasi aktif.

Komutlar:
/liste - Workspace dosyalarını listeler
/oku <dosya> - Workspace içindeki dosyayı okur
/yaz <dosya> | <icerik> - Onayla dosya yazar/üzerine yazar
/ekle <dosya> | <icerik> - Onayla dosyaya tarihli ek yapar
/sil <dosya> - Onayla dosyayı siler
/fikir <fikir> - Fikri araştırır, onayla not dosyana ekler
/ara <konu> - Gemini + Google Search ile kaynaklı internet araştırması yapar
/ara_not <konu> - Gemini araştırmasını onayla not dosyana ekler
/ara_ozet <konu> - Kısa, kaynaklı Gemini özeti üretir
/ara_senaryo <konu> - Gemini araştırması + kanal tarzıyla video paketi üretir
/tarzim <kanal tarzi> - YouTube kanal tarzını kaydeder
/senaryo <konu> - Kanal tarzına göre senaryo, başlık, açıklama ve kapak önerir
/kod <soru> - Workspace bağlamıyla kod yardımı verir
/kod_patch <istek> - Uygulanabilir patch taslağı üretir (dosya yazmaz)
/guvenlik - Mevcut güvenlik kontrollerini deterministik raporlar
/rapor <konu> - Rapor taslağı üretir, onayla kaydeder
"""

# ══════════════════════════════════════════════════════════════════════════════
# 1. GÜVENLİK KATMANI
# ══════════════════════════════════════════════════════════════════════════════

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

def sanitize_for_log(text: str, max_len: int = 240) -> str:
    cleaned = " ".join(text.replace("\n", " ").split())
    return cleaned[:max_len]

def audit_event(event: str, user_id: str, detail: str) -> None:
    logger.info(f"AUDIT | {event} | user={user_id} | {sanitize_for_log(detail)}")

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

def mask_sensitive_line(line: str, filename: str) -> str:
    if filename != ".env.example":
        return line

    upper = line.upper()
    if not any(key in upper for key in SECRET_KEYS):
        return line

    for sep in ("=",):
        if sep in line:
            key, _ = line.split(sep, 1)
            return f"{key}{sep} <masked>"
    return line

def read_project_file_for_context(filename: str) -> str:
    path = Path(filename).resolve()
    repo_root = Path(__file__).resolve().parent

    try:
        if not path.is_relative_to(repo_root):
            return f"[{filename}] skipped: path disallowed"
    except ValueError:
        return f"[{filename}] skipped: path disallowed"

    if not path.exists() or not path.is_file():
        return f"[{filename}] missing"

    if path.stat().st_size > MAX_CODE_CONTEXT_FILE_SIZE:
        return f"[{filename}] skipped: file too large"

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        masked = "\n".join(mask_sensitive_line(line, filename) for line in lines)
        return f"### {filename}\n```text\n{masked}\n```"
    except Exception as e:
        logger.warning(f"Kod bağlamı okunamadı: {filename} ({e})")
        return f"[{filename}] skipped: read error"

def build_code_context() -> str:
    return "\n\n".join(read_project_file_for_context(filename) for filename in CODE_CONTEXT_FILES)

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

# ══════════════════════════════════════════════════════════════════════════════
# 2. OPENCLAW YETENEKLERİ (READ-ONLY TOOLS)
# ══════════════════════════════════════════════════════════════════════════════

def skill_get_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def skill_web_radar(url: str) -> str:
    """Güvenli web scraping - SSRF ve XSS korumalı."""
    if not is_safe_url(url):
        logger.warning(f"🚫 Güvensiz URL reddedildi: {url}")
        return "Hata: Güvensiz veya geçersiz URL."
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Vasi-Bot/1.0)"}
        response = requests.get(
            url,
            headers=headers,
            timeout=MAX_WEB_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
        response.raise_for_status()

        if 300 <= response.status_code < 400:
            logger.warning(f"🚫 Redirect engellendi: {url} -> {response.headers.get('Location')}")
            return "Hata: Yonlendirme guvenlik nedeniyle engellendi."

        content_type = response.headers.get("Content-Type", "")
        if content_type and "text/html" not in content_type and "text/plain" not in content_type:
            logger.warning(f"🚫 Desteklenmeyen içerik türü: {content_type}")
            return "Hata: Desteklenmeyen icerik turu."

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_WEB_BYTES:
                logger.warning(f"🚫 Web yanıtı çok büyük: {url}")
                return "Hata: Web yaniti cok buyuk."
            chunks.append(chunk)
        
        # Charset kontrol et
        if response.encoding is None:
            response.encoding = 'utf-8'

        response_text = b"".join(chunks).decode(response.encoding, errors="replace")
        
        soup = BeautifulSoup(response_text, 'html.parser')
        
        # Tehlikeli elementleri kaldır
        for element in soup(["script", "style", "iframe", "object"]):
            element.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        
        # HTML entities'i escape et (XSS koruması)
        text = html.escape(text)
        
        logger.info(f"✅ Web radar: {url[:50]}...")
        return text[:8000] if len(text) > 8000 else text
    except requests.Timeout:
        logger.error(f"⏱️ Web radar timeout: {url}")
        return "Hata: Istek zaman asımı (timeout)."
    except requests.RequestException as e:
        logger.error(f"🌐 Web radar hatasI: {e}")
        return f"Radar Hatasi: Sayfa yüklenemedi."
    except Exception as e:
        logger.error(f"❌ Web radar kritik hata: {e}", exc_info=True)
        return "Radar Hatasi: İçsel hata."

def extract_gemini_sources(response) -> list[str]:
    """Gemini grounding metadata icinden okunabilir kaynak listesini cikarir."""
    sources = []
    try:
        candidates = getattr(response, "candidates", []) or []
        if not candidates:
            return sources
        metadata = getattr(candidates[0], "grounding_metadata", None)
        chunks = getattr(metadata, "grounding_chunks", []) if metadata else []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if not web:
                continue
            title = getattr(web, "title", "") or "Kaynak"
            uri = getattr(web, "uri", "") or ""
            if uri:
                sources.append(f"- {title}: {uri}")
    except Exception as e:
        logger.warning(f"Gemini kaynakları okunamadı: {e}")
    return sources[:8]

def gemini_grounded_research(topic: str) -> str:
    """Gemini + Google Search grounding ile kaynakli arastirma yapar."""
    if not GEMINI_API_KEY or gemini_client is None:
        return "Hata: GEMINI_API_KEY ayarlanmamış. .env dosyasına ekleyip container'ı yeniden başlatın."

    if not topic or len(topic) > 2000:
        return "Hata: Araştırma konusu boş veya çok uzun."

    prompt = (
        "Türkçe yanıt ver. Güncel web araştırması yap ve iddiaları kaynaklandır. "
        "Çıktı şu bölümleri içersin: Kısa cevap, bulgular, kaynaklara dayalı notlar, "
        "riskler/emin olunmayan noktalar, uygulanabilir ilk 3 adım. "
        "Workspace, dosya içeriği, token veya özel veri isteme.\n\n"
        f"Araştırma konusu: {topic}"
    )

    try:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(
            tools=[grounding_tool],
            temperature=0.2,
        )
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        text = getattr(response, "text", "") or "Gemini yanıt metni üretemedi."
        sources = extract_gemini_sources(response)
        if sources:
            text = f"{text}\n\nKaynaklar:\n" + "\n".join(sources)
        return text[:12000]
    except Exception as e:
        logger.error(f"❌ Gemini araştırma hatası: {e}", exc_info=True)
        return "Hata: Gemini araştırması tamamlanamadı."

def gemini_grounded_summary(topic: str) -> str:
    """Gemini ile kisa ve kaynakli arastirma ozeti."""
    if not GEMINI_API_KEY or gemini_client is None:
        return "Hata: GEMINI_API_KEY ayarlanmamış. .env dosyasına ekleyip container'ı yeniden başlatın."
    if not topic or len(topic) > 2000:
        return "Hata: Araştırma konusu boş veya çok uzun."

    prompt = (
        "Türkçe yanıt ver. Güncel web araştırması yap. "
        "Çıktı en fazla 8 madde olsun: 1 paragraf özet + 5 kritik bulgu + 2 risk notu. "
        "Kısa, net, uygulanabilir yaz.\n\n"
        f"Konu: {topic}"
    )
    try:
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[grounding_tool], temperature=0.1)
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        text = getattr(response, "text", "") or "Gemini kısa özet üretemedi."
        sources = extract_gemini_sources(response)
        if sources:
            text = f"{text}\n\nKaynaklar:\n" + "\n".join(sources)
        return text[:9000]
    except Exception as e:
        logger.error(f"❌ Gemini kısa özet hatası: {e}", exc_info=True)
        return "Hata: Gemini kısa özet üretilemedi."

def run_model_with_tools(
    model: str,
    user_prompt: str,
    system_prompt: str | None = None,
    options: dict | None = None,
) -> str:
    """Ollama modelini guvenli tool whitelist'i ile calistirir."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = ollama_client.chat(model=model, messages=messages, tools=OPENCLAW_TOOLS, options=options)
    except ResponseError as e:
        if getattr(e, "status_code", None) == 404:
            return (
                f"Model bulunamadı: {model}\n\n"
                f"Önce şu komutla modeli indir:\n"
                f"docker compose exec ollama ollama pull {model}"
            )
        logger.error(f"❌ Ollama model hatası: {e}", exc_info=True)
        return f"Model hatası: {getattr(e, 'error', str(e))}"

    message_data = response["message"]

    if message_data.get("tool_calls"):
        messages.append(message_data)
        for tool in message_data["tool_calls"]:
            func_name = tool["function"]["name"]
            args = tool["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            if func_name not in ALLOWED_TOOL_NAMES:
                logger.warning(f"🚫 Yetkisiz tool çağrısı: {func_name}")
                tool_result = "Güvenlik: Bu araç kullanımı yasaktır."
            elif func_name == "skill_get_time":
                tool_result = skill_get_time()
            elif func_name == "skill_web_radar":
                tool_result = skill_web_radar(args.get("url", ""))
            else:
                tool_result = "Bilinmeyen arac."

            messages.append({"role": "tool", "content": tool_result, "name": func_name})

        try:
            final_response = ollama_client.chat(model=model, messages=messages, options=options)
        except ResponseError as e:
            if getattr(e, "status_code", None) == 404:
                return (
                    f"Model bulunamadı: {model}\n\n"
                    f"Önce şu komutla modeli indir:\n"
                    f"docker compose exec ollama ollama pull {model}"
                )
            logger.error(f"❌ Ollama final yanıt hatası: {e}", exc_info=True)
            return f"Model hatası: {getattr(e, 'error', str(e))}"
        return final_response["message"].get("content", "")

    return message_data.get("content", "")

OPENCLAW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "skill_get_time",
            "description": "Sistemin guncel tarih ve saatini verir.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_web_radar",
            "description": "Bir web sitesinin (URL) metin icerigini okur. Arastirma yapmak icin zorunludur.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Tam web adresi (http://...)"}},
                "required": ["url"]
            }
        }
    }
]

# ══════════════════════════════════════════════════════════════════════════════
# 3. DOSYA İŞLEMLERİ (KAPALI DEVRE)
# ══════════════════════════════════════════════════════════════════════════════

def list_workspace_files(scope: str = "general") -> str:
    files = list(WORKSPACE.rglob("*"))
    if not files: return "Workspace bos."
    visible = []
    for f in sorted(files):
        if f.is_file() and is_scope_allowed(f, scope):
            visible.append(f"  {f.relative_to(WORKSPACE)}")
    if not visible:
        return f"Scope '{scope}' icin görünür dosya yok."
    return "Workspace icerigi:\n" + "\n".join(visible)

def read_file(filename: str, scope: str = "general") -> tuple[str, str]:
    """Güvenli dosya okuma."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        return "", "Güvenlik: Bu scope için dosya erişimi engellendi."
    if not path.exists():
        matches = [m for m in WORKSPACE.rglob(filename) if m.is_file() and is_scope_allowed(m, scope)]
        if not matches:
            logger.warning(f"📄 Dosya bulunamadı: {filename}")
            return "", f"'{filename}' bulunamadi."
        path = matches[0]
    try:
        if not path.is_file():
            return "", "Hata: Sadece dosya okunabilir."
        if path.stat().st_size > MAX_FILE_SIZE:
            logger.warning(f"📦 Okuma engellendi, dosya çok büyük: {filename}")
            return "", f"Hata: Dosya çok büyük (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."
        content = path.read_text(encoding="utf-8", errors="replace")
        logger.info(f"📖 Dosya okundu: {path.relative_to(WORKSPACE)}")
        return content[:12000], ""
    except PermissionError:
        logger.error(f"🚫 İzin hatası: {filename}")
        return "", f"Hata: Dosya erişim izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya okuma hatası: {e}")
        return "", "Hata: Dosya okunamadı."

def save_file(filename: str, content: str, scope: str = "general") -> str:
    """Güvenli dosya yazma - boyut sınırı ile."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya yazma engellendi: {filename}")
        return "Güvenlik: Bu scope için yazma engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı: {filename}")
        return "Güvenlik: Sadece .md, .txt, .json, .yaml, .yml ve .csv dosyaları yazılabilir."
    
    # File size kontrolü
    if len(content) > MAX_FILE_SIZE:
        logger.warning(f"📦 Dosya çok büyük: {filename} ({len(content)} bytes)")
        return f"Hata: Dosya çok büyük (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info(f"💾 Dosya kaydedildi: {path.relative_to(WORKSPACE)} ({len(content)} bytes)")
        return f"'{filename}' kaydedildi."
    except PermissionError:
        logger.error(f"🚫 Yazma izni yok: {filename}")
        return "Hata: Dosya yazma izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya yazma hatası: {e}")
        return "Hata: Dosya kaydedilemedi."

def append_file(filename: str, content: str, scope: str = "general") -> str:
    """Güvenli dosya ekleme - tarih/saat damgası ile."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya ekleme engellendi: {filename}")
        return "Güvenlik: Bu scope için ekleme engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı: {filename}")
        return "Güvenlik: Sadece .md, .txt, .json, .yaml, .yml ve .csv dosyalarına ek yapılabilir."

    stamped_content = (
        f"\n\n---\n"
        f"### {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{content.strip()}\n"
    )

    current_size = path.stat().st_size if path.exists() and path.is_file() else 0
    if current_size + len(stamped_content.encode("utf-8")) > MAX_FILE_SIZE:
        logger.warning(f"📦 Dosya ekleme limiti aşıldı: {filename}")
        return f"Hata: Dosya çok büyük olur (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(stamped_content)
        logger.info(f"➕ Dosyaya eklendi: {path.relative_to(WORKSPACE)}")
        return f"'{filename}' dosyasına tarihli kayıt eklendi."
    except PermissionError:
        logger.error(f"🚫 Yazma izni yok: {filename}")
        return "Hata: Dosya yazma izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya ekleme hatası: {e}")
        return "Hata: Dosyaya eklenemedi."

def delete_file(filename: str, scope: str = "general") -> str:
    """Güvenli dosya silme - sadece workspace icindeki normal dosyalar."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya silme engellendi: {filename}")
        return "Güvenlik: Bu scope için silme engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı silme isteği: {filename}")
        return "Güvenlik: Sadece güvenli not/veri dosyaları silinebilir."

    if path.name.startswith("."):
        return "Güvenlik: Gizli/korumalı dosyalar silinemez."
    if not path.exists():
        return f"'{filename}' bulunamadi."
    if not path.is_file():
        return "Hata: Sadece dosya silinebilir."

    try:
        relative = path.relative_to(WORKSPACE)
        path.unlink()
        logger.warning(f"🗑️ Dosya silindi: {relative}")
        return f"'{relative}' silindi."
    except PermissionError:
        logger.error(f"🚫 Silme izni yok: {filename}")
        return "Hata: Dosya silme izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya silme hatası: {e}")
        return "Hata: Dosya silinemedi."

def split_filename_and_content(text: str) -> tuple[str, str] | None:
    if "|" not in text:
        return None
    filename, content = text.split("|", 1)
    filename = filename.strip()
    content = content.strip()
    if not filename or not content:
        return None
    return filename, content

def set_pending(context: ContextTypes.DEFAULT_TYPE, action: str, preview: str, **payload):
    context.user_data["pending_action"] = {
        "action": action,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Onayla", callback_data="pending:yes"),
        InlineKeyboardButton("İptal", callback_data="pending:no")
    ]])
    return preview, keyboard

def is_pending_expired(pending: dict) -> bool:
    created_at = pending.get("created_at")
    if not created_at:
        return True
    try:
        created_dt = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    age = (datetime.now(timezone.utc) - created_dt).total_seconds()
    return age > PENDING_ACTION_TTL_SECONDS

# ══════════════════════════════════════════════════════════════════════════════
# 4. YÖNLENDİRME (ROUTING) VE BOT KOMUTLARI
# ══════════════════════════════════════════════════════════════════════════════

def pick_model(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["kod", "script", "python"]): return MODELS["kod"]
    if any(k in t for k in ["analiz", "gorsel", "tablo"]): return MODELS["gorsel"]
    if any(k in t for k in ["arastir", "neden", "web", "site", "okut"]): return MODELS["teknik"]
    if any(k in t for k in ["e-posta", "rapor", "taslak"]): return MODELS["strateji"]
    return MODELS["gatekeeper"]

def build_system_prompt(model: str) -> str:
    return (
        f"Sen Vasi. {model} motoruyla calisiyorsun. Turkce yanit ver. "
        "Yüksek sinyalli, net, profesyonel ve muhendislik olcutlerine uygun konus. "
        "Eger internetten veya gercek zamanli bir bilgi alman gerekirse yeteneklerini (tools) kullan."
    )

def build_code_system_prompt(model: str) -> str:
    return (
        f"Sen Vasi'nin kod yardımı modusun. {model} motoruyla çalışıyorsun. "
        "Türkçe, pratik ve proje bağlamına sadık yanıt ver. Kod inceleme disiplinin katı olsun. "
        "Sadece verilen dosya içeriklerine dayan; bilmediğin şeyi biliyor gibi yazma. "
        "Komut önerirken yıkıcı komutlar önerme. Gizli anahtar, token veya .env içeriği isteme. "
        "Kod değişikliği gerekiyorsa önce güvenlik etkisini açıkla; botun otomatik dosya değiştirme yetkisi olmadığını belirt. "
        "Yanlış dış servis URL'leri veya hayali API komutları uydurma. "
        "Telegram reply_text parse_mode verilmedikçe HTML çalıştırmaz; bunu XSS diye sunma. "
        "Yerel Ollama için http://localhost, http://host.docker.internal veya Docker içi http://ollama normal kabul edilir. "
        "safe_path resolve()+is_relative_to() kullandığında '..' kontrolünü ayrıca önermek genelde yanlış pozitiftir. "
        "Not dosyalarına HTML/JS yazılmasını tek başına XSS sayma; Telegram parse_mode yoksa metin olarak gönderilir. "
        "Dosya adında '/' kullanımını risk sayma; workspace içinde alt klasör desteklenir. "
        "Model adı env ile sistem sahibi tarafından verilir, Telegram kullanıcısı model seçemez; bunu enjeksiyon sayma. "
        "Kullanıcı not içeriğini veya genel komut metnini sanitize etmeyi güvenlik bulgusu diye önerme; veri kaybı oluşturur. "
        "Her bulgu için koddaki somut kanıtı belirt; kanıt yoksa önerme. "
        "Bulgu yoksa bunu açıkça söyle ve yalnızca düşük öncelikli iyileştirmeleri ayrı bölümde ver."
    )

def build_security_report() -> str:
    ollama_host = urlparse(OLLAMA_HOST).hostname or ""
    ollama_scope = "yerel/izinli" if ollama_host in LOCAL_OLLAMA_HOSTS else "uzak"
    api_key_state = "var" if bool(OLLAMA_API_KEY) else "yok"
    allowlist_state = ", ".join(WEB_RADAR_ALLOWLIST) if WEB_RADAR_ALLOWLIST else "kapalı (public hostlara açık)"

    return f"""# Vasi Güvenlik Durumu

## Aktif Kontroller
- Yetkilendirme: Sadece `MY_TELEGRAM_ID` ile eşleşen kullanıcı kabul edilir.
- Chat sınırı: Grup mesajları ve yönlendirilen mesajlar reddedilir.
- Rate limit: Kullanıcı başına {RATE_LIMIT_WINDOW} saniyede {RATE_LIMIT_REQUESTS} istek sınırı var.
- Workspace sınırı: Dosya yolları `resolve()` + `is_relative_to(WORKSPACE)` ile workspace dışına çıkamaz.
- Yazma/silme sınırı: Sadece {", ".join(sorted(ALLOWED_WRITE_EXTENSIONS))} uzantıları desteklenir.
- Silme sınırı: Klasörler ve gizli dosyalar silinmez.
- Yazma onayı: `/yaz`, `/ekle`, `/sil`, `/fikir`, `/senaryo`, `/ara_senaryo`, `/rapor` işlemleri Telegram onay butonu ister.
- Scope izolasyonu: `youtube` komutları `youtube/`, `notlar/`, `skills/youtube_icerik.md`, `skills/arastirma.md` alanında; `kod` komutları `projeler/` ve `skills/kod_yardimcisi.md` alanında çalışır.
- Pending TTL: Onay bekleyen işlemler {PENDING_ACTION_TTL_SECONDS // 60} dakika sonra otomatik geçersiz olur.
- SSRF koruması: Web aracı sadece `http/https`, public hostname/IP, redirect kapalı ve {MAX_WEB_BYTES // 1024 // 1024}MB yanıt limitiyle çalışır.
- Web radar allowlist: {allowlist_state}
- Gemini araştırması: Sadece `/ara`, `/ara_not`, `/ara_ozet` ve `/ara_senaryo` komutlarında çalışır; workspace dosyaları Gemini'ye otomatik gönderilmez.
- Gemini rate limit: Kullanıcı başına {RATE_LIMIT_WINDOW} saniyede {GEMINI_RATE_LIMIT_REQUESTS} araştırma sınırı var.
- Gemini günlük limit: Kullanıcı başına günlük {GEMINI_DAILY_LIMIT_REQUESTS} araştırma.
- Tool whitelist: Model sadece {", ".join(sorted(ALLOWED_TOOL_NAMES))} araçlarını çağırabilir.
- Docker hardening: `read_only`, `tmpfs /tmp`, `no-new-privileges`, `cap_drop: ALL` compose dosyasında tanımlı.
- Sır koruması: `.env` git/docker ignore içinde; loglarda `httpx` Telegram URL logları susturuldu.
- Audit izi: Hassas içerik maskeleyen `AUDIT` satırları tutulur.
- Ollama host: `{OLLAMA_HOST}` ({ollama_scope}); API key durumu: {api_key_state}. Uzak host key olmadan başlatılmaz.
- Gemini API key durumu: {"var" if bool(GEMINI_API_KEY) else "yok"}; model: `{GEMINI_MODEL}`.

## Gerçekçi Sıradaki İyileştirmeler
1. Otomatik test ekle: `safe_path`, `is_safe_url`, yazma uzantısı, onay akışı için küçük unit testler.
2. Log rotasyonu ekle: Uzun süreli kullanımda `/tmp/vasi_audit.log` veya host logları büyümesin.
3. Birim testleri artır: `pending TTL`, `daily Gemini limit` ve allowlist akışlarını kapsa.
4. Oran/limit ayarlarını `.env` üzerinden tamamen yönetilebilir yap.
5. Audit satırlarını ayrı dosya veya merkezi log sistemine yönlendir.

## Not
Bu rapor model tarafından tahmin edilmez; mevcut kod sabitlerinden ve güvenlik ayarlarından üretilir.
"""

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return
    logger.info(f"👤 Başlangıç komutu: {update.effective_user.id}")
    await update.message.reply_text(HELP_TEXT)

async def cmd_yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    await update.message.reply_text(HELP_TEXT)

async def cmd_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return
    logger.info(f"📋 Liste komutu: {update.effective_user.id}")
    await update.message.reply_text(list_workspace_files(scope="general"))

async def cmd_oku(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    filename = " ".join(context.args).strip()
    if not filename:
        await update.message.reply_text("❌ Kullanım: /oku <dosya>")
        return

    content, error = read_file(filename, scope="general")
    if error:
        await update.message.reply_text(error)
        return
    for i in range(0, len(content), 3900):
        await update.message.reply_text(content[i:i+3900])

async def cmd_yaz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    parsed = split_filename_and_content(" ".join(context.args))
    if not parsed:
        await update.message.reply_text("❌ Kullanım: /yaz <dosya> | <icerik>")
        return

    filename, content = parsed
    preview, keyboard = set_pending(
        context,
        "save",
        f"'{filename}' dosyasına yazılsın mı?\n\n{content[:700]}",
        filename=filename,
        content=content,
        scope="general",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_ekle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    parsed = split_filename_and_content(" ".join(context.args))
    if not parsed:
        await update.message.reply_text("❌ Kullanım: /ekle <dosya> | <icerik>")
        return

    filename, content = parsed
    preview, keyboard = set_pending(
        context,
        "append",
        f"'{filename}' dosyasına tarihli ek yapılsın mı?\n\n{content[:700]}",
        filename=filename,
        content=content,
        scope="general",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_sil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    filename = " ".join(context.args).strip()
    if not filename:
        await update.message.reply_text("❌ Kullanım: /sil <dosya>")
        return

    preview, keyboard = set_pending(
        context,
        "delete",
        f"'{filename}' dosyası silinsin mi? Bu işlem geri alınamaz.",
        filename=filename,
        scope="general",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_fikir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    fikir = " ".join(context.args).strip()
    if not fikir:
        await update.message.reply_text("❌ Kullanım: /fikir <araştırılacak fikir>")
        return
    audit_event("fikir_request", str(update.effective_user.id), fikir[:120])

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    prompt = (
        "Aşağıdaki fikri araştırılabilir bir çalışma notuna dönüştür. "
        "Gerekirse web_radar aracını kullan. Türkçe yaz. "
        "Çıktı şu bölümleri içersin: Kısa özet, neden değerli, araştırma notları, "
        "YouTube/uygulama açısından olası kullanım, ilk 3 aksiyon.\n\n"
        f"Fikir: {fikir}"
    )
    sonuc = run_model_with_tools(MODELS["teknik"], prompt, build_system_prompt(MODELS["teknik"]))
    preview, keyboard = set_pending(
        context,
        "append",
        f"Not dosyana eklensin mi? ({NOTES_FILE})\n\n{sonuc[:1200]}",
        filename=NOTES_FILE,
        content=sonuc,
        scope="youtube",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_ara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    user_id = str(update.effective_user.id)
    if not check_rate_limit(user_id) or not check_gemini_rate_limit(user_id):
        await update.message.reply_text("⚠️ Çok hızlı Gemini araştırması istediniz. Lütfen bekleyiniz.")
        return
    if not check_gemini_daily_limit(user_id):
        await update.message.reply_text("⚠️ Günlük Gemini araştırma limitine ulaştınız. Yarın tekrar deneyin.")
        return

    konu = " ".join(context.args).strip()
    if not konu:
        await update.message.reply_text("❌ Kullanım: /ara <araştırma konusu>")
        return
    audit_event("gemini_research", user_id, konu[:120])

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    sonuc = gemini_grounded_research(konu)
    for i in range(0, len(sonuc), 3900):
        await update.message.reply_text(sonuc[i:i+3900])

async def cmd_ara_not(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    user_id = str(update.effective_user.id)
    if not check_rate_limit(user_id) or not check_gemini_rate_limit(user_id):
        await update.message.reply_text("⚠️ Çok hızlı Gemini araştırması istediniz. Lütfen bekleyiniz.")
        return
    if not check_gemini_daily_limit(user_id):
        await update.message.reply_text("⚠️ Günlük Gemini araştırma limitine ulaştınız. Yarın tekrar deneyin.")
        return

    konu = " ".join(context.args).strip()
    if not konu:
        await update.message.reply_text("❌ Kullanım: /ara_not <araştırma konusu>")
        return
    audit_event("gemini_research_note", user_id, konu[:120])

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    sonuc = gemini_grounded_research(konu)
    preview, keyboard = set_pending(
        context,
        "append",
        f"Gemini araştırması not dosyana eklensin mi? ({NOTES_FILE})\n\n{sonuc[:1200]}",
        filename=NOTES_FILE,
        content=sonuc,
        scope="youtube",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_ara_ozet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    user_id = str(update.effective_user.id)
    if not check_rate_limit(user_id) or not check_gemini_rate_limit(user_id):
        await update.message.reply_text("⚠️ Çok hızlı Gemini araştırması istediniz. Lütfen bekleyiniz.")
        return
    if not check_gemini_daily_limit(user_id):
        await update.message.reply_text("⚠️ Günlük Gemini araştırma limitine ulaştınız. Yarın tekrar deneyin.")
        return

    konu = " ".join(context.args).strip()
    if not konu:
        await update.message.reply_text("❌ Kullanım: /ara_ozet <araştırma konusu>")
        return
    audit_event("gemini_summary", user_id, konu[:120])
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    sonuc = gemini_grounded_summary(konu)
    for i in range(0, len(sonuc), 3900):
        await update.message.reply_text(sonuc[i:i+3900])

async def cmd_ara_senaryo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    user_id = str(update.effective_user.id)
    if not check_rate_limit(user_id) or not check_gemini_rate_limit(user_id):
        await update.message.reply_text("⚠️ Çok hızlı Gemini araştırması istediniz. Lütfen bekleyiniz.")
        return
    if not check_gemini_daily_limit(user_id):
        await update.message.reply_text("⚠️ Günlük Gemini araştırma limitine ulaştınız. Yarın tekrar deneyin.")
        return

    konu = " ".join(context.args).strip()
    if not konu:
        await update.message.reply_text("❌ Kullanım: /ara_senaryo <video konusu>")
        return

    audit_event("gemini_scenario", user_id, konu[:120])
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    arastirma = gemini_grounded_research(konu)
    kanal_tarzi, _ = read_file(CHANNEL_STYLE_FILE, scope="youtube")
    if not kanal_tarzi:
        kanal_tarzi = "Kanal tarzı dosyası yok. Genel, net ve öğretici bir YouTube dili kullan."

    prompt = (
        "Aşağıdaki araştırma notları ve kanal tarzına göre YouTube videosu üretim paketi hazırla. "
        "Çıktı bölümleri: 10 başlık, en iyi 3 seçim ve gerekçe, video açıklaması, 15 etiket, "
        "thumbnail fikri, hook, bölüm bölüm senaryo, kapanış CTA.\n\n"
        f"Kanal tarzı:\n{kanal_tarzi[:5000]}\n\n"
        f"Araştırma notları:\n{arastirma[:9000]}\n\n"
        f"Konu:\n{konu}"
    )
    sonuc = run_model_with_tools(MODELS["strateji"], prompt, build_system_prompt(MODELS["strateji"]))
    out_name = f"youtube/senaryolar/ara_senaryo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    preview, keyboard = set_pending(
        context,
        "save",
        f"Araştırmalı senaryo hazır. '{out_name}' olarak kaydedilsin mi?\n\n{sonuc[:1200]}",
        filename=out_name,
        content=sonuc,
        scope="youtube",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_tarzim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    tarz = " ".join(context.args).strip()
    if not tarz:
        await update.message.reply_text("❌ Kullanım: /tarzim <kanal tarzı, hedef kitle, ton, örnekler>")
        return

    preview, keyboard = set_pending(
        context,
        "save",
        f"Kanal tarzı '{CHANNEL_STYLE_FILE}' dosyasına kaydedilsin mi?\n\n{tarz[:900]}",
        filename=CHANNEL_STYLE_FILE,
        content=tarz,
        scope="youtube",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_senaryo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    konu = " ".join(context.args).strip()
    if not konu:
        await update.message.reply_text("❌ Kullanım: /senaryo <video konusu>")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    kanal_tarzi, _ = read_file(CHANNEL_STYLE_FILE, scope="youtube")
    if not kanal_tarzi:
        kanal_tarzi = "Kanal tarzı dosyası yok. Genel, net, güçlü ve anlaşılır bir YouTube dili kullan."

    prompt = (
        "Aşağıdaki kanal tarzına göre YouTube videosu paketi hazırla. "
        "Çıktı şu bölümleri içersin: 10 başlık önerisi, en iyi 3 başlığın gerekçesi, "
        "video açıklaması, 15 etiket, kapak görseli fikri, thumbnail üzerindeki kısa metinler, "
        "hook, bölüm bölüm senaryo, kapanış CTA.\n\n"
        f"Kanal tarzı:\n{kanal_tarzi[:6000]}\n\n"
        f"Video konusu:\n{konu}"
    )
    sonuc = run_model_with_tools(MODELS["strateji"], prompt, build_system_prompt(MODELS["strateji"]))
    out_name = f"youtube/senaryolar/senaryo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    preview, keyboard = set_pending(
        context,
        "save",
        f"Senaryo hazır. '{out_name}' olarak kaydedilsin mi?\n\n{sonuc[:1200]}",
        filename=out_name,
        content=sonuc,
        scope="youtube",
    )
    await update.message.reply_text(preview, reply_markup=keyboard)

async def cmd_kod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    soru = " ".join(context.args).strip()
    if not soru:
        await update.message.reply_text("❌ Kullanım: /kod <kod sorusu veya yapmak istediğin değişiklik>")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    code_context = build_code_context()
    code_style, _ = read_file(CODE_STYLE_FILE, scope="code")
    prompt = (
        "Aşağıdaki proje dosyalarını ve güvenlik guardrail'lerini okuyarak kod yardımı ver. "
        "Cevabını mevcut kodun gerçekten yaptığı şeylere göre kur. "
        "Önce varsa güvenlik riski veya yanlış varsayımı söyle, sonra uygulanabilir önerileri ver. "
        "Dosyaları değiştirme; sadece öneri, küçük patch taslağı veya güvenli komut öner. "
        "Zaten yapılmış güvenlikleri tekrar önerme. Emin olmadığın konuyu 'kontrol edilmeli' diye işaretle. "
        "Her öneride 'Kanıt:' satırıyla ilgili mevcut kod davranışını göster; kanıt bulamıyorsan o öneriyi çıkar. "
        "Özellikle şu yanlış pozitiflerden kaçın: .env okunmadığı halde token kodda var demek; plain Telegram text'i XSS saymak; "
        "resolve()+is_relative_to() varken '..' traversal açığı demek; not içeriğini sanitize ederek kullanıcı notlarını bozmayı önermek. "
        "Eğer cevap için izinli bağlamda olmayan başka dosya gerekiyorsa kullanıcıdan açıkça dosya adını istemesini söyle.\n\n"
        f"{CODE_REVIEW_GUARDRAILS}\n\n"
        f"Kod yardimcisi skill talimatlari:\n{code_style[:4000]}\n\n"
        f"{list_workspace_files(scope='code')}\n\n"
        f"Proje dosya bağlamı:\n{code_context}\n\n"
        f"Soru:\n{soru}"
    )
    sonuc = run_model_with_tools(
        MODELS["kod"],
        prompt,
        build_code_system_prompt(MODELS["kod"]),
        options={"temperature": 0.1, "top_p": 0.4},
    )
    for i in range(0, len(sonuc), 3900):
        await update.message.reply_text(sonuc[i:i+3900])

async def cmd_kod_patch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return
    istek = " ".join(context.args).strip()
    if not istek:
        await update.message.reply_text("❌ Kullanım: /kod_patch <yapmak istediğin değişiklik>")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    code_context = build_code_context()
    code_style, _ = read_file(CODE_STYLE_FILE, scope="code")
    prompt = (
        "Sadece patch taslağı üret. Dosya yazma yok. "
        "Çıktı formatı: 1) Risk değerlendirmesi 2) Değişiklik planı 3) Örnek diff taslağı. "
        "Mevcut dosya bağlamına sadık kal.\n\n"
        f"Kod yardimcisi skill talimatlari:\n{code_style[:4000]}\n\n"
        f"Bağlam:\n{code_context}\n\n"
        f"İstek:\n{istek}"
    )
    sonuc = run_model_with_tools(
        MODELS["kod"],
        prompt,
        build_code_system_prompt(MODELS["kod"]),
        options={"temperature": 0.1, "top_p": 0.4},
    )
    for i in range(0, len(sonuc), 3900):
        await update.message.reply_text(sonuc[i:i+3900])

async def cmd_guvenlik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return

    report = build_security_report()
    for i in range(0, len(report), 3900):
        await update.message.reply_text(report[i:i+3900])

async def cmd_rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiz. Lütfen bekleyiniz.")
        return
    
    konu = " ".join(context.args)
    if not konu:
        await update.message.reply_text("❌ Kullanım: /rapor <konu>")
        return
    
    logger.info(f"📊 Rapor komutu: {update.effective_user.id} - Konu: {konu[:50]}")
    
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        sonuc = run_model_with_tools(
            MODELS["strateji"],
            f"Detayli rapor yaz: {konu}",
            build_system_prompt(MODELS["strateji"]),
        )
        out_name = f"notlar/rapor_{datetime.now().strftime('%H%M')}.md"
        context.user_data["pending_save"] = {
            "filename": out_name,
            "content": sonuc,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": "general",
        }
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Kaydet", callback_data="save_pending:evet"),
            InlineKeyboardButton("İptal", callback_data="save_pending:iptal")
        ]])
        await update.message.reply_text(f"Rapor hazir. Kaydedilsin mi?\n\n{sonuc[:300]}...", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"❌ Rapor üretme hatası: {e}", exc_info=True)
        await update.message.reply_text("❌ Rapor oluşturulamadı. Lütfen daha sonra deneyin.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_authorized(update):
        await query.edit_message_text("🚫 Yetkisiz erişim.")
        return
    
    logger.info(f"🔘 Callback: {query.data} - {update.effective_user.id}")
    user_id = str(update.effective_user.id)
    
    if query.data in {"save_pending:iptal", "pending:no"}:
        audit_event("pending_cancel", user_id, query.data)
        context.user_data.pop("pending_action", None)
        context.user_data.pop("pending_save", None)
        await query.edit_message_text("❌ İptal edildi.")
    elif query.data == "save_pending:evet":
        pending = context.user_data.get("pending_save")
        if pending:
            if is_pending_expired(pending):
                context.user_data.pop("pending_save", None)
                audit_event("pending_expired", user_id, "save_pending")
                await query.edit_message_text("⏱️ Onay süresi doldu. İşlem iptal edildi.")
                return
            result = save_file(
                pending["filename"],
                pending["content"],
                scope=pending.get("scope", "general"),
            )
            context.user_data.pop("pending_save", None)
            audit_event("pending_save_apply", user_id, pending["filename"])
            await query.edit_message_text(result)
        else:
            await query.edit_message_text("❌ Kaydetme verisi bulunamadı.")
    elif query.data == "pending:yes":
        pending = context.user_data.get("pending_action")
        if not pending:
            await query.edit_message_text("❌ Onay bekleyen işlem bulunamadı.")
            return
        if is_pending_expired(pending):
            context.user_data.pop("pending_action", None)
            audit_event("pending_expired", user_id, pending.get("action", "unknown"))
            await query.edit_message_text("⏱️ Onay süresi doldu. İşlem iptal edildi.")
            return

        action = pending.get("action")
        scope = pending.get("scope", "general")
        if action == "save":
            result = save_file(pending["filename"], pending["content"], scope=scope)
        elif action == "append":
            result = append_file(pending["filename"], pending["content"], scope=scope)
        elif action == "delete":
            result = delete_file(pending["filename"], scope=scope)
        else:
            result = "Hata: Bilinmeyen işlem."

        context.user_data.pop("pending_action", None)
        audit_event("pending_apply", user_id, f"{action}:{pending.get('filename', '-')}")
        await query.edit_message_text(result)

# ══════════════════════════════════════════════════════════════════════════════
# 5. AJAN AKIŞI (AGENTIC WORKFLOW + TOOL CALLING)
# ══════════════════════════════════════════════════════════════════════════════

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı mesaj gönderdiniz. Lütfen bekleyiniz.")
        return
    
    metin = update.message.text
    user_id = update.effective_user.id
    logger.info(f"💬 Mesaj alındı: {user_id} - {metin[:50]}...")
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    model = pick_model(metin)
    messages = [
        {"role": "system", "content": build_system_prompt(model)},
        {"role": "user", "content": metin}
    ]

    try:
        # AŞAMA 1: Modeli Yeteneklerle Birlikte Çağır
        response = ollama_client.chat(model=model, messages=messages, tools=OPENCLAW_TOOLS)
        message_data = response["message"]
        
        # AŞAMA 2: Model Bir Yetenek Kullanmak İstedi Mi?
        if message_data.get("tool_calls"):
            await update.message.reply_text("⚡ [OpenClaw] Ajan dis dunyadan veri cekiyor...")
            
            messages.append(message_data) # Modelin isteğini geçmişe ekle
            
            for tool in message_data["tool_calls"]:
                func_name = tool["function"]["name"]
                args = tool["function"]["arguments"]
                
                # ✅ TOOL CALL VALIDATION: Whitelist kontrolü
                if func_name not in ALLOWED_TOOL_NAMES:
                    logger.warning(f"🚫 Yetkisiz tool çağrısı: {func_name}")
                    tool_result = "Güvenlik: Bu araç kullanımı yasaktır."
                elif func_name == "skill_get_time":
                    tool_result = skill_get_time()
                elif func_name == "skill_web_radar":
                    tool_result = skill_web_radar(args.get("url", ""))
                else:
                    tool_result = "Bilinmeyen arac."
                
                messages.append({"role": "tool", "content": tool_result, "name": func_name})
            
            # AŞAMA 3: Aracı Kullandıktan Sonra Final Yorumunu Al
            final_response = ollama_client.chat(model=model, messages=messages)
            yanit = final_response["message"]["content"]
        else:
            yanit = message_data.get("content", "")

        logger.info(f"✅ Yanıt hazırlandı: {user_id} (Model: {model})")
        for i in range(0, len(yanit), 4000):
            await update.message.reply_text(f"[{model.upper()}]\n" + yanit[i:i+4000])

    except requests.ConnectTimeout:
        logger.error(f"⏱️ Ollama bağlantı timeout: {user_id}")
        await update.message.reply_text("❌ Model bağlantı zaman aşımı. Lütfen daha sonra deneyin.")
    except requests.RequestException as e:
        logger.error(f"🌐 Ollama iletişim hatası: {e}")
        await update.message.reply_text("❌ Model servisi ulaşılamıyor.")
    except ResponseError as e:
        if getattr(e, "status_code", None) == 404:
            await update.message.reply_text(
                f"❌ Model bulunamadı: {model}\n\n"
                f"Önce şu komutla indir:\n"
                f"docker compose exec ollama ollama pull {model}"
            )
        else:
            logger.error(f"❌ Ollama model hatası: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Model hatası: {getattr(e, 'error', str(e))}")
    except Exception as e:
        logger.error(f"❌ Mesaj işleme kritik hatası: {e}", exc_info=True)
        await update.message.reply_text("❌ İçsel hata oluştu. Sistem yöneticisine başvurunuz.")

if __name__ == "__main__":
    try:
        logger.info("="*60)
        logger.info("🚀 Vasi başlatılıyor...")
        logger.info(f"📂 Workspace: {WORKSPACE}")
        logger.info(f"🤖 Ollama Host: {OLLAMA_HOST}")
        logger.info(logger_setup_msg)
        logger.info("="*60)
        
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("yardim", cmd_yardim))
        app.add_handler(CommandHandler("liste", cmd_liste))
        app.add_handler(CommandHandler("oku", cmd_oku))
        app.add_handler(CommandHandler("yaz", cmd_yaz))
        app.add_handler(CommandHandler("ekle", cmd_ekle))
        app.add_handler(CommandHandler("sil", cmd_sil))
        app.add_handler(CommandHandler("fikir", cmd_fikir))
        app.add_handler(CommandHandler("ara", cmd_ara))
        app.add_handler(CommandHandler("ara_not", cmd_ara_not))
        app.add_handler(CommandHandler("ara_ozet", cmd_ara_ozet))
        app.add_handler(CommandHandler("ara_senaryo", cmd_ara_senaryo))
        app.add_handler(CommandHandler("tarzim", cmd_tarzim))
        app.add_handler(CommandHandler("senaryo", cmd_senaryo))
        app.add_handler(CommandHandler("kod", cmd_kod))
        app.add_handler(CommandHandler("kod_patch", cmd_kod_patch))
        app.add_handler(CommandHandler("guvenlik", cmd_guvenlik))
        app.add_handler(CommandHandler("rapor", cmd_rapor))
        app.add_handler(CallbackQueryHandler(callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("✅ Vasi aktif. OpenClaw yetenekleri devrede.")
        logger.info("📡 Polling başlatılıyor...")
        app.run_polling()
    except KeyboardInterrupt:
        logger.info("⏹️  Bot durduruldu (Keyboard Interrupt)")
    except Exception as e:
        logger.critical(f"💥 KRITIK HATA: {e}", exc_info=True)
        raise
