"""DACE katman sinirlarini dogrulayan testler.

Bu testler davranis degil, MIMARI dogrular. Bir katmanin baska bir
katmana bagimliligi kurallara uygun mu?

Izin verilen bagimlilik yonu:
    vasi.py  ->  decision, access, context, execution
    execution ->  access
    context   ->  (bagimsiz)
    access    ->  (bagimsiz)

Ters yonde bagimlilik olmamalidir.
"""
import ast
import inspect
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def modul_importlari(dosya_adi: str) -> set[str]:
    """Bir Python dosyasinin import ettigi yerel modul adlarini dondurur."""
    kaynak = (REPO / dosya_adi).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    isimler = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            for ad in dugum.names:
                isimler.add(ad.name.split(".")[0])
        elif isinstance(dugum, ast.ImportFrom):
            if dugum.module and dugum.level == 0:
                isimler.add(dugum.module.split(".")[0])
    return isimler


YEREL_MODULLER = {"vasi", "access", "context", "execution", "decision", "observability"}


# ── Bagimsizlik ──────────────────────────────────────────────────────────────

def test_access_hicbir_yerel_module_bagimli_degil():
    """Access en alt katman: hicbir yerel modulu import etmemeli."""
    bagimliliklar = modul_importlari("access.py") & YEREL_MODULLER
    assert bagimliliklar == set(), f"access.py sunlara bagimli: {bagimliliklar}"


def test_context_hicbir_yerel_module_bagimli_degil():
    """Context saf fonksiyonlardan olusur: yerel bagimliligi olmamali."""
    bagimliliklar = modul_importlari("context.py") & YEREL_MODULLER
    assert bagimliliklar == set(), f"context.py sunlara bagimli: {bagimliliklar}"


# ── Yon kontrolu ─────────────────────────────────────────────────────────────

def test_execution_sadece_access_e_bagimli():
    """Execution yalnizca Access'i kullanabilir, vasi'yi kullanamaz."""
    bagimliliklar = modul_importlari("execution.py") & YEREL_MODULLER
    assert bagimliliklar <= {"access"}, (
        f"execution.py izin verilmeyen bagimlilik iceriyor: {bagimliliklar - {'access'}}"
    )


def test_hicbir_katman_vasi_yi_import_etmiyor():
    """Ters bagimlilik yasak: katmanlar vasi.py'yi import edemez."""
    for modul in ["access.py", "context.py", "execution.py", "decision.py"]:
        assert "vasi" not in modul_importlari(modul), (
            f"{modul} vasi.py'yi import ediyor - dairesel bagimlilik riski"
        )


# ── Guvenlik garantisi ───────────────────────────────────────────────────────

def test_execution_dosya_islemleri_access_uzerinden_gecer():
    """Her dosya islemi scoped_path() ile dogrulanmali.

    Bu, 'dosya erisimi her zaman yetkilendirmeden gecer' iddiasini
    yurutulebilir hale getirir.
    """
    import execution

    for fn_adi in ["read_file", "save_file", "append_file", "delete_file"]:
        kaynak = inspect.getsource(getattr(execution, fn_adi))
        assert "scoped_path(" in kaynak, (
            f"{fn_adi}() scoped_path() kullanmiyor - workspace sinirlari atlanabilir"
        )


def test_yazma_islemleri_uzanti_kontrolunden_gecer():
    """save_file ve append_file yazilabilir uzanti kontrolu yapmali."""
    import execution

    for fn_adi in ["save_file", "append_file"]:
        kaynak = inspect.getsource(getattr(execution, fn_adi))
        assert "is_allowed_write_file(" in kaynak, (
            f"{fn_adi}() uzanti kontrolu yapmiyor"
        )


def test_web_araci_url_dogrulamasindan_gecer():
    """skill_web_radar SSRF korumasini atlayamaz."""
    import execution

    kaynak = inspect.getsource(execution.skill_web_radar)
    assert "is_safe_url(" in kaynak, "skill_web_radar() SSRF kontrolu yapmiyor"


# ── Katman butunlugu ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("modul,beklenen", [
    ("access.py", ["is_authorized", "safe_path", "classify_file", "is_safe_url"]),
    ("context.py", ["build_system_prompt", "build_code_context"]),
    ("execution.py", ["save_file", "delete_file", "skill_web_radar"]),
    ("decision.py", ["pick_model", "detect_skill", "skill_scope"]),
])
def test_katmanlar_beklenen_fonksiyonlari_iceriyor(modul, beklenen):
    """Refactor sirasinda fonksiyon kaybolmadi."""
    kaynak = (REPO / modul).read_text(encoding="utf-8")
    for fn in beklenen:
        assert f"def {fn}(" in kaynak, f"{modul} icinde {fn}() yok"


# ── Decision katmani ─────────────────────────────────────────────────────────

def test_decision_hicbir_yerel_module_bagimli_degil():
    """Decision saf karar mantigi: yerel bagimliligi olmamali."""
    bagimliliklar = modul_importlari("decision.py") & YEREL_MODULLER
    assert bagimliliklar == set(), f"decision.py sunlara bagimli: {bagimliliklar}"


def test_bilinmeyen_skill_en_kisitlayici_kapsama_duser():
    """Guvenli varsayilan: tanimlanmamis bir skill erisim genisletmemeli."""
    import decision
    assert decision.skill_scope("skills/tanimsiz.md") == "general"
    assert decision.skill_scope("") == "general"


def test_bilinen_skiller_dogru_kapsamda():
    import decision
    assert decision.skill_scope("skills/youtube_icerik.md") == "youtube"
    assert decision.skill_scope("skills/kod_yardimcisi.md") == "code"
    assert decision.skill_scope("skills/arastirma.md") == "youtube"


def test_message_handler_skill_baglamini_kullaniyor(vasi_module):
    """detect_skill artik gercekten bagli; olu kod degil."""
    import inspect
    kaynak = inspect.getsource(vasi_module.message_handler)
    assert "detect_skill(" in kaynak, "message_handler detect_skill kullanmiyor"
    assert "skill_scope(" in kaynak, "skill okumasi kapsam belirtmiyor"


# ── Test izolasyonu ──────────────────────────────────────────────────────────

def test_tum_katmanlar_ayni_workspace_i_goruyor(vasi_module, tmp_path):
    """Katmanlar onbellekten gelen ESKI bir workspace tasimamali.

    Bu test, conftest'in modul temizligi eksik kalirsa kirilir:
    onbellekte kalan bir katman onceki testin tmp_path'ini tasir.
    """
    beklenen = (tmp_path / "workspace").resolve()
    assert vasi_module.access.WORKSPACE == beklenen
    assert vasi_module.execution.WORKSPACE == beklenen
    assert vasi_module.WORKSPACE == beklenen


def test_kok_dizindeki_her_modul_temizleniyor():
    """conftest elle tutulan bir liste degil, dinamik tarama kullanmali.

    Elle tutulan liste, yeni bir katman eklendiginde geride kalir.
    Bu tam olarak bir kez yasandi: decision.py eklendiginde liste
    guncellenmedi ve hicbir test bunu yakalamadi.
    """
    kaynak = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "glob(" in kaynak, (
        "conftest kok dizini taramiyor; yeni bir katman eklendiginde "
        "temizlik disinda kalir"
    )

# ── Model gizlilik profili ───────────────────────────────────────────────────

def test_litellm_takma_adlari_onek_kuralina_uyuyor():
    """config.yaml'daki her takma ad yerel- veya dis- ile baslamali.

    Bu kural olmadan, bir modelin verinin makineden cikip cikmadigi
    koddan anlasilamaz. Yeni bir model eklerken onek unutulursa
    bu test kirilir.
    """
    import yaml
    import decision

    config_yolu = REPO / "litellm" / "config.yaml"
    if not config_yolu.exists():
        pytest.skip("litellm/config.yaml yok")

    config = yaml.safe_load(config_yolu.read_text(encoding="utf-8"))
    takma_adlar = [m["model_name"] for m in config.get("model_list", [])]

    assert takma_adlar, "config.yaml'da hic model tanimli degil"

    kuralsiz = [
        ad for ad in takma_adlar
        if decision.privacy_profile(ad) == "bilinmiyor"
    ]
    assert not kuralsiz, (
        f"Su takma adlar onek kuralina uymuyor: {kuralsiz}. "
        f"Her ad '{decision.YEREL_ONEK}' veya '{decision.DIS_ONEK}' "
        f"ile baslamali."
    )


def test_yerel_modeller_ollama_kullaniyor():
    """yerel- onekli bir model gercekten yerelde calismali.

    Onek bir iddiadir; bu test onu dogrular. yerel- diye
    isimlendirilmis ama buluta giden bir model, isimlendirme
    kuralini anlamsizlastirirdi.
    """
    import yaml

    config_yolu = REPO / "litellm" / "config.yaml"
    if not config_yolu.exists():
        pytest.skip("litellm/config.yaml yok")

    config = yaml.safe_load(config_yolu.read_text(encoding="utf-8"))
    for girdi in config.get("model_list", []):
        ad = girdi["model_name"]
        if not ad.startswith("yerel-"):
            continue
        model = girdi["litellm_params"]["model"]
        assert model.startswith("ollama/"), (
            f"'{ad}' yerel olarak isaretlenmis ama '{model}' kullaniyor"
        )


def test_bilinmeyen_takma_ad_yerel_sayilmiyor():
    """Guvenli varsayilan: kurala uymayan ad asla yerel degildir."""
    import decision
    for ad in ["claude-analiz", "gpt4", "", "yerelsiz"]:
        assert not decision.is_local(ad), f"'{ad}' yerel sayilmamali"
        assert decision.leaves_machine(ad), f"'{ad}' icin veri cikiyor sayilmali"