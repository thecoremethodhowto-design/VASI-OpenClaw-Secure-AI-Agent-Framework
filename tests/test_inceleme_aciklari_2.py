"""Ikinci bagimsiz inceleme (5 Ekim 2026): duzeltmelerin kendisi kirildi.

Faz 6, ilk incelemenin buldugu dort acigi kapatti; testleri yesildi. Ayni
inceleyici duzeltmeleri yeniden kirmaya calisti. Ayrica videonun cekim
akisini, yaratanin bugunku izinin birebir kopyasi uzerinde, gercek bir
PostgreSQL ile adim adim oynatti. Buradaki her test bir bulguyu birebir
kuruyor; duzeltmeden ONCE hepsi kirmiziydi.

  1. Bes BOS sahte donmus dosya (denetim.log.1 ... .5), dosyanin basindan
     silmeyi "rotasyon" diye akliyordu: bot, tanik ve Mac'teki dogrulayici
     ucu de yesil. Gercek satirlar sahte dosyalara tasininca zincirin
     surekliligi bile saglaniyordu.
  2. Mac'teki dogrulayici bottan gevsekti: tek bos '.1' yetiyordu.
  3. Tanik bir kez sifirlaninca HER acilis yeni bir alarm yaziyordu; onay
     bunu durduramiyordu. Cekimin son "yesil" karesi alinamazdi. Dogum
     kaydi rotasyonla gidince de tanigin silinmesi gorulmuyordu.
  4. Yeniden onaylandiktan sonra da "eski bicimli onay ... yeniden
     onaylayin" uyarisi her yesil ekranda kaliyordu.
  5. Saglik satirinda "tanık: tanık sıfırlanmış" kelime tekrari.
  6. Yazicinin kendi kayitlari (tanik tamamlandi, calisirken silinen tanik
     alarmi) bir sonraki olaya erteleniyordu; olay gelmezse hic yazilmiyordu.

Duzeltme: rotasyon artik zincirde iz birakir. Her yeni dosya bir donme
kaydiyla baslar (denetim_dosyasi_dondu | onceki_son_sira=N). Dosyalarin
basindaki eksiklik ancak boyle bir kayitla basliyorsa rotasyondur. Tanik da
kendi kopyasindaki donme kayitlarini sayar: yedek sayisina gore hangi
halkalarin gitmis olmasi gerektigini bilir. Tanik sifirlaninca alarmla
birlikte yeni bir dogum kaydi yazilir; acilis en son dogumla hizalanir.

Kodla kapanmayanlar sinir olarak yazildi (bkz. test_SINIR_...): dosyanin
kenarindan butun bir birimi goturmeyi dosya tek basina goremez; dosyayi VE
tanigi birlikte eski bir haline donduren ya da ikisine birden onay ekleyen
biri yakalanmaz. Bunlar ayni makinenin sinirlari.
"""
import logging
import sys
import uuid
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import audit_chain as ac  # noqa: E402
from test_ikinci_tanik import _SahteTanik, _Yazici, _satirlar, _yaz_satirlar  # noqa: E402
from test_inceleme_aciklari import _dosya, _iki, _onayla, _zincir  # noqa: E402
from test_iz_onayi import tanikli  # noqa: E402,F401  (pytest fikstur)

DONME = "denetim_dosyasi_dondu"


class _DonenYazici(_Yazici):
    """Kucuk dosyalarla donen tanikli yazici: rotasyonu dakikalar degil satirlar tetikler."""

    def __init__(self, yol, tanik, maxBytes=600, backupCount=2):
        self.lg = logging.getLogger(f"donen-test-{uuid.uuid4().hex}")
        self.lg.propagate = False
        self.lg.setLevel(logging.INFO)
        self.h = ac.ZincirliDosyaYazicisi(str(yol), tanik=tanik, encoding="utf-8",
                                          maxBytes=maxBytes, backupCount=backupCount)
        self.h.setFormatter(logging.Formatter("%(message)s"))
        self.lg.addHandler(self.h)


def _siralar(yol):
    return [h[1] for h in map(ac.halka_coz, _satirlar(yol)) if h]


def _dondur(yol, tanik, n=40, yedek=2):
    with _DonenYazici(yol, tanik, backupCount=yedek) as y:
        y.yaz(*[f"olay_{i:02d}" for i in range(n)])
    return ac.dosyalari_sirala(yol)


# ── 1-2. Sahte donmus dosyalar ───────────────────────────────────────────────

def test_bos_sahte_donmus_dosyalar_bastan_silmeyi_aklamiyor(tmp_path, capsys):
    yol = tmp_path / "iz.log"
    _yaz_satirlar(yol, _zincir(6)[2:])               # sira 1-2 bot dururken silindi
    for n in range(1, 6):                            # ... ve 5 bos "donmus dosya"
        Path(f"{yol}.{n}").write_text("", encoding="utf-8")
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 3)], r.sorunlar
    assert not r.bas_rotasyon
    assert ac.main([str(yol)]) == 1
    assert "rotasyonla silinmiş" not in capsys.readouterr().out


def test_gercek_satirlar_sahte_donmus_dosyalara_tasinsa_da_yakalaniyor(tmp_path):
    """Sureklilik bile saglaniyor: sira 1-4 silinmis, 5-9 bes dosyaya dagitilmis."""
    yol, z = tmp_path / "iz.log", _zincir(12)
    for n, satir in zip(range(5, 0, -1), z[4:9]):    # .5 en eski: sira 5 ... .1: sira 9
        Path(f"{yol}.{n}").write_text(satir + "\n", encoding="utf-8")
    _yaz_satirlar(yol, z[9:])
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 5)], r.sorunlar
    assert "dönme kaydı" in r.sorunlar[0].aciklama


def test_ilk_satiri_donme_kaydina_cevirmek_ise_yaramiyor(tmp_path):
    """Saldirgan basi siler, kalan ilk satirin govdesini bir donme kaydina
    cevirir ve ozeti oldugu gibi birakir: sonraki halka hala ona baglanir.
    Donme kaydi bir onceki ozeti tasidigi icin kendi ozeti dogrulanir."""
    yol, z = tmp_path / "iz.log", _zincir(8)
    oz = ac.halka_coz(z[4])[2]                       # sira 5'in gercek ozeti
    onceki = ac.halka_coz(z[3])[2]                   # sira 4'unku: saldirgan da biliyor
    sahte = f"AUDIT | {DONME} | user=sistem | onceki_son_sira=4 onceki_ozet={onceki} | sira=5"
    Path(f"{yol}.1").write_text(f"{sahte} | ozet={oz}\n", encoding="utf-8")
    _yaz_satirlar(yol, z[5:])
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 5)], r.sorunlar


def test_mac_dogrulayicisi_tek_bos_yedekle_kandirilamiyor(tmp_path, capsys):
    yol = tmp_path / "iz.log"
    _yaz_satirlar(yol, _zincir(5)[3:])
    Path(f"{yol}.1").write_text("", encoding="utf-8")
    assert ac.main([str(yol)]) == 1
    cikti = capsys.readouterr().out
    assert "başlangıç eksik" in cikti and "rotasyonla silinmiş" not in cikti


def test_sahte_donmus_dosyalar_tanigi_da_kandiramiyor(tmp_path):
    """Tanigin tuttugu halkalar 'rotasyonla gitmis olabilir' diye gizlenmemeli."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    _yaz_satirlar(yol, _satirlar(yol)[2:])           # dogum kaydi ve 'bir' gitti
    for n in range(1, 6):
        Path(f"{yol}.{n}").write_text("", encoding="utf-8")
    r, k, _ = _iki(yol, tanik)
    assert not r.bas_rotasyon
    assert [s for s, _ in k.dosyada_yok] == [1, 2] and k.dosya_oncesi == 0


# ── Gercek rotasyon: iz birakir ──────────────────────────────────────────────

def test_gercek_rotasyon_her_yeni_dosyayi_donme_kaydiyla_baslatiyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    dosyalar = _dondur(yol, tanik)
    assert len(dosyalar) == 3, "rotasyon tetiklenmedi"
    for d in dosyalar:
        ilk = _satirlar(d)[0]
        assert f"| {DONME} | user=sistem | onceki_son_sira=" in ilk, ilk
        assert ac.halka_coz(ilk)[1] == int(ilk.split("onceki_son_sira=")[1].split()[0]) + 1
    r = _dosya(yol)
    assert r.saglam and r.bas_rotasyon and r.baslangic_eksik, r.sorunlar
    assert r.tanik_baslangici == 1, "dogum kaydi rotasyonla gitti, donme kaydi tasimiyor"
    k, t = ac.iki_tanigi_karsilastir(r, tanik.halkalar(), yedek_sayisi=2)
    assert k.uyusuyor and t.saglam and k.dosya_oncesi > 0, (k, t.sorunlar)
    assert "tanıktaki dönme kayıtlarıyla uyumlu" in ac.karsilastirma_metni(k, r, t)
    assert ac.main([str(yol)]) == 0                  # Mac'teki dogrulayici da yanlis alarm vermiyor


def test_rotasyondan_sonra_en_eski_dosyanin_icerigi_giderse_tanik_yakaliyor(tmp_path):
    """Dosya sayisi ayni kaliyor; yalnizca en eski dosyanin icerigi gidiyor."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _dondur(yol, tanik)
    en_eski = Path(f"{yol}.2")
    giden = _siralar(en_eski)
    en_eski.write_text("", encoding="utf-8")         # bot dururken
    r = _dosya(yol)
    k, _ = ac.iki_tanigi_karsilastir(r, tanik.halkalar(), yedek_sayisi=2)
    assert [s for s, _ in k.dosyada_yok] == giden, (k.dosyada_yok, giden)


def test_SINIR_dosya_tek_basina_butun_bir_eski_dosyanin_silinmesini_goremez(tmp_path):
    """Bu test GECMELI. Sondan silinen satirlar gibi: zincirin kenarindan
    butun bir birimi goturmek dosyanin kendi tutarliligini bozmaz. Kalan en
    eski dosya gercek bir donme kaydiyla basliyor. Bunu tanik gorur (bir
    ustteki test); Mac'teki dogrulayici goremez."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _dondur(yol, tanik)
    Path(f"{yol}.2").write_text("", encoding="utf-8")
    assert _dosya(yol).saglam, "Bu artik dosyada yakalaniyorsa bu testi guncelle"


def test_tanik_yedek_sayisini_bilmiyorsa_eski_kurala_donuyor(tmp_path):
    """Elle cagrilan karsilastirma (yedek sayisi yok): dosyalarin basindan
    oncesi rotasyon olabilir -- ama yalnizca dosyalar bir donme kaydiyla basliyorsa."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _dondur(yol, tanik)
    r = _dosya(yol)
    k, _ = ac.iki_tanigi_karsilastir(r, tanik.halkalar())
    assert k.uyusuyor and k.dosya_oncesi > 0


# ── 3. Tanik sifirlaninca yeniden dogar ──────────────────────────────────────

def test_tanik_sifirlaninca_yeniden_dogar_sonraki_acilislar_sessiz(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    tanik.sifirla()                                  # DROP TABLE, bot dururken
    tanik.sema_kur()
    with _Yazici(yol, tanik) as y:
        y.yaz("uc")                                  # acilis: alarm
    r, k, _ = _iki(yol, tanik)
    assert ["tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler] == [True], r.mudahaleler
    assert k.sifirlanmis and k.taniksiz == [1, 2, 3]
    _onayla(yol, tanik)                              # gordum, inceledim
    for _ in range(2):                               # iki duz yeniden baslatma
        with _Yazici(yol, tanik) as y:
            y.yaz("sonraki")
    r, k, t = _iki(yol, tanik)
    assert r.temiz, [m.aciklama for m in r.mudahaleler]
    assert k.uyusuyor and t.saglam
    dogumlar = [s for s in _satirlar(yol) if f"| {ac.TANIK_BASLANGICI} |" in s]
    assert len(dogumlar) == 2 and "ilk_sira=4 |" in dogumlar[1], dogumlar


def test_calisirken_silinen_tanik_hemen_bildiriliyor_ve_yeniden_doguyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        tanik.sifirla()                              # bot calisirken DROP TABLE
        y.yaz("iki")                                 # tablo yeniden kurulur: alarm HEMEN
        calisirken = _satirlar(yol)                  # bot hala calisiyor
    assert any("tanık sıfırlanmış" in s for s in calisirken), calisirken[-3:]
    r = _dosya(yol)
    assert any("tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler), r.mudahaleler
    _onayla(yol, tanik)
    with _Yazici(yol, tanik) as y:
        y.yaz("sonraki")
    r, k, _ = _iki(yol, tanik)
    assert r.temiz, [m.aciklama for m in r.mudahaleler]
    assert k.uyusuyor


def test_dogum_kaydi_rotasyonla_gitse_de_tanigin_silinmesi_yakalaniyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    dosyalar = _dondur(yol, tanik, yedek=1)
    assert not any(f"| {ac.TANIK_BASLANGICI} |" in s for d in dosyalar for s in _satirlar(d)), \
        "dogum kaydi hala dosyalarda: test bir sey sinamiyor"
    tanik.sifirla()
    tanik.sema_kur()
    with _DonenYazici(yol, tanik, backupCount=1) as y:
        y.yaz("sonraki")
    r = _dosya(yol)
    assert any("tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler), r.mudahaleler


# ── 4. Eski bicimli onay notu ────────────────────────────────────────────────

def test_eski_onay_yeni_onaydan_sonra_uyari_degil_bilgi(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    s = _satirlar(yol)
    _yaz_satirlar(yol, s[:2] + s[3:])                # 'iki' bot dururken silindi
    with _Yazici(yol, tanik) as y:                   # eski surumun onayi: kimlik listesi yok
        y.lg.info(f"AUDIT | {ac.ONAY_OLAYI} | user=***456 | kapsam=4 bulgu=2")
    r = _dosya(yol)
    assert "⚠️ Eski biçimli onay (sıra 5)" in ac.rapor_metni(r)

    _onayla(yol, tanik)
    r, k, t = _iki(yol, tanik)
    for metin in (ac.rapor_metni(r), ac.karsilastirma_metni(k, r, t)):
        assert "⚠️ Eski biçimli onay" not in metin, metin
        assert "Eski biçimli onay (sıra 5) yok sayıldı" in metin, metin


# ── 5. Kelime tekrari ────────────────────────────────────────────────────────

def test_sifirlanmis_tanik_satirinda_kelime_tekrari_yok(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    tanik.sifirla()
    tanik.sema_kur()
    with _Yazici(yol, tanik) as y:
        y.yaz("uc")
    _, k, t = _iki(yol, tanik)
    assert k.sifirlanmis
    satir = ac.tanik_ozet_satiri(k, t)
    assert satir.startswith("tanık sıfırlanmış: 3 halka tanıkta yok (sıra 1–3)"), satir
    assert "tanık: tanık" not in satir


# ── 6. Yazicinin kendi kayitlari beklemez ────────────────────────────────────

def test_kesinti_tamamlaninca_kaydi_hemen_yaziliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        tanik.kapali = True
        y.yaz("iki")                                 # tanik kapali: bellekte bekler
        tanik.kapali = False
        y.yaz("uc")                                  # tanik dondu: bekleyen yazilir
        son = _satirlar(yol)[-1]
    assert f"| {ac.TANIK_TAMAMLAMA} |" in son, son


def test_kesinti_bot_kapanirken_tamamlanirsa_kaydi_yine_yaziliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        tanik.kapali = True
        y.yaz("iki")
        tanik.kapali = False                         # tanik dondu; bot bir sey yazmadan duruyor
    son = _satirlar(yol)[-1]
    assert f"| {ac.TANIK_TAMAMLAMA} |" in son, son
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor


# ── Mac'teki dogrulayici ve onay ─────────────────────────────────────────────

def test_mac_dogrulayicisi_onayin_dosyanin_kendi_beyani_oldugunu_soyluyor(tmp_path, capsys):
    """Dosya tek basina sahte bir onayi ayirt edemez: bunu acikca soylemeli."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    s = _satirlar(yol)
    _yaz_satirlar(yol, s[:2] + s[3:])
    _onayla(yol, tanik)
    assert ac.main([str(yol)]) == 0
    cikti = capsys.readouterr().out
    assert "Onaylanmış geçmiş" in cikti
    assert "dosya tek başına söyleyemez, tanık söyler" in cikti, cikti


# ── Bot: yedek sayisini taniga veriyor ───────────────────────────────────────

def test_bot_tanik_karsilastirmasinda_yedek_sayisini_kullaniyor(tanikli, monkeypatch):
    v, _tanik = tanikli
    monkeypatch.setattr(v, "LOG_BACKUP_COUNT", 2)
    monkeypatch.setattr(v._audit_yazici, "maxBytes", 1200)
    monkeypatch.setattr(v._audit_yazici, "backupCount", 2)
    for i in range(40):
        v.audit_event(f"olay_{i:02d}", "123456", "x")
    assert len(ac.dosyalari_sirala(v.AUDIT_LOG_FILE)) == 3, "rotasyon tetiklenmedi"
    saglik = v.build_denetim_izi_health()
    assert saglik.status == "ok", saglik.details

    Path(f"{v.AUDIT_LOG_FILE}.2").write_text("", encoding="utf-8")   # icerik gitti, sayi ayni
    k, _, _, _ = v.denetim_tanigi_karsilastirmasi()
    assert k.dosyada_yok, "tanik, rotasyonla gitmemesi gereken halkalari gizledi"
    assert v.build_denetim_izi_health().status == "warn"


# ── Son kontrol: incelemenin yetistiremedigi mesru islemler ve bir sinir ─────

def test_SINIR_en_eski_yedegi_erken_silmek_bir_sonraki_rotasyondan_sonra_gorunmez(tmp_path):
    """Bu test GECMELI. En eski yedek, bir sonraki rotasyonda zaten silinecek
    dosyadir. Onu erken silmeyi tanik o rotasyona kadar gorur (yukaridaki
    test; botun her acilistaki denetimi de). Rotasyondan sonra diskteki durum
    mesru rotasyonunkiyle AYNIDIR: ayirt edilecek bir sey kalmaz. Tanik o
    satirlari yine de saklar (ucuncu tur inceleme, 5 Ekim)."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _dondur(yol, tanik)
    Path(f"{yol}.2").write_text("", encoding="utf-8")
    ilk = _satirlar(yol)[0]
    with _DonenYazici(yol, tanik) as y:
        for i in range(20):                          # tam bir rotasyon daha
            y.yaz(f"sonra_{i}")
            if _satirlar(yol)[0] != ilk:
                break
    assert _satirlar(yol)[0] != ilk, "rotasyon olmadi: test bir sey sinamiyor"
    r = _dosya(yol)
    k, _ = ac.iki_tanigi_karsilastir(r, tanik.halkalar(), yedek_sayisi=2)
    assert r.temiz and k.uyusuyor, "Bu artik yakalaniyorsa bu testi guncelle"


def test_donmus_dosyalarin_hepsi_silinirse_ana_dosyanin_donme_kaydi_yetmiyor(tmp_path, capsys):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    for d in _dondur(yol, tanik)[:-1]:
        Path(d).unlink()                             # bot dururken: butun yedekler gitti
    r = _dosya(yol)
    assert [x.tur for x in r.sorunlar] == ["eksik"], r.sorunlar
    assert "dönmüş dosya yok" in r.sorunlar[0].aciklama
    assert ac.main([str(yol)]) == 1


def test_yedek_sayisi_sifirsa_donme_kaydi_yazilmiyor(tmp_path):
    """RotatingFileHandler gibi: backupCount=0 ise donme yok -- her yazimda
    bir donme kaydi birikmemeli."""
    yol = tmp_path / "iz.log"
    with _DonenYazici(yol, None, maxBytes=300, backupCount=0) as y:
        y.yaz(*[f"olay_{i}" for i in range(10)])
    assert not any(f"| {DONME} |" in s for s in _satirlar(yol))
    assert _dosya(yol).temiz and len(ac.dosyalari_sirala(yol)) == 1


def test_art_arda_iki_sifirlama_ikisi_de_bildiriliyor_sonra_sessiz(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
    for tur in range(2):
        tanik.sifirla()
        tanik.sema_kur()
        with _Yazici(yol, tanik) as y:
            y.yaz(f"acilis_{tur}")
        r = _dosya(yol)
        assert ["tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler] == [True], \
            (tur, [m.aciklama for m in r.mudahaleler])
        _onayla(yol, tanik)
    with _Yazici(yol, tanik) as y:
        y.yaz("sonraki")
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor
    assert sum(f"| {ac.TANIK_BASLANGICI} |" in s for s in _satirlar(yol)) == 3


def test_tanik_hem_silinmis_hem_acilista_kapaliysa_donunce_bildiriliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    tanik.sifirla()
    tanik.sema_kur()
    tanik.kapali = True                              # veritabani acilista hazir degil
    with _Yazici(yol, tanik) as y:
        y.yaz("uc")                                  # yalnizca dosyada; hizalama ertelendi
        tanik.kapali = False
        y.yaz("dort")                                # tanik dondu: hizalama + alarm
    r = _dosya(yol)
    assert any("tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler), r.mudahaleler
    dogum = [s for s in _satirlar(yol) if f"| {ac.TANIK_BASLANGICI} |" in s][-1]
    assert f"ilk_sira={min(tanik.kayit)} |" in dogum, (dogum, min(tanik.kayit))
    _onayla(yol, tanik)
    with _Yazici(yol, tanik) as y:
        y.yaz("bes")
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor


def test_tanik_kapaliyken_donen_dosyalar_tanik_donunce_eksiksiz(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _DonenYazici(yol, tanik, backupCount=5) as y:
        y.yaz(*[f"once_{i:02d}" for i in range(5)])
        tanik.kapali = True
        y.yaz(*[f"kesinti_{i:02d}" for i in range(20)])     # birkac rotasyon, tanik kapali
        tanik.kapali = False
        y.yaz("dondu")
    donmeler = [s for s, (_o, g) in tanik.kayit.items() if f"| {DONME} |" in g]
    assert len(donmeler) >= 2, "tanik kapaliyken donme olmadi: test bir sey sinamiyor"
    r = _dosya(yol)
    k, t = ac.iki_tanigi_karsilastir(r, tanik.halkalar(), yedek_sayisi=5)
    assert r.temiz and k.uyusuyor and t.saglam, (r.sorunlar, k)


def test_kapanista_yazilan_kayit_dosyayi_dondurse_de_zincir_tutarli(tmp_path):
    kapanista_dondu = False
    for n in range(1, 10):
        yol, tanik = tmp_path / f"iz{n}.log", _SahteTanik()
        with _DonenYazici(yol, tanik, backupCount=3) as y:
            y.yaz(*[f"olay_{i}" for i in range(n)])
            tanik.kapali = True
            y.yaz("kesinti")
            tanik.kapali = False                     # kapanista: kuyruk + 'tamamlandi' kaydi
        s = _satirlar(yol)
        assert f"| {ac.TANIK_TAMAMLAMA} |" in s[-1], (n, s[-1])
        kapanista_dondu |= len(s) == 2 and f"| {DONME} |" in s[0]
        r = _dosya(yol)
        k, t = ac.iki_tanigi_karsilastir(r, tanik.halkalar(), yedek_sayisi=3)
        assert r.temiz and k.uyusuyor and t.saglam, (n, r.sorunlar, k)
    assert kapanista_dondu, "kapanista hic donme olmadi: test bir sey sinamiyor"
