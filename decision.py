"""Decision katmani: ne yapilmasi gerektigine karar verir.

DACE mimarisinin Decision katmani. Gelen istegi siniflandirip
hangi modelin ve hangi skill baglaminin kullanilacagini belirler.

Bu katman KARAR VERIR, ERISIM SAGLAMAZ. Skill dosyalarinin
okunmasi Execution katmaninda, izin kontrolu Access katmaninda
yapilir. Buradaki skill_scope() yalnizca hangi kapsamin talep
edilecegini soyler; kapsamin gecerliligini Access dogrular.

Ayni ilke model secimi icin de gecerlidir: privacy_profile() bir
model takma adinin verinin makineden cikip cikmadigini soyler.
Bu bilgiyle NE YAPILACAGINA Access katmani karar verir.
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

# ── MODEL GIZLILIK PROFILI ────────────────────────────────────

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