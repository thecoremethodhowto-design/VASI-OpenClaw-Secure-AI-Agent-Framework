"""kanit.py'nin kendisi: kanit listesi eskiyemez, kanitlayici kendini kandiramaz."""
import re
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import kanit  # noqa: E402

# 4 Ekim: kullanicinin pytest.ini'si `-q` ekliyor; kanit.py de `-q` veriyordu.
# -qq'da pytest "1 failed in 0.3s" satirini hic yazmaz ve son satira bakan
# eski kanitlayici yakalanan 36 bozmanin hepsini "calismadi" saydi. Uctan uca
# testler ayni kosulu PYTEST_ADDOPTS ile yeniden kurar: "" ve "-q" (= -qq).
AYRINTI = pytest.mark.parametrize("pytest_ek", ["", "-q"], ids=["varsayilan", "4_ekim_qq"])


def test_her_kanitin_bozacagi_satir_kodda_bir_kez_var():
    """Kod degisip desen kaybolursa kanit sessizce 'gecmez' -- burada yakalanir."""
    for no, (faz, ad, dosya, aranan, yerine, testler) in enumerate(kanit.KANITLAR, 1):
        metin = (KOK / dosya).read_text(encoding="utf-8")
        assert metin.count(aranan) == 1, f"kanit {no} ({ad}): desen {metin.count(aranan)} kez"
        assert aranan != yerine, f"kanit {no}: hicbir sey bozmuyor"


def test_her_kanit_var_olan_bir_teste_isaret_ediyor():
    for no, (_, ad, _, _, _, testler) in enumerate(kanit.KANITLAR, 1):
        assert testler, f"kanit {no}: test yok"
        for test in testler:
            dosya, ad_ = test.split("::")
            ad_ = ad_.split("[")[0]
            kaynak = (KOK / dosya).read_text(encoding="utf-8")
            assert re.search(rf"^def {ad_}\(", kaynak, re.M), f"kanit {no}: {test} yok"


@AYRINTI
def test_tek_kanit_uctan_uca_calisiyor(monkeypatch, capsys, pytest_ek):
    monkeypatch.setenv("PYTEST_ADDOPTS", pytest_ek)
    no = next(i for i, k in enumerate(kanit.KANITLAR, 1) if "temiz' yerine" in k[1])
    assert kanit.main(["--sadece", str(no)]) == 0
    assert "1 bozma · 1 tanesi yakalandı" in capsys.readouterr().out


@AYRINTI
def test_hicbir_seyi_bozmayan_degisiklik_kanit_sayilmiyor(monkeypatch, capsys, pytest_ek):
    """Kanitlayicinin kendisi: yesil kalan bir test 'yakalandi' sayilmamali."""
    monkeypatch.setenv("PYTEST_ADDOPTS", pytest_ek)
    zararsiz = ("t", "zararsız bir boşluk", "audit_chain.py",
                'BASLANGIC = "0" * 32', 'BASLANGIC = "0" * 32 ',
                ["tests/test_audit_chain.py::test_ozet_onceki_halkaya_bagli"])
    monkeypatch.setattr(kanit, "KANITLAR", [zararsiz])
    assert kanit.main(["--sadece", "1"]) == 1
    assert "YEŞİL KALDI" in capsys.readouterr().out


def test_kodu_cokerten_bozma_kanit_sayilmiyor_ve_nedeni_soyleniyor(monkeypatch, capsys):
    """Test kirmizi, ama koruma yakaladigi icin degil: kod hic yuklenemedi.

    Bu bir kanit degildir. Sayilmamali ve neden sayilmadigi ekranda
    yazmali -- 4 Ekim'de "ÇALIŞMADI" yazip nedenini soylemeyen satirlar
    sorunu bulmayi zorlastirdi.
    """
    cokerten = ("t", "içe aktarmayı çökerten bozma", "audit_chain.py",
                'BASLANGIC = "0" * 32', "BASLANGIC = 0 / 0",
                ["tests/test_audit_chain.py::test_ozet_onceki_halkaya_bagli"])
    monkeypatch.setattr(kanit, "KANITLAR", [cokerten])
    assert kanit.main(["--sadece", "1"]) == 1
    cikti = capsys.readouterr().out
    assert "0 tanesi yakalandı" in cikti
    assert "ÇALIŞMADI" in cikti and "ZeroDivisionError" in cikti


# ── sonucun okunmasi: makine okunur rapor, ekrandaki metin degil ───────────

GECER = '<testcase classname="t" name="a" />'
KALIR = '<testcase classname="t" name="a"><failure message="assert 1 == 2" /></testcase>'
KURULUMDA = ('<testcase classname="t" name="a"><error message="failed on setup with '
             '&quot;ImportError: x&quot;">E   ImportError: cannot import name X</error></testcase>')
TOPLANAMADI = ('<testcase classname="" name="tests.test_x"><error message="collection failure">'
               '    X = 1/0\nE   ZeroDivisionError: division by zero</error></testcase>')
YIKIMDA = ('<testcase classname="t" name="a"><error message="failed on teardown with '
           '&quot;RuntimeError: y&quot;" /></testcase>')
ATLAR = '<testcase classname="t" name="a"><skipped message="gercek veritabani yok" /></testcase>'


@pytest.mark.parametrize("kod, testcaseler, beklenen, nedende", [
    (1, [KALIR], "kirmizi", ""),
    (0, [GECER], "yesil", ""),
    (1, [KURULUMDA], "calismadi", "ImportError"),
    (2, [TOPLANAMADI], "calismadi", "ZeroDivisionError"),
    (1, [KALIR, YIKIMDA], "calismadi", "hata verdi"),
    (0, [ATLAR], "calismadi", "atlandı"),
    (4, [], "calismadi", "bulunamadı"),
    (0, [KALIR], "calismadi", "çelişiyor"),
    (1, [GECER], "calismadi", "çelişiyor"),
], ids=["kirmizi", "yesil", "kurulum_hatasi", "toplama_hatasi", "yikim_hatasi",
        "atlandi", "test_yok", "kod_0_ama_kirmizi", "kod_1_ama_yesil"])
def test_sonuc_makine_okunur_rapordan_okunuyor(tmp_path, kod, testcaseler, beklenen, nedende):
    rapor = tmp_path / "rapor.xml"
    rapor.write_text('<testsuites><testsuite name="pytest">' + "".join(testcaseler)
                     + "</testsuite></testsuites>", encoding="utf-8")
    sonuc, neden = kanit._sonucu_oku(kod, rapor)
    assert sonuc == beklenen
    assert nedende in neden
    assert bool(neden) == (sonuc == "calismadi")


def test_rapor_yoksa_kanit_yok_ve_pytestin_hatasi_gosteriliyor(tmp_path):
    cikti = "\nERROR: file or directory not found: tests/test_yok.py\n\n"
    sonuc, neden = kanit._sonucu_oku(4, tmp_path / "yok.xml", cikti)
    assert sonuc == "calismadi"
    assert "raporu yok" in neden and "file or directory not found" in neden


def test_kanit_hicbir_yerel_modulu_import_etmiyor():
    import ast
    yerel = {p.stem for p in KOK.glob("*.py")} - {"kanit"}
    agac = ast.parse((KOK / "kanit.py").read_text(encoding="utf-8"))
    importlar = set()
    for d in ast.walk(agac):
        if isinstance(d, ast.Import):
            importlar |= {a.name.split(".")[0] for a in d.names}
        elif isinstance(d, ast.ImportFrom) and d.module:
            importlar.add(d.module.split(".")[0])
    assert not importlar & yerel, importlar & yerel
