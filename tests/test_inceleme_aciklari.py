"""Bagimsiz incelemenin buldugu dort acik (4 Ekim 2026).

Faz 4 ve Faz 5 kendi testleriyle yesildi; o testler, yazarin aklina gelen
saldirilari sinaniyordu. Videonun metni bagimsiz bir inceleyiciye
dogrulatilirken inceleyici kodu da kirdi. Buradaki her test bir saldiriyi
birebir kuruyor; duzeltmeden ONCE hepsi kirmiziydi.

  1. Tanik tek komutla sifirlanabiliyordu (DROP TABLE). Bot bos taniği
     "ilk kurulum" saniyordu; dosyanin sonu da kesilince her sey yesil.
  2. Onay bulgulari degil bir sira ARALIGINI onayliyordu: onaydan sonra
     araliktaki eski bir satira dokunmak sessizce "onayli gecmis" oluyordu.
  3. Dosyanin BASINDAN silinen satirlar "rotasyonla silinmis olabilir"
     sayiliyordu -- ortada hic donmus dosya yokken bile.
  4. Tanik kapaliyken yazilan halkalar taniga sonradan yazilmiyordu; bot
     dururken sondan silinirlerse ne dosya ne tanik goruyordu.

Ve bir gizlilik kaydi: gercek Telegram kimligi bir test girdisine girmisti.
"""
import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import audit_chain as ac  # noqa: E402
from test_ikinci_tanik import _SahteTanik, _Yazici, _satirlar, _yaz_satirlar  # noqa: E402
from test_iz_onayi import (  # noqa: E402,F401  (tanikli: pytest fikstur)
    _bot_dururken_sondan_sil, _guncelleme, _kurcalanmis_iz, _onay_dugmesi, tanikli,
)


def _dosya(yol, **kw):
    return ac.dogrula_dosyalar(ac.dosyalari_sirala(yol), **kw)


def _iki(yol, tanik):
    r = _dosya(yol)
    k, t = ac.iki_tanigi_karsilastir(r, tanik.halkalar())
    return r, k, t


def _zincir(n, ilk_onceki=ac.BASLANGIC):
    """Gercek bir zincir: 'AUDIT | olay_i | user=***456 | ayrinti | sira=i | ozet=...'."""
    satirlar, onceki = [], ilk_onceki
    for sira in range(1, n + 1):
        govde = f"AUDIT | olay_{sira} | user=***456 | ayrinti | sira={sira}"
        onceki = ac.ozet(onceki, govde)
        satirlar.append(f"{govde} | ozet={onceki}")
    return satirlar


def _onayla(yol, tanik, *sonra, kapsam=None, sadece=None):
    """/iz_onayla'nin yaptigi: acik bulgularin kimlikleriyle onay satiri."""
    r, k, t = _iki(yol, tanik)
    _, kimlikler = ac.acik_bulgular(r, k, t)
    if sadece is not None:
        kimlikler = [kimlikler[i] for i in sadece]
    ayrinti = ac.onay_ayrintisi(r.son_sira if kapsam is None else kapsam, kimlikler)
    with _Yazici(yol, tanik) as y:
        y.lg.info(f"AUDIT | {ac.ONAY_OLAYI} | user=***456 | {ayrinti}")
        y.yaz(*sonra)


# ── 1. Tanik sifirlanirsa ────────────────────────────────────────────────────

def test_ilk_kurulumda_tanigin_dogumu_yaziliyor_alarm_yok(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    s = _satirlar(yol)
    assert ac.TANIK_BASLANGICI in s[0] and "ilk_sira=1 |" in s[0]
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and r.tanik_baslangici == 1
    assert k.uyusuyor and not k.sifirlanmis and k.eslesen == 3


def test_ilk_kurulumda_tablo_yoksa_da_alarm_yok(tmp_path):
    """Gercek veritabani testinin yakaladigi hata: veritabani acilista gec
    kalirsa sema kurulamaz; tablo ilk YAZIMDA kurulur ('kuruldu'). Bu, ilk
    kurulumda olagan -- 'tanık sıfırlanmış' alarmi yanlis olurdu."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    tanik.tablo_yok = True
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and not r.mudahaleler, r.mudahaleler
    assert k.uyusuyor and k.eslesen == 3


def test_tanik_sonradan_kurulursa_onceki_halkalar_alarm_degil(tmp_path):
    """4 Ekim 13:40'taki gibi: zincir vardi, tanik sonradan geldi."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, None) as y:
        y.yaz("bir", "iki", "uc")
    with _Yazici(yol, tanik) as y:
        y.yaz("dort")
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and r.tanik_baslangici == 4
    assert k.uyusuyor and k.tanik_oncesi == 3 and not k.sifirlanmis


def test_eski_kurulumda_tanigin_dogumu_sonradan_yaziliyor(tmp_path):
    """Bu duzeltmeden once kurulmus tanik: dosyada dogum kaydi yok."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    satirlar = _zincir(5)
    _yaz_satirlar(yol, satirlar)
    for satir in satirlar[2:]:                       # tanik sira 3'ten beri tutuyor
        govde, sira, oz = ac.halka_coz(satir)
        tanik.kayit[sira] = (oz, govde)
    with _Yazici(yol, tanik) as y:
        y.yaz("alti")
    s = _satirlar(yol)
    assert ac.TANIK_BASLANGICI in s[5] and "ilk_sira=3 |" in s[5]
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and r.tanik_baslangici == 3
    assert k.uyusuyor and k.tanik_oncesi == 2


def test_tanik_bot_dururken_silinirse_acilista_alarm(tmp_path):
    """Incelemenin saldirisi: sondan sil + DROP TABLE. Eskiden her sey yesildi."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    yedek = _satirlar(yol)
    with _Yazici(yol, tanik) as y:
        y.yaz("uc", "dort")
    _yaz_satirlar(yol, yedek)                        # bot dururken sondan sil
    tanik.sifirla()                                  # ... ve tanigi tek komutla sil
    tanik.sema_kur()                                 # acilista sema bos tabloyla geri gelir
    with _Yazici(yol, tanik) as y:
        y.yaz("bes")

    r, k, _ = _iki(yol, tanik)
    assert not r.temiz, "tanigin silinmesi ize yazilmadi"
    assert any("tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler), r.mudahaleler
    assert k.sifirlanmis and not k.uyusuyor
    assert k.taniksiz == [1, 2, 3], "eski halkalar 'tanıktan önce' sayilip gizlenmis"
    assert "tanık sıfırlanmış" in ac.tanik_ozet_satiri(k, ac.tanik_raporu(tanik.halkalar()))


def test_tanik_bot_calisirken_silinirse_alarm(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
        tanik.sifirla()                              # bot calisirken DROP TABLE
        y.yaz("uc", "dort")
    r, k, _ = _iki(yol, tanik)
    assert [m.aciklama for m in r.mudahaleler] == [
        "tanık tablosu yoktu, yeniden kuruldu: sıra 1–3 tanıkta yok; tanık sıfırlanmış"]
    assert k.sifirlanmis and k.taniksiz == [1, 2, 3]


def test_tanigin_basi_silinirse_alarm(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    del tanik.kayit[1], tanik.kayit[2]               # tetikleyici atlatilarak DELETE
    with _Yazici(yol, tanik) as y:
        y.yaz("dort")
    r, k, _ = _iki(yol, tanik)
    assert any("tanığın başından halka silinmiş" in m.aciklama for m in r.mudahaleler)
    assert k.sifirlanmis and k.taniksiz == [1, 2]


def test_sifirlanan_tanik_saglikta_ve_denetcide_kirmizi(tanikli):
    v, tanik = tanikli
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    tanik.sifirla()
    v.audit_event("sonraki", "123456", "x")
    v.audit_event("bir_sonraki", "123456", "x")       # bildirim burada ize gecer
    saglik = v.build_denetim_izi_health()
    assert saglik.status == "warn" and "tanık sıfırlanmış" in saglik.details
    sonuc = v.sovereign.audit(v.guvenlik_anlik_goruntusu())
    assert ("iz_tanigi", "kritik") in [(b.kontrol, b.onem) for b in sonuc.bulgular]


# ── 2. Onay listeyi onaylar, araligi degil ───────────────────────────────────

def test_onaydan_sonra_eski_satir_degisirse_yeniden_uyariyor(tmp_path):
    """Incelemenin saldirisi: araliktaki eski satira dokunmak onayli sayiliyordu."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik)
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor and len(r.onaylanan) == 2

    s = _satirlar(yol)
    assert "| bir |" in s[1]
    s[1] = s[1].replace("| bir |", "| BIR |")         # sira 2: onay kapsaminin icinde
    _yaz_satirlar(yol, s)

    r, k, _ = _iki(yol, tanik)
    assert not r.temiz
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("degistirilmis", 2)]
    assert len(r.onaylanan) == 2, "eski gecmis yine onayli kalmali"
    assert k.farkli == [2], "tanik da yeni farki gostermeli"


def test_onaydan_sonra_eski_satir_silinirse_yeniden_uyariyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik)
    s = _satirlar(yol)
    assert "| iki |" in s[2]
    del s[2]                                         # sira 3, onay kapsaminin icinde
    _yaz_satirlar(yol, s)

    r, k, _ = _iki(yol, tanik)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 6)]
    assert "sıra 3–5 kayıp" in r.sorunlar[0].aciklama
    assert [s for s, _ in k.dosyada_yok] == [3], "yeni kayip onayli sayilmis"
    assert sorted(s for _, s in k.onaylanan) == [4, 5]


def test_onay_yalnizca_listelenen_bulgulari_kapsiyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _kurcalanmis_iz(yol, tanik)
    r, k, t = _iki(yol, tanik)
    satirlar, kimlikler = ac.acik_bulgular(r, k, t)
    assert len(kimlikler) == 4 and len(set(kimlikler)) == 4
    _onayla(yol, tanik, sadece=[0, 1])               # yalnizca dosyanin iki bulgusu

    r, k, _ = _iki(yol, tanik)
    assert r.temiz
    assert [s for s, _ in k.dosyada_yok] == [4, 5], "listede olmayan onaylanmis"


def test_eski_bicim_onay_artik_gecmiyor_ve_soyleniyor(tmp_path, capsys):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    with _Yazici(yol, tanik) as y:
        y.lg.info(f"AUDIT | {ac.ONAY_OLAYI} | user=***456 | kapsam={once.son_sira} bulgu=4")
    r = _dosya(yol)
    assert not r.temiz and not r.onaylanan and r.onay is None
    assert [sira for sira, _ in r.eski_onaylar] == [once.son_sira + 1]
    assert ac.main([str(yol)]) == 1
    assert "Eski biçimli onay" in capsys.readouterr().out


def test_onaylar_birikiyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, "on")
    yedek = _satirlar(yol)
    with _Yazici(yol, tanik) as y:
        y.yaz("onbir", "oniki")
    _yaz_satirlar(yol, yedek)                        # ikinci kurcalama
    with _Yazici(yol, tanik) as y:
        y.yaz("onuc")
    r, k, t = _iki(yol, tanik)
    assert len(ac.acik_bulgular(r, k, t)[1]) == 4, "yalnizca YENI bulgular acik olmali"
    _onayla(yol, tanik)

    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor
    assert len(r.onaylanan) == 4 and len(k.onaylanan) == 4 and len(r.onaylar) == 2


def test_bot_onayi_kimlik_listesiyle_yaziyor(tanikli):
    """Uctan uca: /iz_onayla -> Onayla -> eski satira dokunmak yine uyarir."""
    v, tanik = tanikli
    _bot_dururken_sondan_sil(v, tanik)
    update, context = _guncelleme(), SimpleNamespace(args=[], user_data={})
    asyncio.run(v.cmd_iz_onayla(update, context))
    assert "Yalnızca bu 4 bulgu onaylanır" in update.message.gonderilenler[-1][0]
    _onay_dugmesi(v, context)
    assert v.build_denetim_izi_health().status == "ok"
    onay = [s for s in _satirlar(v.AUDIT_LOG_FILE) if f"| {ac.ONAY_OLAYI} |" in s][-1]
    assert re.search(r"kapsam=\d+ bulgu=4 onay=[0-9a-f]{16}(,[0-9a-f]{16}){3} \|", onay), onay

    s = _satirlar(v.AUDIT_LOG_FILE)
    i = next(n for n, satir in enumerate(s) if "| olay_0 |" in satir)
    s[i] = s[i].replace("| x |", "| X |")             # onaylanan araliktaki eski bir satir
    _yaz_satirlar(v.AUDIT_LOG_FILE, s)
    assert v.build_denetim_izi_health().status == "warn"


# ── 3. Bastan silmek rotasyon degildir ───────────────────────────────────────

def test_dosyanin_basi_silinirse_rotasyon_sayilmiyor(tmp_path, capsys):
    yol = tmp_path / "iz.log"
    _yaz_satirlar(yol, _zincir(5)[2:])               # sira 1-2 bot dururken silindi
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 3)]
    assert "dönmüş dosya yok" in r.sorunlar[0].aciklama
    assert ac.main([str(yol)]) == 1
    assert "rotasyonla" not in capsys.readouterr().out


def test_zincirden_onceki_satirlar_yerindeyken_bas_eksigi_rotasyon_degil(tmp_path):
    yol = tmp_path / "iz.log"
    Path(f"{yol}.1").write_text("AUDIT | daha_eski | user=***456 | x\n", encoding="utf-8")
    _yaz_satirlar(yol, ["AUDIT | eski | user=***456 | zincirden once"] + _zincir(5)[2:])
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 3)]
    assert "zincirden önceki satırlar yerinde" in r.sorunlar[0].aciklama


def test_donmus_dosya_sayisi_bas_eksigini_rotasyon_yapmiyor(tmp_path):
    """Ilk duzeltme donmus dosyalari SAYIYORDU; ikinci inceleme bunu bes bos
    dosyayla kirdi (bkz. test_inceleme_aciklari_2). Ilk halka gecerli bir
    donme kaydi degilse, kac donmus dosya olursa olsun bas eksikligi silmedir."""
    yol, z = tmp_path / "iz.log", _zincir(6)
    Path(f"{yol}.1").write_text("\n".join(z[2:4]) + "\n", encoding="utf-8")
    _yaz_satirlar(yol, z[4:])
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 3)]
    assert "geçerli bir dönme kaydı değil" in r.sorunlar[0].aciklama


def test_bot_bas_eksigini_donme_kaydi_olmadan_rotasyon_saymiyor(vasi_module):
    """Botun kendi raporu da ayni kurala uyuyor: donmus dosya var, ama
    dosyalar bir donme kaydiyla baslamiyor."""
    v, z = vasi_module, _zincir(6)
    Path(f"{v.AUDIT_LOG_FILE}.1").write_text("\n".join(z[1:3]) + "\n", encoding="utf-8")
    _yaz_satirlar(v.AUDIT_LOG_FILE, z[3:])
    r = v.denetim_zinciri_raporu()
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 2)]


def test_tanikta_bastan_silinenler_dosyada_yok_sayiliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    _yaz_satirlar(yol, _satirlar(yol)[2:])           # dogum kaydi ve 'bir' gitti
    r, k, _ = _iki(yol, tanik)
    assert not r.bas_rotasyon
    assert [s for s, _ in k.dosyada_yok] == [1, 2] and k.dosya_oncesi == 0


# ── 4. Tanik kesintisinde yazilanlar ─────────────────────────────────────────

def test_kesintide_yazilanlar_tanik_donunce_ona_yaziliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")                                 # 1 dogum, 2 bir
        tanik.kapali = True
        y.yaz("iki", "uc")                           # 3, 4: yalnizca dosyada
        tanik.kapali = False
        y.yaz("dort", "bes")                         # 5 (3-4 once yazilir), 6 kayit, 7
    assert sorted(tanik.kayit) == [1, 2, 3, 4, 5, 6, 7]
    s = _satirlar(yol)
    assert ac.TANIK_TAMAMLAMA in s[5] and "kesinti: sıra 3–4 tanığa sonradan yazıldı" in s[5]
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor


def test_kesintide_yazilanlar_bot_kapanirken_de_taniga_yaziliyor(tmp_path):
    """Incelemenin saldirisi: tanik dondu, bot bir sey yazmadan durduruldu,
    kesintide yazilanlar sondan silindi. Eskiden ne dosya ne tanik goruyordu."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        tanik.kapali = True
        y.yaz("iki", "uc")
        tanik.kapali = False                         # tanik dondu; bot duruyor
    # 3-4 kapanirken taniga yazildi; 5, bunun kaydi (denetim_tanigi_tamamlandi).
    assert sorted(tanik.kayit) == [1, 2, 3, 4, 5]
    _yaz_satirlar(yol, _satirlar(yol)[:2])           # bot dururken: kesintide yazilanlar silindi
    r, k, _ = _iki(yol, tanik)
    assert [s for s, _ in k.dosyada_yok] == [3, 4, 5]


def test_SINIR_tanik_kapaliyken_bot_da_durursa_aradakilerin_tek_tanigi_dosya(tmp_path):
    """Bu test GECMELI: tanik HIC gormediyse, gorduklerini soyleyemez.

    Tanik kapaliyken yazilan halkalar, bot da tanik donmeden durursa,
    yalnizca dosyada kalir. Bot dururken silinirlerse iki kopya yine
    uyusur. Ikinci tanigin dogasi: tanik ancak gordugune taniklik eder.
    """
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        tanik.kapali = True
        y.yaz("iki", "uc")                           # tanik hala kapaliyken bot duruyor
    _yaz_satirlar(yol, _satirlar(yol)[:2])
    tanik.kapali = False
    r, k, _ = _iki(yol, tanik)
    assert r.temiz and k.uyusuyor


def test_acilista_dosyadaki_fazlalik_taniga_kendiliginden_yazilmiyor(tmp_path):
    """Bot dururken dosyanin sonuna ozeti DOGRU hesaplanmis bir satir eklenebilir
    (anahtar yok). Yazici bunu 'tamamlama' diye taniga yazsaydi sahte satir
    tanikli olurdu -- sahte bir onay da."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
    s = _satirlar(yol)
    govde = "AUDIT | sahte | user=***456 | x | sira=3"
    s.append(f"{govde} | ozet={ac.ozet(ac.halka_coz(s[-1])[2], govde)}")
    _yaz_satirlar(yol, s)
    assert _dosya(yol).temiz, "dosya tek basina kandiriliyor"
    with _Yazici(yol, tanik) as y:
        y.yaz("iki")
    assert 3 not in tanik.kayit
    r, k, _ = _iki(yol, tanik)
    assert k.taniksiz == [3]


# ── 5. Gizlilik ──────────────────────────────────────────────────────────────

def test_depoda_gercek_bir_telegram_kimligi_yok():
    """Gercek kimlik bir kez bir test girdisine girdi. Depo herkese acik.

    On ve daha uzun haneli her sayi supheli. Bulunan sayinin yalnizca ilk
    uc hanesi yazilir: test ciktisi da bir yere yapistirilabilir.
    """
    desen = re.compile(r"(?<![0-9A-Fa-f.])\d{10,}(?![0-9A-Fa-f.])")
    izinli = {"1234567890"}
    bulunan = []
    dosyalar = [*KOK.glob("*.py"), *KOK.glob("*.sh"), *KOK.glob("*.md"),
                *(KOK / "tests").glob("*.py")]
    for yol in dosyalar:
        for no, satir in enumerate(yol.read_text(encoding="utf-8", errors="replace")
                                   .splitlines(), 1):
            for m in desen.finditer(satir):
                if m.group() not in izinli:
                    bulunan.append(f"{yol.name}:{no}: {m.group()[:3]}…")
    assert not bulunan, bulunan
