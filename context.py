"""Context katmani: modele verilecek baglami hazirlar.

DACE mimarisinin Context katmani. "Model neyi bilmeli?" sorusunu
yanitlayan tum fonksiyonlar burada toplanir.

Bu katmandaki fonksiyonlar saf fonksiyonlardir: girdi alir, metin
dondurur, kalici yan etkileri yoktur.
"""
import logging
from pathlib import Path

logger = logging.getLogger("vasi")

# ── SABITLER ─────────────────────────────────────────────────────────────────
MAX_CODE_CONTEXT_FILE_SIZE = 80 * 1024  # 80KB

# ── KOD BAGLAMI DOSYALARI ─────────────────────────────────────
CODE_CONTEXT_FILES = (
    "vasi.py",
    "access.py",
    "context.py",
    "observability.py",
    "Dockerfile",
    "docker-compose.yml",
    "requirements.in",
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

# ── BAGLAM OKUMA VE MASKELEME ─────────────────────────────────

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

# ── SISTEM PROMPTLARI ─────────────────────────────────────────

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