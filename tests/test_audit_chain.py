"""Denetim izi zinciri: her satir bir oncekinin ozetini tasir.

Bu dosyanin iki tur testi var. Cogu, zincirin NEYI yakaladigini
gosteriyor: degistirilen, silinen, araya eklenen, yarim kalan satir;
bot calisirken dosyaya yapilan her mudahale. Biri -- test_SINIR_... --
zincirin NEYI YAKALAYAMADIGINI gosteriyor ve GECMESI gerekiyor. O test
gectigi surece ikinci bir tanik gereklidir.
"""
import ast
import logging
import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import audit_chain as ac  # noqa: E402


def _yaz(yol, olaylar, **kw):
    """Zincirli yaziciyla satir yazar -- botun yaptigi gibi."""
    lg = logging.getLogger(f"zincir-test-{uuid.uuid4().hex}")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    h = ac.ZincirliDosyaYazicisi(str(yol), encoding="utf-8", **kw)
    h.setFormatter(logging.Formatter("%(message)s"))
    lg.addHandler(h)
    try:
        for olay in olaylar:
            lg.info(f"AUDIT | {olay} | user=***456 | ayrinti")
    finally:
        lg.removeHandler(h)
        h.close()


def _satirlar(yol):
    return Path(yol).read_text(encoding="utf-8").splitlines()


def _yaz_satirlar(yol, satirlar):
    Path(yol).write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def _dogrula(yol):
    return ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))


class _CanliYazici:
    """Kapanmadan yazmaya devam eden yazici: bot calisirken oldugu gibi.

    _yaz() her cagrida yeni yazici acar -- yeniden baslatma. Bu sinif
    ayni yaziciyi acik tutar; arada dosyaya disaridan dokunulabilir.
    """

    def __init__(self, yol, **kw):
        self.lg = logging.getLogger(f"zincir-canli-{uuid.uuid4().hex}")
        self.lg.propagate = False
        self.lg.setLevel(logging.INFO)
        self.h = ac.ZincirliDosyaYazicisi(str(yol), encoding="utf-8", **kw)
        self.h.setFormatter(logging.Formatter("%(message)s"))
        self.lg.addHandler(self.h)

    def yaz(self, *olaylar):
        for olay in olaylar:
            self.lg.info(f"AUDIT | {olay} | user=***456 | ayrinti")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for h in list(self.lg.handlers):
            self.lg.removeHandler(h)
        self.h.close()


def _editor_gibi_kaydet(yol, satirlar, satir_sonu="\n"):
    """TextEdit, vim, sed -i gibi: YENI dosya yaz, eskisinin yerine koy."""
    gecici = Path(f"{yol}.kaydediliyor")
    gecici.write_text("\n".join(satirlar) + satir_sonu, encoding="utf-8")
    os.replace(gecici, yol)


def _bastan_hesapla(satirlar):
    """Saldirgan gibi: sira ve ozetleri bastan hesaplar."""
    yeni, onceki = [], ac.BASLANGIC
    for sira, satir in enumerate(satirlar, 1):
        govde, _, _ = ac.halka_coz(satir)
        govde = re.sub(r"\| sira=\d+$", f"| sira={sira}", govde)
        oz = ac.ozet(onceki, govde)
        yeni.append(f"{govde} | ozet={oz}")
        onceki = oz
    return yeni


# ── 1. Yazici ────────────────────────────────────────────────────────────────

def test_ozet_onceki_halkaya_bagli():
    assert ac.ozet("a", "govde") == ac.ozet("a", "govde")
    assert ac.ozet("a", "govde") != ac.ozet("b", "govde")
    assert ac.ozet("a", "govde") != ac.ozet("a", "govde ")
    assert len(ac.ozet(ac.BASLANGIC, "x")) == 32


def test_yazici_sira_ve_ozet_ekliyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, ["bir", "iki", "uc"])

    halkalar = [ac.halka_coz(s) for s in _satirlar(yol)]
    assert [h[1] for h in halkalar] == [1, 2, 3]
    assert halkalar[0][2] == ac.ozet(ac.BASLANGIC, halkalar[0][0])
    assert halkalar[1][2] == ac.ozet(halkalar[0][2], halkalar[1][0])


def test_yeniden_baslatmada_zincir_kaldigi_yerden_devam_ediyor(tmp_path):
    """Faz 3a'dan beri iz yeniden baslatmadan sag cikiyor; zincir de cikmali."""
    yol = tmp_path / "iz.log"
    _yaz(yol, ["once_1", "once_2"])
    _yaz(yol, ["sonra_1"])              # yeni yazici = yeniden baslatma

    r = _dogrula(yol)
    assert r.saglam, r.sorunlar
    assert r.son_sira == 3 and r.halka == 3


# ── 2. Neyi yakaliyor ────────────────────────────────────────────────────────

def test_temiz_zincir_saglam(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i}" for i in range(10)])
    r = _dogrula(yol)
    assert r.saglam and r.halka == 10 and r.son_sira == 10


def test_degistirilen_satir_yakalaniyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i}" for i in range(5)])
    s = _satirlar(yol)
    s[2] = s[2].replace("olay_2", "olay_X")         # ozete dokunmadan degistir
    _yaz_satirlar(yol, s)

    r = _dogrula(yol)
    assert not r.saglam
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("degistirilmis", 3)]


def test_silinen_satir_yakalaniyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i}" for i in range(5)])
    s = _satirlar(yol)
    del s[2]                                        # sira 3 gidiyor
    _yaz_satirlar(yol, s)

    r = _dogrula(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 4)]
    assert "sıra 3 kayıp" in r.sorunlar[0].aciklama


def test_araya_kopyalanan_satir_yakalaniyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i}" for i in range(4)])
    s = _satirlar(yol)
    s.insert(2, s[1])                               # sira 2 iki kez
    _yaz_satirlar(yol, s)

    r = _dogrula(yol)
    assert [x.tur for x in r.sorunlar] == ["eklenmis"]


def test_zincirsiz_denetim_satiri_yakalaniyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, ["bir", "iki"])
    s = _satirlar(yol)
    s.insert(1, "AUDIT | uydurma | user=***999 | hic olmadi")
    _yaz_satirlar(yol, s)

    r = _dogrula(yol)
    assert [x.tur for x in r.sorunlar] == ["zincirsiz"]


def test_yarim_kalan_satir_yakalaniyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, ["bir", "iki"])
    s = _satirlar(yol)
    s[1] = s[1][:-10]                               # yazma kesilmis gibi
    _yaz_satirlar(yol, s)

    r = _dogrula(yol)
    assert [x.tur for x in r.sorunlar] == ["yarim"]


def test_yarim_satirdan_sonra_zincir_devam_edebiliyor(tmp_path):
    """Cokme sonrasi yarim kalan satir sonraki yazimi bozmamali."""
    yol = tmp_path / "iz.log"
    _yaz(yol, ["bir", "iki"])
    s = _satirlar(yol)
    s[1] = s[1][:-10]
    _yaz_satirlar(yol, s)
    _yaz(yol, ["uc"])                               # yeniden baslatma

    r = _dogrula(yol)
    # yarim satir hala bir sorun; ama yeni halka son SAGLAM halkaya bagli
    assert [x.tur for x in r.sorunlar] == ["yarim"]
    assert r.son_sira == 2


def test_zincirden_once_yazilan_satirlar_hata_degil(tmp_path):
    """Faz 3a'da kalici izin ilk uc satiri zincirden once yazildi."""
    yol = tmp_path / "iz.log"
    yol.write_text(
        "AUDIT | unknown_command | user=***422 | /danetle\n"
        "AUDIT | sovereign_audit | user=***422 | bulgu=0\n",
        encoding="utf-8",
    )
    _yaz(yol, ["ilk_halka", "ikinci_halka"])

    r = _dogrula(yol)
    assert r.saglam, r.sorunlar
    assert r.zincir_oncesi == 2 and r.halka == 2
    assert "zincirden önce yazılmış" in ac.rapor_metni(r)


# ── 3. Bot calisirken dosyaya dokunulursa ────────────────────────────────────

def test_dosya_calisirken_degistirilirse_iz_susmuyor(tmp_path):
    """Editorle kaydetmek dosyanin YERINE yenisini koyar.

    Bu kontrol yokken yazici eski dosyayi acik tutuyordu: sonraki
    satirlar artik hicbir yerde gorunmeyen eski dosyaya gidiyordu. Iz,
    yeniden baslatmaya kadar SESSIZCE kaydetmeyi birakiyordu.
    """
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz("bir", "iki", "uc")
        s = _satirlar(yol)
        s[1] = s[1].replace("iki", "IKI")
        _editor_gibi_kaydet(yol, s)
        y.yaz("dort")

    son = _satirlar(yol)
    assert "dort" in son[-1], "degisiklikten sonraki satir diske ulasmadi"
    assert ac.MUDAHALE_OLAYI in son[-2]
    r = _dogrula(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("degistirilmis", 2)]
    assert [(x.sira, x.aciklama) for x in r.mudahaleler] == [
        (4, "dosya dışarıdan değiştirilmiş (yerine yenisi konmuş)")]
    assert r.son_sira == 5


def test_icerik_ayni_kalsa_da_dokunulmasi_kaydediliyor(tmp_path):
    """Degistirmeden kaydetmek zinciri bozmaz -- ama bir denetim olayidir."""
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz("bir", "iki")
        _editor_gibi_kaydet(yol, _satirlar(yol))
        y.yaz("uc")

    r = _dogrula(yol)
    assert r.saglam, r.sorunlar              # icerik ayni: zincir tutarli
    assert not r.temiz                       # ama dosyaya dokunulmus
    assert [x.sira for x in r.mudahaleler] == [3]
    assert "zincir sağlam (4 halka) · dış müdahale kaydı: sıra 3" == ac.ozet_satiri(r)
    assert "dışarıdan dokunulmuş" in ac.rapor_metni(r)
    assert "✅" not in ac.rapor_metni(r)
    assert ac.main([str(yol)]) == 1, "zincir saglam ama dokunulmus: komut satiri yesil yanmamali"


@pytest.mark.parametrize("yontem", ["yerine_yenisi", "ayni_dosyada"])
def test_sondan_silmek_calisirken_ele_veriliyor(tmp_path, yontem):
    """Hash zincirinin bilinen zaafi: sondan silmek zinciri bozmaz.

    Zincirin ucunu diskten okuyan bir yazici, silinenin ustunden
    sorunsuzca devam ederdi. Bu yazici ucu kendi hafizasinda tutuyor:
    bir sonraki satir, silinen halkaya bagli.
    """
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz(*[f"olay_{i}" for i in range(5)])
        kalan = _satirlar(yol)[:3]                  # sira 4 ve 5 gidiyor
        if yontem == "yerine_yenisi":
            _editor_gibi_kaydet(yol, kalan)
        else:
            _yaz_satirlar(yol, kalan)               # ayni inode, yerinde kirpma
        y.yaz("sonraki")

    r = _dogrula(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 6)]
    assert "sıra 4–5 kayıp" in r.sorunlar[0].aciklama


@pytest.mark.parametrize("saldiri, beklenen", [
    ("degistir", ("degistirilmis", 6)),
    ("sil",      ("eksik", 6)),
])
def test_calisirken_bastan_hesaplanan_zincir_ele_veriliyor(tmp_path, saldiri, beklenen):
    """SINIR testindeki saldiri, bot CALISIRKEN yapilirsa yakalaniyor.

    Saldirgan dosyayi kendi icinde kusursuz hale getirebilir; yazicinin
    hafizasindaki ucu degistiremez. Bir sonraki satir ona baglanir.
    """
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz(*[f"olay_{i}" for i in range(5)])
        s = _satirlar(yol)
        if saldiri == "degistir":
            s[2] = s[2].replace("olay_2", "olay_X")
        else:
            del s[2]
        _yaz_satirlar(yol, _bastan_hesapla(s))
        assert _dogrula(yol).temiz                  # su an dosya kusursuz gorunuyor
        y.yaz("sonraki")

    r = _dogrula(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [beklenen]


def test_dosya_calisirken_silinirse_yeni_dosya_olayla_basliyor(tmp_path, capsys):
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz("bir", "iki", "uc")
        yol.unlink()
        y.yaz("dort")

    s = _satirlar(yol)
    assert len(s) == 2
    assert ac.MUDAHALE_OLAYI in s[0] and "dort" in s[1]
    r = _dogrula(yol)
    assert r.baslangic_eksik == (1, 3)
    assert [(x.sira, x.aciklama) for x in r.mudahaleler] == [
        (4, "dosya silinmiş ya da taşınmış")]
    assert ac.main([str(yol)]) == 1                 # komut satiri da yesil yanmiyor
    cikti = capsys.readouterr().out
    assert "dış müdahale" in cikti
    assert "rotasyonla" not in cikti, "silme, rotasyon gibi anlatilmis"
    assert "yazıcı tam bu noktada dış müdahale kaydetmiş" in cikti


def test_satir_sonu_olmadan_birakilan_dosyada_satirlar_karismiyor(tmp_path):
    """Bazi editorler son satir sonunu siler; yeni satir yine kendi satirinda."""
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz("bir", "iki")
        _editor_gibi_kaydet(yol, _satirlar(yol), satir_sonu="")
        y.yaz("uc")

    s = _satirlar(yol)
    assert len(s) == 4 and all(ac.halka_coz(x) for x in s), s
    assert _dogrula(yol).saglam


def test_mudahale_genel_loga_uyari_olarak_dusuyor_zincire_degil(tmp_path):
    """Uyari ayni logger'dan cikar ve bu yaziciya da ugrar.

    Bot bir filtre kullaniyor; yazici ona guvenmiyor. Bu testteki
    logger'da filtre yok -- uyari zincire yine de dusmemeli.
    """
    yol = tmp_path / "iz.log"
    toplanan = []

    class _Topla(logging.Handler):
        def emit(self, record):
            toplanan.append(record)

    with _CanliYazici(yol) as y:
        y.lg.addHandler(_Topla())
        y.yaz("bir")
        yol.unlink()
        y.yaz("iki")

    uyarilar = [r.getMessage() for r in toplanan if r.levelno == logging.WARNING]
    assert len(uyarilar) == 1 and "dosya silinmiş" in uyarilar[0]
    assert "sıra 2" in uyarilar[0]                  # ize nerede yazildigini soyluyor
    assert not any("⚠️" in s for s in _satirlar(yol)), "uyari zincire dusmus"


def test_mudahale_satiri_tetikleyen_yazimin_zamanini_tasiyor(tmp_path):
    """Kendi saati olsaydi, kendisinden SONRA gelen satirdan ileride dururdu."""
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.h.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        y.yaz("bir")
        yol.unlink()
        kayit = logging.LogRecord(y.lg.name, logging.INFO, "", 0,
                                  "AUDIT | iki | user=***456 | x", None, None)
        kayit.created, kayit.msecs = 1_000_000_000.0, 0.0      # 2001'den bir an
        y.h.handle(kayit)

    bildirim, iki = _satirlar(yol)
    assert ac.MUDAHALE_OLAYI in bildirim
    assert bildirim.split(" - ")[0] == iki.split(" - ")[0], (bildirim, iki)


def test_yeniden_acilamazsa_sonraki_yazimda_yine_deniyor(tmp_path, monkeypatch):
    """Disk dolu, izin yok... Yazici o an yazamaz -- ama kalici olarak susmaz.

    Eski akis kapatilip yenisi acilamasaydi, yazici kapali bir akisla
    kalir ve sonraki her yazim ayni hatayla duserdi.
    """
    yol = tmp_path / "iz.log"
    with _CanliYazici(yol) as y:
        y.yaz("bir")
        yol.unlink()
        asil_ac, denemeler = y.h._open, []

        def ilki_basarisiz():
            denemeler.append(1)
            if len(denemeler) == 1:
                raise OSError("disk dolu")
            return asil_ac()

        monkeypatch.setattr(y.h, "_open", ilki_basarisiz)
        monkeypatch.setattr(logging, "raiseExceptions", False)   # stderr'i kirletme
        y.yaz("iki")                                # yazilamaz, yuksek sesle
        y.yaz("uc")                                 # yeniden denenir

    s = _satirlar(yol)
    assert ac.MUDAHALE_OLAYI in s[0] and "uc" in s[1], s


# ── 4. Neyi YAKALAYAMIYOR ────────────────────────────────────────────────────

def test_SINIR_bot_dururken_bastan_hesaplanan_zincir_dosyayi_kandirir(tmp_path):
    """Bu test GECMELI. Gectigi surece ikinci tanik gereklidir.

    Bot calisirken yapilan her degisiklik bir sonraki satirda ele
    veriliyor (yukaridaki testler). Ama bot DURURKEN: bir satiri sil,
    sonrakilerin sirasini ve ozetini yeniden hesapla -- dosya kendi
    icinde kusursuz gorunur. Yeniden baslayan yazicinin hafizasi yok;
    diskte ne bulursa ona inanir ve zinciri oradan surdurur. Gizli bir
    anahtar bunu cozmez: anahtar ayni makinede durur.

    Ikinci tanik (veritabanindaki kopya zincir) bu saldiriyi yakaliyor:
    test_ikinci_tanik.py, test_bot_dururken_bastan_hesaplanan_zincir_
    yakalaniyor ve test_3_ekim_... Bu test yine de duruyor, cunku
    dosyanin TEK BASINA neyi yapamadigini anlatmaya devam ediyor -- ve
    tanik kapaliyken durum hala bu.
    """
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i}" for i in range(5)])          # bot calisti, durdu
    s = _satirlar(yol)
    del s[2]
    _yaz_satirlar(yol, _bastan_hesapla(s))
    _yaz(yol, ["yeniden_baslatmadan_sonra"])             # bot yeniden basladi

    r = _dogrula(yol)
    assert r.temiz, "Bu saldiri artik dosyada yakalaniyorsa bu testi guncelle"
    assert r.halka == 5                                  # 6 olay oldu, iz 5 diyor


# ── 5. Rotasyon ve es zamanlilik ─────────────────────────────────────────────

def test_rotasyonda_zincir_dosyalar_arasinda_suruyor(tmp_path):
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i:02d}" for i in range(30)], maxBytes=400, backupCount=20)

    dosyalar = ac.dosyalari_sirala(yol)
    assert len(dosyalar) > 2, "rotasyon tetiklenmedi"
    r = ac.dogrula_dosyalar(dosyalar)
    assert r.temiz, (r.sorunlar, r.mudahaleler)     # kendi rotasyonu mudahale degil
    # Her yeni dosya bir donme kaydiyla baslar: 30 olay + donme sayisi kadar halka.
    donmeler = sum(f"| {ac.ROTASYON_OLAYI} |" in s for d in dosyalar
                   for s in Path(d).read_text(encoding="utf-8").splitlines())
    assert donmeler == len(dosyalar) - 1
    assert r.son_sira == r.halka == 30 + donmeler


def test_rotasyonla_silinen_baslangic_hata_degil_ama_soyleniyor(tmp_path):
    """Yedek sayisi asilinca en eski dosya silinir: sessizce degil."""
    yol = tmp_path / "iz.log"
    _yaz(yol, [f"olay_{i:02d}" for i in range(30)], maxBytes=400, backupCount=2)

    r = _dogrula(yol)
    assert r.saglam, r.sorunlar
    assert r.baslangic_eksik is not None and r.baslangic_eksik[0] == 1
    assert "başlangıç eksik" in ac.rapor_metni(r)


def test_es_zamanli_yazimda_zincir_catallanmiyor(tmp_path):
    yol = tmp_path / "iz.log"
    lg = logging.getLogger(f"zincir-esz-{uuid.uuid4().hex}")
    lg.propagate, lg.level = False, logging.INFO
    h = ac.ZincirliDosyaYazicisi(str(yol), encoding="utf-8")
    h.setFormatter(logging.Formatter("%(message)s"))
    lg.addHandler(h)

    def yaz(n):
        for i in range(50):
            lg.info(f"AUDIT | is_{n}_{i} | user=***456 | x")

    iplikler = [threading.Thread(target=yaz, args=(n,)) for n in range(4)]
    for t in iplikler:
        t.start()
    for t in iplikler:
        t.join()
    lg.removeHandler(h)
    h.close()

    r = _dogrula(yol)
    assert r.temiz, (r.sorunlar[:3], r.mudahaleler[:3])
    assert r.son_sira == 200 and r.halka == 200


# ── 6. Bagimsizlik: dogrulayici sistemden ayri calisabilmeli ─────────────────

def test_komut_satirindan_dogrulama(tmp_path):
    """Konteyner olmadan: python3 audit_chain.py denetim/denetim.log"""
    yol = tmp_path / "iz.log"
    _yaz(yol, ["bir", "iki", "uc"])
    temiz = subprocess.run([sys.executable, str(KOK / "audit_chain.py"), str(yol)],
                           capture_output=True, text=True)
    assert temiz.returncode == 0, temiz.stdout
    assert "Zincir sağlam" in temiz.stdout

    s = _satirlar(yol)
    s[1] = s[1].replace("iki", "IKI")
    _yaz_satirlar(yol, s)
    kirik = subprocess.run([sys.executable, str(KOK / "audit_chain.py"), str(yol)],
                           capture_output=True, text=True)
    assert kirik.returncode == 1
    assert "Zincir kırık" in kirik.stdout and "sıra 2" in kirik.stdout


def test_hicbir_sey_dogrulamayan_dogrulayici_tamam_demiyor(tmp_path, capsys):
    """Gercek kurulumda yasandi (3 Ekim 2026).

    Testler yeni imajda yesildi ama calisan bot eski surumdu: dosyada
    tek bir zincirli satir yoktu. Dogrulayici 'Zincirde henuz halka yok'
    deyip 0 dondu; satirlardan biri TextEdit'le degistirildikten sonra
    da AYNI seyi soyledi. Hicbir sey dogrulamadan 0 donmek, 'sorun yok'
    demenin sessiz hali.
    """
    yol = tmp_path / "denetim.log"
    satir = "2026-10-03 21:10:22,479 - vasi - INFO - AUDIT | sovereign_audit | user=***422 | bulgu=0"
    yol.write_text("\n".join([satir] * 8) + "\n", encoding="utf-8")

    assert ac.main([str(yol)]) == 3
    cikti = capsys.readouterr().out
    assert "✅" not in cikti
    assert "Zincirli satır yok: 8 denetim satırının hiçbiri doğrulanamaz" in cikti
    assert "zincirli yazıcıyla mı çalışıyor" in cikti

    _yaz_satirlar(yol, [satir.replace("bulgu=0", "bulgu=3")] + [satir] * 7)
    assert ac.main([str(yol)]) == 3             # degisiklik GORULEMEZ -- ve bunu soyluyor
    capsys.readouterr()

    yol.write_text("", encoding="utf-8")
    assert ac.main([str(yol)]) == 3             # bos dosya da 'tamam' degil
    assert "doğrulanacak bir şey yok" in capsys.readouterr().out


def test_macos_python39_ile_uyumlu():
    """Sistem Python'i 3.9: dogrulayici Mac'te dogrudan calisabilmeli."""
    kaynak = (KOK / "audit_chain.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" in kaynak
    ast.parse(kaynak, feature_version=(3, 9))


def test_hicbir_yerel_modulu_import_etmiyor():
    """Dogrulayici, dogruladigi sisteme guvenmemeli."""
    yerel = {p.stem for p in KOK.glob("*.py")} - {"audit_chain"}
    agac = ast.parse((KOK / "audit_chain.py").read_text(encoding="utf-8"))
    importlar = set()
    for d in ast.walk(agac):
        if isinstance(d, ast.Import):
            importlar |= {a.name.split(".")[0] for a in d.names}
        elif isinstance(d, ast.ImportFrom) and d.module:
            importlar.add(d.module.split(".")[0])
    assert not (importlar & yerel), f"yerel import: {importlar & yerel}"


# ── 7. Botla birlikte ────────────────────────────────────────────────────────

def test_bot_denetim_dosyasina_zincirli_yaziyor(vasi_module):
    v = vasi_module
    v.audit_event("ilk", "123456", "x")
    v.audit_event("ikinci", "123456", "y")

    satirlar = [s for s in _satirlar(v.AUDIT_LOG_FILE) if "AUDIT |" in s]
    assert len(satirlar) == 2
    assert "| sira=1 | ozet=" in satirlar[0] and "| sira=2 | ozet=" in satirlar[1]
    assert _dogrula(v.AUDIT_LOG_FILE).saglam


def test_ayrintidaki_sahte_alan_zinciri_bozamaz(vasi_module):
    """Ayrinti icine '| sira=99 | ozet=...' yazmak yeni alan uretmemeli."""
    v = vasi_module
    v.audit_event("olay", "123456", "x | sira=99 | ozet=" + "a" * 32)

    satir = [s for s in _satirlar(v.AUDIT_LOG_FILE) if "AUDIT |" in s][0]
    govde, sira, _ = ac.halka_coz(satir)
    assert sira == 1
    assert _dogrula(v.AUDIT_LOG_FILE).saglam


@pytest.mark.parametrize("bozuk, durum, sozcuk", [
    (False, "ok",   "zincir sağlam (3 halka)"),
    (True,  "warn", "zincir kırık: sıra 2"),
])
def test_saglik_satiri_zinciri_her_seferinde_okuyor(vasi_module, monkeypatch, bozuk, durum, sozcuk):
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    if bozuk:
        s = _satirlar(v.AUDIT_LOG_FILE)
        s[1] = s[1].replace("olay_1", "olay_X")
        _yaz_satirlar(v.AUDIT_LOG_FILE, s)

    satir = v.build_denetim_izi_health()
    assert satir.status == durum
    assert sozcuk in satir.details


def test_guvenlik_raporu_zincir_iddiasi_koda_uyuyor(vasi_module):
    """Rapor 'zincir var' derse zincirli yazici gercekten devrede olmali."""
    v = vasi_module
    rapor = v.build_security_report()
    zincirli = any(type(h).__name__ == "ZincirliDosyaYazicisi"
                   for h in logging.getLogger("vasi").handlers)
    if zincirli:
        assert "her satır bir öncekinin özetini taşır" in rapor
    else:
        assert "zincir yok" in rapor
    assert "zincirleme özet (hash chain) yok" not in rapor


def test_saglik_dis_mudahaleyi_gizlemiyor(vasi_module, monkeypatch):
    """Icerik ayni kalsa bile: calisirken dosyaya dokunulduysa yesil yanmaz."""
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    v.audit_event("bir", "123456", "x")
    _editor_gibi_kaydet(v.AUDIT_LOG_FILE, _satirlar(v.AUDIT_LOG_FILE))
    v.audit_event("iki", "123456", "y")

    satir = v.build_denetim_izi_health()
    assert satir.status == "warn"
    assert "zincir sağlam (3 halka) · dış müdahale kaydı: sıra 2" in satir.details
    assert "iki" in _satirlar(v.AUDIT_LOG_FILE)[-1]      # iz susmadi
