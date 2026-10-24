"""Makine disi capa: zincirin ucu RFC 3161 zaman damgasiyla disariya.

test_audit_store_pg.py::test_SINIR_super_kullanici_tanigi_hala_silebilir
iki taniginin AYNI makinede oldugunu ve makineye erisenin ikisini birlikte
yeniden yazabildigini gosteriyor. Bu dosya ayni saldirinin capalanmis
halkalarda yakalandigini -- ve capanin neyi YAKALAYAMADIGINI (test_SINIR_)
gosteriyor.

Testler disariya istek atmaz: TSA bellekte (tests/_sahte_tsa.py) ama
makbuzlari gercekten imzali. Ayristirici, gercek bir uygulamanin (OpenSSL)
makbuzuyla da sinaniyor (tests/veri/capa_openssl/).
"""
import asyncio
import hashlib
import inspect
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parents[1]
for _y in (KOK, Path(__file__).resolve().parent):
    if str(_y) not in sys.path:
        sys.path.insert(0, str(_y))
import audit_chain as ac  # noqa: E402
import capa  # noqa: E402
from _sahte_tsa import SahteTSA  # noqa: E402

OPENSSL = Path(__file__).resolve().parent / "veri" / "capa_openssl"
OPENSSL_SIRA, OPENSSL_OZET = 42, "0123456789abcdef0123456789abcdef"
OZ = "ab" * 16


# ── Yardimcilar ──────────────────────────────────────────────────────────────

def _zincir(n, govde_on="olay"):
    """{sira: ozet} ve satirlar -- n halkalik gecerli bir zincir."""
    satirlar, onceki, halkalar = [], ac.BASLANGIC, {}
    for sira in range(1, n + 1):
        govde = f"x - vasi - INFO - AUDIT | {govde_on}{sira} | user=*** | - | sira={sira}"
        oz = ac.ozet(onceki, govde)
        satirlar.append(f"{govde} | ozet={oz}")
        halkalar[sira] = oz
        onceki = oz
    return halkalar, satirlar


def _capala(tsa, dizin, sira, ozet, sertifika):
    ad, tsr, m = capa.damgala("https://tsa.test/tsr", sira, ozet, sertifika, gonder=tsa)
    capa.kaydet(dizin, ad, tsr)
    return m


@pytest.fixture()
def tsa(tmp_path):
    t = SahteTSA()
    t.sertifika_dizini = t.sertifikalari_yaz(tmp_path / "sertifika")
    return t


# ── 1. Makbuz: bicim, imza, guven ───────────────────────────────────────────

def test_openssl_makbuzu_okunuyor_ve_imzasi_dogrulaniyor():
    """Ayristirici yalnizca kendi sahte TSA'mizi degil, gercek bir uygulamayi okuyor."""
    m = capa.makbuz_coz((OPENSSL / "ornek.tsr").read_bytes())
    assert m.imprint == hashlib.sha256(capa.capa_metni(OPENSSL_SIRA, OPENSSL_OZET)).digest()
    assert capa.imzayi_dogrula(m, OPENSSL) == "dogrulandi"


def test_openssl_makbuzunda_tek_bayt_degisirse_imza_tutmuyor():
    ham = bytearray((OPENSSL / "ornek.tsr").read_bytes())
    tst_bas = ham.find(hashlib.sha256(capa.capa_metni(OPENSSL_SIRA, OPENSSL_OZET)).digest())
    ham[tst_bas] ^= 0x01                          # damgalanan ozetin ilk bayti
    m = capa.makbuz_coz(bytes(ham))
    assert capa.imzayi_dogrula(m, OPENSSL).startswith("gecersiz")


def test_baska_tsanin_sertifikasiyla_makbuz_gecersiz(tsa):
    m = capa.makbuz_coz((OPENSSL / "ornek.tsr").read_bytes())
    assert capa.imzayi_dogrula(m, tsa.sertifika_dizini).startswith("gecersiz")


def test_sertifika_yoksa_imza_dogrulanmadi_der_sessizce_gecmez(tmp_path):
    m = capa.makbuz_coz((OPENSSL / "ornek.tsr").read_bytes())
    assert capa.imzayi_dogrula(m, tmp_path / "yok") == "dogrulanmadi: TSA sertifikası yok"
    assert not m.imza_dogru


def test_istek_rfc3161_bicimde(tsa):
    istek = capa.istek_olustur(b"\x11" * 32, 12345)
    surum, imprint, nonce, sertifika_iste = capa._tek(istek).cocuklar()
    assert capa._tamsayi(surum) == 1
    assert capa._oid_coz(imprint.cocuklar()[0].cocuklar()[0]) == capa.OID_SHA256
    assert imprint.cocuklar()[1].deger == b"\x11" * 32
    assert capa._tamsayi(nonce) == 12345
    assert sertifika_iste.ham == b"\x01\x01\xff"


def test_damgala_gecerli_makbuzu_kabul_ediyor(tsa, tmp_path):
    ad, tsr, m = capa.damgala("u", 7, OZ, tsa.sertifika_dizini, gonder=tsa)
    assert ad == f"capa-00000007-{OZ}.tsr"
    assert m.imza == "dogrulandi"


@pytest.mark.parametrize("ayar, mesaj", [
    ({"baska_ozet": True}, "başka bir özeti"),
    ({"nonce_kaydir": 1}, "nonce"),
    ({"durum": 2}, "reddetti"),
])
def test_damgala_yanlis_makbuzu_reddediyor(tsa, ayar, mesaj):
    for k, v in ayar.items():
        setattr(tsa, k, v)
    with pytest.raises(capa.CapaHatasi, match=mesaj):
        capa.damgala("u", 7, OZ, tsa.sertifika_dizini, gonder=tsa)


def test_damgala_baska_anahtarla_imzali_makbuzu_saklamiyor(tsa, tmp_path):
    """Makineyi ele geciren biri kendi 'TSA'sini kurabilir: depodaki sertifika durdurur."""
    from cryptography.hazmat.primitives.asymmetric import ec
    tsa.imzalayan = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(capa.CapaHatasi, match="imza tutmuyor"):
        capa.damgala("u", 7, OZ, tsa.sertifika_dizini, gonder=tsa)


def test_tsaya_ulasilamazsa_capahatasi():
    def kopuk(*_a):
        raise OSError("ağ yok")
    with pytest.raises(capa.CapaHatasi, match="ulaşılamadı"):
        capa.damgala("u", 7, OZ, gonder=kopuk)


def test_kaydet_var_olan_makbuzun_ustune_yazmaz(tmp_path):
    capa.kaydet(tmp_path, "capa-00000001-" + OZ + ".tsr", b"a")
    capa.kaydet(tmp_path, "capa-00000001-" + OZ + ".tsr", b"a")      # ayni: sorun yok
    with pytest.raises(capa.CapaHatasi, match="üstüne yazılmaz"):
        capa.kaydet(tmp_path, "capa-00000001-" + OZ + ".tsr", b"b")


def test_capa_yalnizca_standart_kutuphane_ve_audit_chain_kullanir():
    kaynak = (KOK / "capa.py").read_text(encoding="utf-8")
    yerel = {p.stem for p in KOK.glob("*.py")} - {"capa", "audit_chain"}
    for satir in kaynak.splitlines():
        m = re.match(r"\s*(?:import|from)\s+(\w+)", satir)
        if m:
            assert m.group(1) not in yerel, satir


# ── 2. Zincirle karsilastirma: neyi yakaliyor ───────────────────────────────

def test_temiz_zincir_ve_capalar_tutuyor(tsa, tmp_path):
    halkalar, _ = _zincir(10)
    for s in (4, 8, 10):
        _capala(tsa, tmp_path / "c", s, halkalar[s], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, sertifika_dizini=tsa.sertifika_dizini)
    assert r.saglam and not r.uyarilar
    assert r.son.sira == 10 and r.imzasi_dogrulanan == 3
    assert "çapalı: sıra ≤ 10" in capa.ozet_satiri(r)


def test_capalanmis_halka_yeniden_yazilirsa_yakalaniyor(tsa, tmp_path):
    """'Günlükler Yalan Söyleyebilir mi?' 4. deneme: makineye erisen biri dosyayi
    (ve tanigi) bastan yazar. Capalanan ozet makinenin disinda: tutmaz."""
    halkalar, _ = _zincir(10)
    _capala(tsa, tmp_path / "c", 8, halkalar[8], tsa.sertifika_dizini)
    yeniden, _ = _zincir(10, govde_on="sahte")        # 1'den itibaren yeniden hesaplanmis
    r = capa.capalari_dogrula(tmp_path / "c", yeniden, sertifika_dizini=tsa.sertifika_dizini)
    assert not r.saglam
    assert any("sıra 8 çapalandıktan sonra dosyada yeniden yazılmış" in s for _, s in r.sorunlar)


def test_tanikta_yeniden_yazilan_halka_da_yakalaniyor(tsa, tmp_path):
    halkalar, _ = _zincir(5)
    _capala(tsa, tmp_path / "c", 5, halkalar[5], tsa.sertifika_dizini)
    tanik = dict(halkalar)
    tanik[5] = "cd" * 16
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, tanik, sertifika_dizini=tsa.sertifika_dizini)
    assert any("tanıkta yeniden yazılmış" in s for _, s in r.sorunlar)


def test_zincirin_sonu_kesilirse_yakalaniyor(tsa, tmp_path):
    halkalar, _ = _zincir(10)
    _capala(tsa, tmp_path / "c", 10, halkalar[10], tsa.sertifika_dizini)
    kesik = {s: o for s, o in halkalar.items() if s <= 6}
    r = capa.capalari_dogrula(tmp_path / "c", kesik, sertifika_dizini=tsa.sertifika_dizini)
    assert any("zincir çapanın gerisinde" in s for _, s in r.sorunlar)


def test_yeniden_yazip_yeniden_capalamak_iki_farkli_capa_birakir(tsa, tmp_path):
    halkalar, _ = _zincir(6)
    _capala(tsa, tmp_path / "c", 6, halkalar[6], tsa.sertifika_dizini)
    sahte, _ = _zincir(6, govde_on="sahte")
    _capala(tsa, tmp_path / "c", 6, sahte[6], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", sahte, sertifika_dizini=tsa.sertifika_dizini)
    assert any("iki farklı çapa" in s for _, s in r.sorunlar)


def test_adi_degistirilen_makbuz_yakalaniyor(tsa, tmp_path):
    halkalar, _ = _zincir(5)
    _capala(tsa, tmp_path / "c", 5, halkalar[5], tsa.sertifika_dizini)
    eski = tmp_path / "c" / capa.makbuz_adi(5, halkalar[5])
    eski.rename(tmp_path / "c" / capa.makbuz_adi(5, "ef" * 16))
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, sertifika_dizini=tsa.sertifika_dizini)
    assert any("damgalamamış" in s for _, s in r.sorunlar)


def test_geriye_tarihli_zincir_capa_zamanindan_yakalaniyor(tsa, tmp_path):
    """Daha buyuk sira, daha kucuk siradan once damgalanmis olamaz."""
    halkalar, _ = _zincir(8)
    _capala(tsa, tmp_path / "c", 4, halkalar[4], tsa.sertifika_dizini)
    tsa.zaman = datetime.now(timezone.utc) - timedelta(days=3)
    _capala(tsa, tmp_path / "c", 8, halkalar[8], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, sertifika_dizini=tsa.sertifika_dizini)
    assert any("önce damgalanmış" in s for _, s in r.sorunlar)


def test_capa_gecikirse_uyari(tsa, tmp_path):
    halkalar, _ = _zincir(10)
    _capala(tsa, tmp_path / "c", 5, halkalar[5], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, sertifika_dizini=tsa.sertifika_dizini,
                              aralik_sn=3600, simdi=datetime.now(timezone.utc) + timedelta(hours=3))
    assert r.saglam
    assert r.uyarilar and "çapa gecikti" in r.uyarilar[0] and "5 halka çapasız" in r.uyarilar[0]


def test_hic_capa_yoksa_uyari(tmp_path):
    halkalar, _ = _zincir(3)
    r = capa.capalari_dogrula(tmp_path / "yok", halkalar)
    assert r.uyarilar == ["hiç çapa yok: zincirin hiçbir halkası makine dışında kayıtlı değil"]


def test_komut_satiri_yeniden_yazilan_zinciri_bildiriyor(tsa, tmp_path, capsys):
    halkalar, satirlar = _zincir(6)
    log = tmp_path / "denetim.log"
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    _capala(tsa, tmp_path / "c", 6, halkalar[6], tsa.sertifika_dizini)
    arg = [str(log), "--capa", str(tmp_path / "c"), "--sertifika", str(tsa.sertifika_dizini)]
    assert capa.main(arg) == 0
    _, sahte = _zincir(6, govde_on="sahte")
    log.write_text("\n".join(sahte) + "\n", encoding="utf-8")
    assert capa.main(arg) == 1
    assert "yeniden yazılmış" in capsys.readouterr().out


# ── 3. Sinirlar: capanin YAKALAYAMADIKLARI ───────────────────────────────────

def test_SINIR_son_capadan_sonra_yazilan_halkalar_korunmaz(tsa, tmp_path):
    """Bu test GECMELI. Pencere, capa sikligidir (varsayilan bir saat).

    Son capadan sonra yazilan halkalari makineye erisen biri yine yeniden
    yazabilir; capa onlari hic gormedi.
    """
    halkalar, _ = _zincir(10)
    _capala(tsa, tmp_path / "c", 6, halkalar[6], tsa.sertifika_dizini)
    sahte = dict(halkalar)
    for s in (7, 8, 9, 10):
        sahte[s] = "ee" * 16
    r = capa.capalari_dogrula(tmp_path / "c", sahte, sertifika_dizini=tsa.sertifika_dizini)
    assert r.saglam, "Bu artik yakalaniyorsa bu testi guncelle"


def test_SINIR_makinedeki_makbuzlar_silinebilir_telegram_kopyasi_yakalar(tsa, tmp_path):
    """Bu test GECMELI. Makbuzun sahtesi uretilemez ama makinedeki silinebilir.

    Yalnizca makinedeki klasorle dogrulanirsa sonuc "hic capa yok" uyarisidir,
    bulgu degil. Sahibin Telegram'dan indirdigi kopya verilince yeniden yazma
    ortaya cikar: kopya, makineye erisenin ulasamadigi yerdedir.
    """
    halkalar, _ = _zincir(6)
    _capala(tsa, tmp_path / "makine", 6, halkalar[6], tsa.sertifika_dizini)
    _capala(tsa, tmp_path / "telefon", 6, halkalar[6], tsa.sertifika_dizini)
    for p in (tmp_path / "makine").iterdir():
        p.unlink()                                    # saldirgan makbuzu siler
    sahte, _ = _zincir(6, govde_on="sahte")
    yerel = capa.capalari_dogrula(tmp_path / "makine", sahte, sertifika_dizini=tsa.sertifika_dizini)
    assert yerel.saglam and yerel.uyarilar             # yalnizca uyari
    kopyayla = capa.capalari_dogrula([tmp_path / "makine", tmp_path / "telefon"], sahte,
                                     sertifika_dizini=tsa.sertifika_dizini)
    assert not kopyayla.saglam


# ── 4. Vasi'ye bagli: saatlik capa, onay, saglik ────────────────────────────

@pytest.fixture()
def capali(vasi_module, tsa, monkeypatch, tmp_path):
    v = vasi_module
    monkeypatch.setattr(v, "CAPA_TSA", "https://tsa.test/tsr")
    monkeypatch.setattr(v, "CAPA_ACIK", True)
    monkeypatch.setattr(v, "CAPA_SERTIFIKA_DIZINI", tsa.sertifika_dizini)
    monkeypatch.setattr(v, "CAPA_DIZINI", tmp_path / "capa")
    monkeypatch.setattr(v.capa, "_http_gonder", tsa)
    v.tsa = tsa
    return v


class _Bot:
    def __init__(self, patlar=False):
        self.gonderilen, self.patlar = [], patlar

    async def send_document(self, **kw):
        if self.patlar:
            raise ConnectionError("telegram kapalı")
        self.gonderilen.append(kw)


def test_capa_kapaliyken_saglik_bunu_soyler(vasi_module):
    c = vasi_module.build_capa_health()
    assert c.status == "warn" and "kapalı" in c.details


def test_capa_zincirin_ucunu_damgaliyor_yeni_halka_yoksa_tekrar_etmiyor(capali):
    v = capali
    v.audit_event("deneme", "1", "-")
    yol, m = v.capa_at("deneme")
    assert yol.name == capa.makbuz_adi(v._audit_yazici.son_sira, v._audit_yazici.son_ozet)
    assert m.imza == "dogrulandi"
    assert v.capa_at("deneme") is None                  # yeni halka yok
    v.audit_event("deneme", "1", "-")
    assert v.capa_at("deneme") is not None
    assert len(v.tsa.istekler) == 2


def test_basarili_capa_ize_yazilmaz_bos_sistem_saatlik_mesaj_atmaz(capali):
    v = capali
    v.audit_event("deneme", "1", "-")
    once = v._audit_yazici.son_sira
    v.capa_at("saatlik")
    assert v._audit_yazici.son_sira == once
    assert v.capa_at("saatlik") is None


def test_kopya_telegrama_gidiyor_ve_saglik_yesil(capali):
    v = capali
    v.audit_event("deneme", "1", "-")
    bot = _Bot()
    asyncio.run(v.capa_at_ve_gonder(bot, "saatlik"))
    assert len(bot.gonderilen) == 1
    g = bot.gonderilen[0]
    assert g["chat_id"] == v.MY_TELEGRAM_ID and g["filename"].startswith("capa-")
    assert capa.makbuz_coz(g["document"]).imza  # gercek makbuz baytlari
    c = v.build_capa_health()
    assert c.status == "ok", c.details
    asyncio.run(v.capa_at_ve_gonder(bot, "saatlik"))
    assert len(bot.gonderilen) == 1                     # ayni kopya iki kez gitmez


def test_telegram_kapaliysa_kopya_bekler_ve_saglik_soyler(capali):
    v = capali
    v.audit_event("deneme", "1", "-")
    asyncio.run(v.capa_at_ve_gonder(_Bot(patlar=True), "saatlik"))
    c = v.build_capa_health()
    assert c.status == "warn" and "Telegram'a gitmedi" in c.details
    bot = _Bot()
    asyncio.run(v.capa_at_ve_gonder(bot, "saatlik"))
    assert len(bot.gonderilen) == 1


def test_tsa_ulasilamazsa_bot_durmaz_ve_olay_ize_yazilir(capali, tmp_path):
    v = capali
    v.tsa.durum = 2
    v.audit_event("deneme", "1", "-")
    asyncio.run(v.capa_at_ve_gonder(_Bot(), "saatlik"))
    metin = Path(v.AUDIT_LOG_FILE).read_text(encoding="utf-8")
    assert "AUDIT | capa_atilamadi |" in metin
    assert not list((tmp_path / "capa").glob("capa-*.tsr"))


def test_dosya_capadan_sonra_yeniden_yazilirsa_saglik_ve_iz_dogrula_soyler(capali):
    v = capali
    for i in range(3):
        v.audit_event("deneme", "1", str(i))
    v.capa_at("deneme")
    yol = Path(v.AUDIT_LOG_FILE)
    satirlar = yol.read_text(encoding="utf-8").splitlines()
    yeni, onceki = [], ac.BASLANGIC
    for s in satirlar:                                 # her satiri degistirip bastan hesapla
        govde, _, _ = ac.halka_coz(s)
        govde = govde.replace("deneme", "sahte")
        oz = ac.ozet(onceki, govde)
        yeni.append(f"{govde} | ozet={oz}")
        onceki = oz
    yol.write_text("\n".join(yeni) + "\n", encoding="utf-8")
    assert ac.dogrula_dosyalar(ac.dosyalari_sirala(yol)).saglam   # dosya tek basina kanar
    c = v.build_capa_health()
    assert c.status == "warn" and "çapa tutmuyor" in c.details
    assert "yeniden yazılmış" in capa.rapor_metni(v.capa_raporu(imza_sayisi=None))


def test_onay_hemen_capa_atiyor():
    kaynak = (KOK / "vasi.py").read_text(encoding="utf-8")
    blok = kaynak[kaynak.index('elif action == "iz_onayla":'):]
    blok = blok[:blok.index("result = (")]
    assert 'capa_arka_planda(context, "onay")' in blok


def test_saatlik_dongu_ve_kapanis_capasi_uygulamaya_bagli(vasi_module):
    kaynak = inspect.getsource(vasi_module)
    assert ".post_init(_capa_baslat).post_stop(_capa_kapat)" in kaynak
    assert "build_capa_health()" in inspect.getsource(vasi_module.build_health_report)


def test_dockerfile_capa_ve_sertifika_klasorunu_kopyaliyor():
    if not (KOK / "Dockerfile").exists():
        pytest.skip("Dockerfile yok (konteynerde kopyalanmiyor)")
    d = (KOK / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY capa.py ." in d and "COPY scripts/capa ./scripts/capa" in d


# ── 5. Bagimsiz inceleme (Ekim 2026): ilk surumu kiran yollar ───────────────
#
# Isi gormemis ayri bir yapay zeka ajani ilk surumu kirdi. Her saldiri once
# burada test olarak yazildi; kirmizisi goruldu, sonra kapatildi.

@pytest.fixture()
def sahip(tsa, tmp_path):
    """20 halkalik zincir; 5, 10, 15 capali; kopyalar makinede ve telefonda."""
    halkalar, satirlar = _zincir(20)
    log = tmp_path / "makine" / "denetim.log"
    log.parent.mkdir()
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    for s in (5, 10, 15):
        ad, tsr, _ = capa.damgala("u", s, halkalar[s], tsa.sertifika_dizini, gonder=tsa)
        capa.kaydet(tmp_path / "makine" / "capa", ad, tsr)
        capa.kaydet(tmp_path / "telefon", ad, tsr)
    arg = [str(log), "--capa", str(tmp_path / "makine" / "capa"),
           "--capa", str(tmp_path / "telefon"), "--sertifika", str(tsa.sertifika_dizini)]
    assert capa.main(arg) == 0
    return log, satirlar, halkalar, arg


def test_capali_satirin_govdesi_degisip_ozeti_birakilirsa_yakalaniyor(sahip, capsys):
    log, satirlar, _, arg = sahip
    satirlar = list(satirlar)
    satirlar[9] = satirlar[9].replace("olay10", "SAHTE")
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert capa.main(arg) == 1
    assert "sıra 10 çapalandıktan sonra dosyada yeniden yazılmış" in capsys.readouterr().out


def test_cli_zincirin_kendisi_kiriksa_temiz_demiyor(sahip, capsys):
    """Capasiz bir halkanin govdesi degisti: capa tutar ama zincir kirik -> 1."""
    log, satirlar, _, arg = sahip
    satirlar = list(satirlar)
    satirlar[11] = satirlar[11].replace("olay12", "SAHTE")
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert capa.main(arg) == 1
    assert "Zincirin kendisi kırık" in capsys.readouterr().out


def test_capali_satir_silinirse_yakalaniyor(sahip, capsys):
    log, satirlar, _, arg = sahip
    log.write_text("\n".join(s for i, s in enumerate(satirlar) if i != 9) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert capa.main(arg) == 1
    assert "çapalanmış sıra 10 dosyada yok" in capsys.readouterr().out


def test_sahte_rotasyon_temiz_gecmiyor(sahip, capsys):
    """Butun gecmis silinip sira 16'dan baslayan sahte bir 'donmus' dosya kurulur.

    Sahte rotasyon gercegiyle ayni gorunur; dogrulayici ikisini AYIRAMAZ, ama
    'tutuyor' da demez: capali halkalar karsilastirilamadi diye uyarir (3).
    """
    log, _, _, arg = sahip
    rot = (f"x - vasi - INFO - AUDIT | {ac.ROTASYON_OLAYI} | user=sistem | "
           f"onceki_son_sira=15 onceki_ozet={'cd' * 16} | sira=16")
    oz = ac.ozet("cd" * 16, rot)
    satirlar, onceki = [f"{rot} | ozet={oz}"], oz
    for s in range(17, 27):
        g = f"x - vasi - INFO - AUDIT | uydurma{s} | user=*** | - | sira={s}"
        onceki = ac.ozet(onceki, g)
        satirlar.append(f"{g} | ozet={onceki}")
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    Path(str(log) + ".1").write_text("", encoding="utf-8")
    assert ac.dogrula_dosyalar(ac.dosyalari_sirala(log)).saglam   # dosya tek basina kanar
    capsys.readouterr()
    assert capa.main(arg) == 3
    cikti = capsys.readouterr().out
    assert "çapa 15" in cikti and "karşılaştırılamadı" in cikti and "✅" not in cikti


def test_capadan_sonra_verilen_sahte_onay_uyari_veriyor(sahip, capsys):
    """Govde degisikligi + capasiz pencereye eklenmis gecerli bir onay halkasi."""
    log, satirlar, halkalar, arg = sahip
    satirlar = list(satirlar)
    satirlar[9] = satirlar[9].replace("olay10", "SAHTE")
    dr = ac.dogrula(enumerate(satirlar))
    govde = (f"x - vasi - INFO - AUDIT | {ac.ONAY_OLAYI} | user=*** | kapsam=20 "
             f"bulgu={len(dr.sorunlar)} onay={','.join(s.kimlik for s in dr.sorunlar)} | sira=21")
    satirlar.append(f"{govde} | ozet={ac.ozet(halkalar[20], govde)}")
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    assert ac.dogrula_dosyalar(ac.dosyalari_sirala(log)).saglam
    capsys.readouterr()
    assert capa.main(arg) != 0
    assert "Bu onayı sen verdin mi?" in capsys.readouterr().out


def test_bozuk_makbuz_dogrulayiciyi_dusurmuyor_bulgu_oluyor(sahip, capsys, tmp_path):
    log, _, _, arg = sahip
    (Path(arg[2]) / f"capa-00000001-{'0' * 32}.tsr").write_bytes(b"\x30\x02\x30\x00")
    capsys.readouterr()
    assert capa.main(arg) == 1
    assert "makbuz geçersiz" in capsys.readouterr().out


def test_telegram_kopyasi_yeniden_adlandirilmis_ya_da_klasorde_okunuyor(tsa, tmp_path):
    halkalar, _ = _zincir(6)
    _capala(tsa, tmp_path / "x", 6, halkalar[6], tsa.sertifika_dizini)
    kaynak = tmp_path / "x" / capa.makbuz_adi(6, halkalar[6])
    (tmp_path / "telefon" / "ekim").mkdir(parents=True)
    kaynak.rename(tmp_path / "telefon" / "ekim" / kaynak.name.replace(".tsr", " (1).tsr"))
    r = capa.capalari_dogrula(tmp_path / "telefon", halkalar, sertifika_dizini=tsa.sertifika_dizini)
    assert [c.sira for c in r.capalar] == [6]


def test_halkasindan_cok_sonra_damgalanan_capa_uyari(tsa, tmp_path):
    """Telegram kopyalari botun anahtariyla degistirilebilir: zinciri yeniden
    yazip bugun yeniden capalayan biri, eski halkalara bugunun makbuzunu verir."""
    halkalar, _ = _zincir(4)
    govdeler = {s: f"2026-01-01 10:00:00,000 - vasi - INFO - AUDIT | olay{s} | sira={s}"
                for s in halkalar}
    _capala(tsa, tmp_path / "c", 4, halkalar[4], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", halkalar, sertifika_dizini=tsa.sertifika_dizini,
                              govdeler=govdeler, aralik_sn=3600)
    assert any("çok sonra damgalanmış" in u for u in r.uyarilar)


def _bot_sinifi():
    class Bot:
        def __init__(self, patlar=False):
            self.patlar, self.giden = patlar, []

        async def send_document(self, **kw):
            if self.patlar:
                raise ConnectionError("telegram kapalı")
            self.giden.append(kw["filename"])
    return Bot


def test_birikmis_kopyalar_eskiden_baslayarak_gidiyor_saglik_bitene_kadar_uyarir(capali):
    v, Bot = capali, _bot_sinifi()
    for _ in range(30):
        v.audit_event("deneme", "1", "-")
        asyncio.run(v.capa_at_ve_gonder(Bot(patlar=True), "saatlik"))
    acik = Bot()
    asyncio.run(v.capa_at_ve_gonder(acik, "saatlik"))
    assert len(acik.giden) == 24 and acik.giden == sorted(acik.giden)
    c = v.build_capa_health()
    assert c.status == "warn" and "6 makbuz henüz Telegram'a gitmedi" in c.details
    asyncio.run(v.capa_at_ve_gonder(acik, "saatlik"))
    assert len(acik.giden) == 30


def test_bozuk_makbuz_telegram_kopyalarini_durdurmuyor(capali, tmp_path):
    v, Bot = capali, _bot_sinifi()
    (tmp_path / "capa").mkdir(exist_ok=True)
    (tmp_path / "capa" / f"capa-00000000-{'0' * 32}.tsr").write_bytes(b"\x30\x02\x30\x00")
    b = Bot()
    for _ in range(3):
        v.audit_event("deneme", "1", "-")
        asyncio.run(v.capa_at_ve_gonder(b, "saatlik"))
    assert len(b.giden) == 3


def test_klasordeki_ileri_sirali_dosya_capalamayi_durdurmuyor(capali, tmp_path):
    v = capali
    (tmp_path / "capa").mkdir(exist_ok=True)
    (tmp_path / "capa" / f"capa-99999999-{'0' * 32}.tsr").write_bytes(b"x")
    v.audit_event("deneme", "1", "-")
    assert v.capa_at("saatlik") is not None
    assert v.build_capa_health().status == "warn"


# ── 6. Ikinci inceleme: duzeltmelerin kendisi ───────────────────────────────

def test_mesru_onay_kalici_uyari_birakmiyor(sahip, tsa, capsys):
    """Cokmeden kalan yarim satir capalanir, sahip sonra onaylar: bu olagan
    akis kalici bir uyari birakmamali (yalnizca icerik degisikligi sorulur)."""
    log, satirlar, halkalar, arg = sahip
    satirlar = satirlar[:6] + ["2026-10-20 10:06:30,000 - vasi - INFO - AUDIT | yar"] + satirlar[6:]
    dr = ac.dogrula(enumerate(satirlar))
    assert [s.tur for s in dr.sorunlar] == ["zincirsiz"]
    govde = (f"x - vasi - INFO - AUDIT | {ac.ONAY_OLAYI} | user=*** | kapsam=20 bulgu=1 "
             f"onay={dr.sorunlar[0].kimlik} | sira=21")
    oz = ac.ozet(halkalar[20], govde)
    satirlar.append(f"{govde} | ozet={oz}")
    ad, tsr, _ = capa.damgala("u", 21, oz, tsa.sertifika_dizini, gonder=tsa)
    capa.kaydet(Path(arg[2]), ad, tsr)
    log.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert capa.main(arg) == 0
    assert "✅" in capsys.readouterr().out


def test_ilk_satir_capasi_yeniden_hesaplanamazsa_temiz_denmiyor(tsa, tmp_path):
    halkalar, satirlar = _zincir(12)
    govdeler = {s: ac.halka_coz(l)[0] for s, l in zip(range(1, 13), satirlar)}
    kesik = {s: o for s, o in halkalar.items() if s >= 10}
    _capala(tsa, tmp_path / "c", 10, halkalar[10], tsa.sertifika_dizini)
    r = capa.capalari_dogrula(tmp_path / "c", kesik, sertifika_dizini=tsa.sertifika_dizini,
                              govdeler={s: g for s, g in govdeler.items() if s >= 10})
    assert r.hesaplanamayan == [10]
    assert "✅" not in capa.rapor_metni(r)


def test_guvenlik_raporu_capa_durumunu_olcumden_soyluyor(vasi_module, monkeypatch):
    v = vasi_module
    assert "çapalanmıyor" in v.build_security_report()
    monkeypatch.setattr(v, "CAPA_ACIK", True)
    monkeypatch.setattr(v, "capa_raporu", lambda *a, **k: capa.CapaRaporu())
    metin = v.build_security_report()
    assert "makine dışına çapalanır" in metin and "çapa yok" in metin
