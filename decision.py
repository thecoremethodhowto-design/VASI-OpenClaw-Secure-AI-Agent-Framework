"""Decision katmani: ne yapilmasi gerektigine karar verir.

DACE mimarisinin Decision katmani. Gelen istegi siniflandirip
hangi modelin ve hangi skill baglaminin kullanilacagini belirler.

Bu katman KARAR VERIR, ERISIM SAGLAMAZ. Skill dosyalarinin
okunmasi Execution katmaninda, izin kontrolu Access katmaninda
yapilir. Buradaki skill_scope() yalnizca hangi kapsamin talep
edilecegini soyler; kapsamin gecerliligini Access dogrular.
"""
import os

# ── MODEL SECIMI ─────────────────────────────────────────────────────────────
MODELS = {
    "gatekeeper": os.getenv("VASI_MODEL_GATEKEEPER", "llama3.1:8b"),
    "strateji":   os.getenv("VASI_MODEL_STRATEJI", "llama3.1:8b"),
    "teknik":     os.getenv("VASI_MODEL_TEKNIK", "llama3.1:8b"),
    "kod":        os.getenv("VASI_MODEL_KOD", "qwen3-coder:30b"),
    "gorsel":     os.getenv("VASI_MODEL_GORSEL", "llama3.1:8b"),
}


def pick_model(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["kod", "script", "python"]): return MODELS["kod"]
    if any(k in t for k in ["analiz", "gorsel", "tablo"]): return MODELS["gorsel"]
    if any(k in t for k in ["arastir", "neden", "web", "site", "okut"]): return MODELS["teknik"]
    if any(k in t for k in ["e-posta", "rapor", "taslak"]): return MODELS["strateji"]
    
    return MODELS["gatekeeper"]


# ── SKILL TESPITI ─────────────────────────────────────────────

def detect_skill(text: str) -> tuple[str, str]:
    """Deterministik skill tespiti; evaluation ve DACE iskeleti için hafif sınıflandırıcı."""
    t = text.lower()
    youtube_terms = [
        "youtube", "video", "senaryo", "script", "hook", "thumbnail",
        "başlık", "baslik", "açıklama", "aciklama", "etiket", "kanal",
    ]
    code_terms = [
        "kod", "script", "python", "javascript", "hata", "debug",
        "refactor", "fonksiyon", "class", "api", "pytest", "unit test",
        "birim test", "optimize",
        "review", "oyun", "pygame", "uygulama", "proje",
    ]
    research_terms = [
        "araştır", "arastir", "ara", "bul", "güncel", "guncel",
        "haber", "trend", "ne var", "durum nedir", "son gelişmeler",
        "son gelismeler",
    ]
    if any(term in t for term in youtube_terms):
        return "youtube_icerik", "skills/youtube_icerik.md"
    if any(term in t for term in code_terms):
        return "kod_yardimcisi", "skills/kod_yardimcisi.md"
    if any(term in t for term in research_terms):
        return "arastirma", "skills/arastirma.md"
    return "", ""


# ── SKILL KAPSAM ESLESMESI ────────────────────────────────────

SKILL_SCOPES = {
    "skills/youtube_icerik.md": "youtube",
    "skills/kod_yardimcisi.md": "code",
    "skills/arastirma.md":      "youtube",
}


def skill_scope(skill_path: str) -> str:
    """Bir skill dosyasinin hangi kapsam altinda okunmasi gerektigini soyler.

    Bilinmeyen bir yol icin en kisitlayici kapsami (general) dondurur.
    Boylece yeni bir skill eklenip burada tanimlanmazsa, erisim
    genislemez; daralir.
    """
    return SKILL_SCOPES.get(skill_path, "general")