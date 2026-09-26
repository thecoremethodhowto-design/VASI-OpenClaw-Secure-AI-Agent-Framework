"""Sovereign: sapma denetcisi.

Bu testler hicbir servis gerektirmez -- denetci zaten hicbir yerel
modulu import etmiyor, sabitleri parametre olarak aliyor.
"""
import inspect
from pathlib import Path

import pytest


# ── Cerceve: tur ve durdurma kurali ──────────────────────────────────────────

def _bulgu(sov, **kw):
    varsayilan = {
        "kontrol": "test", "tur": sov.DETERMINISTIK, "onem": sov.KRITIK,
        "yetenek": sov.YETENEK_RAG, "mesaj": "x",
    }
    return sov.Bulgu(**{**varsayilan, **kw})


def test_sezgisel_bulgu_durduramaz(vasi_module):
    """KRITIK: bir TAHMIN bir yetenegi kapatamaz.

    Sezgisel bir kontrol durdurursa, yanlis alarm operatoru kendi
    sisteminden kilitler. Ve bir-iki yanlis alarmdan sonra insanlar
    kontrolu kapatir. Kapali bir kontrol, olmayan bir kontroldur.
    """
    sov = vasi_module.sovereign
    assert _bulgu(sov, tur=sov.SEZGISEL).durdurabilir is False


def test_uyari_seviyesi_durduramaz(vasi_module):
    """Geri alinabilir bir sorun icin durdurmaya degmez."""
    sov = vasi_module.sovereign
    assert _bulgu(sov, onem=sov.UYARI).durdurabilir is False
    assert _bulgu(sov, onem=sov.BILGI).durdurabilir is False


def test_yeteneksiz_bulgu_durduramaz(vasi_module):
    sov = vasi_module.sovereign
    assert _bulgu(sov, yetenek=sov.YETENEK_YOK).durdurabilir is False


def test_deterministik_kritik_bulgu_durdurabilir(vasi_module):
    """Uc kosul da saglanirsa durdurma mumkun."""
    sov = vasi_module.sovereign
    assert _bulgu(sov).durdurabilir is True


def test_tum_yetenekler_tanimli(vasi_module):
    """Bir kontrol tanimsiz bir yetenek gosteremez.

    Satirdaki HER YETENEK_* adini dogrular. Once yalnizca ilk virgule
    kadar okuyordu; kosullu bir ifade (A if ... else B) yazildiginda
    ad yerine ifadenin tamamini okumaya calisti. Satirin tamamini
    taramak hem daha saglam hem daha genis: iki kollu bir secimin
    ikisini birden dogruluyor.
    """
    import re
    sov = vasi_module.sovereign
    for k in sov.KONTROLLER:
        for satir in inspect.getsource(k).split("\n"):
            if "yetenek=" not in satir:
                continue
            adlar = re.findall(r"\bYETENEK_\w+\b", satir)
            assert adlar, f"{k.__name__}: yetenek= satirinda sabit yok: {satir.strip()}"
            for ad in adlar:
                assert getattr(sov, ad) in sov.GECERLI_YETENEKLER, f"{k.__name__}: {ad}"


def test_sezgisel_kontrol_asla_kritik_degil(vasi_module):
    """Kaynak kod garantisi: SEZGISEL ile KRITIK ayni Bulgu'da olamaz."""
    sov = vasi_module.sovereign
    for k in sov.KONTROLLER:
        kaynak = inspect.getsource(k)
        if "SEZGISEL" not in kaynak:
            continue
        # SEZGISEL uretebilen bir kontrol KRITIK uretmemeli
        assert "onem=KRITIK" not in kaynak, (
            f"{k.__name__} hem sezgisel hem kritik bulgu uretebiliyor"
        )


# ── Kontroller: politika-kod uyumu ───────────────────────────────────────────

def test_politikadaki_yeni_sinif_yakalaniyor(vasi_module):
    """Politikaya sinif eklenip kod guncellenmezse yakalanmali.

    Yeni sinif oncelik listesinin sonuna duser ve gevsek siniflarin
    arkasinda kalir -- tam olarak RAG fazinda bulunan hatanin sekli.
    """
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_politika_kod_uyumu({
        "sinif_onceligi": ("SECRET", "PRIVATE", "PROJECT", "PUBLIC"),
        "politika_siniflari": {"SECRET": {}, "PUBLIC": {}, "ARSIV": {}},
    })
    assert len(bulgular) == 1
    assert "ARSIV" in bulgular[0].mesaj
    assert bulgular[0].durdurabilir is True


def test_uyumlu_politika_temiz(vasi_module):
    sov = vasi_module.sovereign
    assert sov.kontrol_politika_kod_uyumu({
        "sinif_onceligi": ("SECRET", "PUBLIC"),
        "politika_siniflari": {"SECRET": {}, "PUBLIC": {}},
    }) == []


# ── Kontroller: arac listesi ─────────────────────────────────────────────────

def test_izinsiz_arac_sunumu_kritik(vasi_module):
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_arac_listesi({
        "izinli_araclar": {"skill_get_time"},
        "sunulan_araclar": {"skill_get_time", "skill_shell"},
    })
    assert len(bulgular) == 1
    assert bulgular[0].onem == sov.KRITIK
    assert bulgular[0].yetenek == sov.YETENEK_ARACLAR
    assert "skill_shell" in bulgular[0].mesaj


def test_olu_izin_uyari(vasi_module):
    """Kullanilmayan izin guvenlik acigi degil, ama saldiri yuzeyi."""
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_arac_listesi({
        "izinli_araclar": {"skill_get_time", "skill_eski"},
        "sunulan_araclar": {"skill_get_time"},
    })
    assert len(bulgular) == 1
    assert bulgular[0].onem == sov.UYARI
    assert bulgular[0].durdurabilir is False


# ── Kontroller: hafiza kaynak filtresi ───────────────────────────────────────

def test_guvenilmeyen_kaynak_prompta_girerse_kritik(vasi_module):
    """MITRE'nin OpenClaw bulgusu: bellek kaynagina gore ayrismiyordu."""
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_hafiza_kaynak_filtresi({
        "prompta_girebilen": ("user", "web"),
        "gecerli_kaynaklar": ("user", "web", "tool"),
    })
    kritikler = [b for b in bulgular if b.onem == sov.KRITIK]
    assert len(kritikler) == 1
    assert "web" in kritikler[0].mesaj
    assert kritikler[0].yetenek == sov.YETENEK_HAFIZA


def test_yalnizca_user_temiz(vasi_module):
    sov = vasi_module.sovereign
    assert sov.kontrol_hafiza_kaynak_filtresi({
        "prompta_girebilen": ("user",),
        "gecerli_kaynaklar": ("user", "web", "tool", "model"),
    }) == []


# ── Kontroller: RAG arac yalitimi ────────────────────────────────────────────

def test_aracsiz_yolda_yurutme_yakalaniyor(vasi_module):
    """Birisi 'madem tespit ettik, calistiralim' derse."""
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_rag_arac_yalitimi({
        "aracsiz_fonksiyon_kaynagi": "denenen = [...]\n    skill_web_radar(url)\n",
    })
    assert len(bulgular) == 1
    assert bulgular[0].durdurabilir is True
    assert bulgular[0].yetenek == sov.YETENEK_RAG


def test_temiz_aracsiz_yol_sorun_degil(vasi_module):
    sov = vasi_module.sovereign
    assert sov.kontrol_rag_arac_yalitimi({
        "aracsiz_fonksiyon_kaynagi": "denenen = [c['name'] for c in ...]",
    }) == []


# ── Kontroller: onay kapilari ────────────────────────────────────────────────

def test_onay_kapisi_eksik_komut_kritik(vasi_module):
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_onay_kapilari({
        "onay_gereken_komutlar": {"yaz", "sil"},
        "onay_isteyen_komutlar": {"yaz"},
    })
    kritikler = [b for b in bulgular if b.onem == sov.KRITIK]
    assert len(kritikler) == 1
    assert "/sil" in kritikler[0].mesaj


def test_liste_geride_kalirsa_bilgi(vasi_module):
    """TERS KONTROL: fazla koruma zararsiz, ama liste eskimis.

    Denetcinin kendi tanimini denetlemesi. Bir liste ne kadar eskirse,
    asil kontrol o kadar anlamsizlasir.
    """
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_onay_kapilari({
        "onay_gereken_komutlar": {"yaz"},
        "onay_isteyen_komutlar": {"yaz", "tarzim"},
    })
    assert len(bulgular) == 1
    assert bulgular[0].onem == sov.BILGI
    assert bulgular[0].durdurabilir is False
    assert "/tarzim" in bulgular[0].mesaj


# ── Kontroller: sezgisel hata orani ──────────────────────────────────────────

def test_yuksek_hata_orani_uyariyor_ama_durdurmuyor(vasi_module):
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_hata_orani({"komut_sayisi": 20, "hata_sayisi": 15})
    assert len(bulgular) == 1
    assert bulgular[0].tur == sov.SEZGISEL
    assert bulgular[0].durdurabilir is False


def test_az_ornekte_oran_hesaplanmiyor(vasi_module):
    """Uc komutun ikisi hatalıysa oran %66 -- ama anlamsiz."""
    sov = vasi_module.sovereign
    assert sov.kontrol_hata_orani({"komut_sayisi": 3, "hata_sayisi": 2}) == []


def test_dusuk_hata_orani_temiz(vasi_module):
    sov = vasi_module.sovereign
    assert sov.kontrol_hata_orani({"komut_sayisi": 100, "hata_sayisi": 5}) == []


# ── Dayaniklilik ─────────────────────────────────────────────────────────────

def test_eksik_alan_kontrolu_cokertmiyor(vasi_module):
    """Anlik goruntuye alan eklenirken denetci cokmemeli."""
    sov = vasi_module.sovereign
    sonuc = sov.audit({})
    assert sonuc.temiz
    assert sonuc.calisan_kontrol == len(sov.KONTROLLER)
    assert sonuc.hatali_kontrol == []


def test_bir_kontrol_patlarsa_digerleri_devam_eder(vasi_module, monkeypatch):
    """KRITIK: denetci, korudugu seyden buyuk bir risk olmamali.

    Ama sessizce de gecmez -- hatali kontrol sonuca yazilir.
    """
    sov = vasi_module.sovereign

    def patlayan(g):
        raise RuntimeError("beklenmedik")

    monkeypatch.setattr(sov, "KONTROLLER", (patlayan, sov.kontrol_arac_listesi))
    sonuc = sov.audit({
        "izinli_araclar": {"a"},
        "sunulan_araclar": {"a", "b"},
    })

    assert sonuc.hatali_kontrol == ["patlayan"]
    assert sonuc.calisan_kontrol == 1
    assert len(sonuc.bulgular) == 1, "saglam kontrol calismali"


def test_kapanacak_yetenekler_yalnizca_durdurabilirleri_topluyor(vasi_module):
    sov = vasi_module.sovereign
    sonuc = sov.DenetimSonucu(bulgular=[
        _bulgu(sov, yetenek=sov.YETENEK_RAG),
        _bulgu(sov, tur=sov.SEZGISEL, yetenek=sov.YETENEK_ARACLAR),
        _bulgu(sov, onem=sov.UYARI, yetenek=sov.YETENEK_HAFIZA),
    ])
    assert sonuc.kapanacak_yetenekler == {sov.YETENEK_RAG}


# ── Katman kurali ────────────────────────────────────────────────────────────

def test_sovereign_hicbir_yerel_modulu_import_etmiyor(vasi_module):
    """KATMAN KURALI: denetci, denetledigi seye bagimli olmamali.

    Boylece denetledigi bir moduldeki sorun denetciyi de bozamaz.
    """
    import ast
    kaynak = Path(vasi_module.sovereign.__file__).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    importlar = set()
    for d in ast.walk(agac):
        if isinstance(d, ast.Import):
            importlar.update(a.name.split(".")[0] for a in d.names)
        elif isinstance(d, ast.ImportFrom) and d.module and d.level == 0:
            importlar.add(d.module.split(".")[0])

    yerel = {"vasi", "access", "context", "execution", "decision",
             "memory", "rag", "observability"}
    assert not (importlar & yerel), (
        f"sovereign.py su yerel modulleri import ediyor: {importlar & yerel}"
    )


# ── Anlik goruntu ────────────────────────────────────────────────────────────

BEKLENEN_ALANLAR = {
    "izinli_araclar", "sunulan_araclar", "sinif_onceligi",
    "politika_siniflari", "prompta_girebilen", "gecerli_kaynaklar",
    "onay_gereken_komutlar", "onay_isteyen_komutlar",
    "aracsiz_fonksiyon_kaynagi", "komut_sayisi", "hata_sayisi",
}


def test_anlik_goruntu_tum_alanlari_iceriyor(vasi_module):
    g = vasi_module.guvenlik_anlik_goruntusu()
    eksik = BEKLENEN_ALANLAR - set(g)
    assert not eksik, f"anlik goruntude eksik alan: {eksik}"


def test_onay_isteyen_komutlar_elle_liste_kullanmiyor(vasi_module):
    """Yeni bir komut set_pending kullanirsa kendiliginden kapsanmali."""
    kaynak = inspect.getsource(vasi_module._onay_isteyen_komutlar)
    assert "set_pending(" in kaynak
    assert "inspect.getsource" in kaynak


def test_canli_sistem_denetimden_temiz_geciyor(vasi_module):
    """Suan calisan sistemde sapma olmamali.

    Bu test kirildiginda iki ihtimal var: ya kodda gercek bir sapma
    var, ya da denetcinin beklentisi eskimis. Ikisi de duzeltilmeli.
    """
    sov = vasi_module.sovereign
    sonuc = sov.audit(vasi_module.guvenlik_anlik_goruntusu())

    # BILGI seviyesi haric. Zaman sapmasi kontrolu her kod
    # degisikliginde bir kez "su alan degisti" der -- dogru davranis,
    # ama sapma degil. Testin onu hata saymasi, gelistiricinin her
    # degisiklikte sahte kirmizi gormesi demekti; ve duzenli sahte
    # kirmizi veren bir test okunmaz hale gelir.
    onemliler = [b for b in sonuc.bulgular if b.onem != sov.BILGI]
    assert not onemliler, sov.format_report(sonuc)
    assert sonuc.hatali_kontrol == []


# ── /denetle komutu ──────────────────────────────────────────────────────────

def test_denetle_komutu_kayitli(vasi_module):
    assert inspect.iscoroutinefunction(vasi_module.cmd_denetle)
    assert "/denetle" in vasi_module.HELP_TEXT


def test_denetle_denetim_izi_birakiyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_denetle)
    assert "audit_event(" in kaynak
    assert "sovereign_audit" in kaynak


def test_denetle_anlik_goruntu_hatasini_yakaliyor(vasi_module):
    """Goruntu alinamazsa komut cokmemeli."""
    kaynak = inspect.getsource(vasi_module.cmd_denetle)
    assert "except Exception" in kaynak


# ── Rapor bicimi ─────────────────────────────────────────────────────────────

def test_temiz_rapor_kontrol_sayisini_soyluyor(vasi_module):
    sov = vasi_module.sovereign
    metin = sov.format_report(sov.DenetimSonucu(calisan_kontrol=7))
    assert "temiz" in metin.lower()
    assert "7" in metin


def test_rapor_durdurabilir_bulguda_yetenegi_gosteriyor(vasi_module):
    sov = vasi_module.sovereign
    metin = sov.format_report(sov.DenetimSonucu(
        bulgular=[_bulgu(sov, yetenek=sov.YETENEK_RAG)], calisan_kontrol=7,
    ))
    assert "Etkilenen yetenek" in metin
    assert sov.YETENEK_RAG in metin


def test_rapor_hatali_kontrolu_gizlemiyor(vasi_module):
    sov = vasi_module.sovereign
    metin = sov.format_report(sov.DenetimSonucu(
        calisan_kontrol=6, hatali_kontrol=["kontrol_x"],
    ))
    assert "kontrol_x" in metin


# ══════════════════════════════════════════════════════════════════════════════
# FAZ 2 — YETENEK KAPISI
# ══════════════════════════════════════════════════════════════════════════════

from datetime import datetime, timedelta, timezone


def _sonuc(sov, *bulgular):
    return sov.DenetimSonucu(bulgular=list(bulgular), calisan_kontrol=len(sov.KONTROLLER))


def _simdi():
    return datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


# ── Kapatma ──────────────────────────────────────────────────────────────────

def test_durdurabilir_bulgu_yetenegi_kapatiyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    yeni = kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    assert yeni == {sov.YETENEK_RAG}
    assert kapi.acik(sov.YETENEK_RAG) is False
    assert kapi.acik(sov.YETENEK_ARACLAR) is True


def test_durduramayan_bulgu_hicbir_seyi_kapatmiyor(vasi_module):
    """Sezgisel ya da uyari seviyesi bir bulgu yetenek kapatmaz."""
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(
        sov,
        _bulgu(sov, tur=sov.SEZGISEL),
        _bulgu(sov, onem=sov.UYARI),
        _bulgu(sov, yetenek=sov.YETENEK_YOK),
    ))
    assert kapi.kapali == {}
    assert kapi.acik(sov.YETENEK_RAG) is True


def test_temiz_denetim_kapali_yetenegi_geri_aciyor(vasi_module):
    """Sapma duzeltilince yetenek kendiliginden acilmali.

    Eski bir bulgu, duzeltildikten sonra yetenegi kapali tutmaya
    devam edemez. Denetim tek yetkilidir.
    """
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    assert kapi.acik(sov.YETENEK_RAG) is False

    kapi.uygula(_sonuc(sov))  # temiz
    assert kapi.acik(sov.YETENEK_RAG) is True
    assert kapi.kapali == {}


def test_yeni_kapanan_yalnizca_yeni_olanlari_dondurur(vasi_module):
    """Ayni bulgu iki kez denetlenirse ikinci sefer "yeni" sayilmaz."""
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    s = _sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG))
    assert kapi.uygula(s) == {sov.YETENEK_RAG}
    assert kapi.uygula(s) == set()


def test_neden_kapali_bulgu_mesajini_tasiyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, kontrol="politika_kod_uyumu", mesaj="INTERNAL")))
    gerekce = kapi.neden_kapali(sov.YETENEK_RAG)
    assert "politika_kod_uyumu" in gerekce and "INTERNAL" in gerekce
    assert kapi.neden_kapali(sov.YETENEK_ARACLAR) is None


# ── Gecersiz kilma ───────────────────────────────────────────────────────────

def test_gecersiz_kilma_yetenegi_geri_aciyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())
    assert kapi.acik(sov.YETENEK_RAG, simdi=_simdi()) is True


def test_gecersiz_kilma_suresi_dolunca_yetenek_yeniden_kapaniyor(vasi_module):
    """EN ONEMLI TEST: suresiz gecersiz kilma, kontrolu silmektir.

    Sure dolunca yetenek kendiliginden kapanmali ve operator asil
    sorunu cozmek zorunda kalmali.
    """
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())

    hemen_once = _simdi() + timedelta(seconds=1799)
    assert kapi.acik(sov.YETENEK_RAG, simdi=hemen_once) is True

    hemen_sonra = _simdi() + timedelta(seconds=1801)
    assert kapi.acik(sov.YETENEK_RAG, simdi=hemen_sonra) is False


def test_suresi_dolan_gecersiz_kilma_kaydi_temizleniyor(vasi_module):
    """Durum raporu suresi dolmus bir kilmayi "aktif" gostermemeli."""
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 60, simdi=_simdi())
    kapi.acik(sov.YETENEK_RAG, simdi=_simdi() + timedelta(seconds=120))
    assert sov.YETENEK_RAG not in kapi.gecersiz_kilmalar


def test_gecersiz_kilma_yalnizca_adi_gecen_yetenegi_aciyor(vasi_module):
    """Toplu acma yok: her yetenek ayri karar."""
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(
        sov,
        _bulgu(sov, yetenek=sov.YETENEK_RAG),
        _bulgu(sov, yetenek=sov.YETENEK_ARACLAR),
    ))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())
    assert kapi.acik(sov.YETENEK_RAG, simdi=_simdi()) is True
    assert kapi.acik(sov.YETENEK_ARACLAR, simdi=_simdi()) is False


def test_yeni_denetim_gecersiz_kilmayi_silmiyor(vasi_module):
    """Gecersiz kilma operatorun karari; denetim onu iptal etmez."""
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    s = _sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG))
    kapi.uygula(s)
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())
    kapi.uygula(s)
    assert kapi.acik(sov.YETENEK_RAG, simdi=_simdi()) is True


def test_geri_al_gecersiz_kilmayi_kaldiriyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_RAG)))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())
    assert kapi.geri_al(sov.YETENEK_RAG) is True
    assert kapi.acik(sov.YETENEK_RAG, simdi=_simdi()) is False
    assert kapi.geri_al(sov.YETENEK_RAG) is False


# ── Durum satiri ─────────────────────────────────────────────────────────────

def test_durum_satiri_temizken_her_seyin_acik_oldugunu_soyluyor(vasi_module):
    sov = vasi_module.sovereign
    assert "açık" in sov.YetenekKapisi().durum_satiri().lower()


def test_durum_satiri_kapali_ve_kilinmisi_ayiriyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = sov.YetenekKapisi()
    kapi.uygula(_sonuc(
        sov,
        _bulgu(sov, yetenek=sov.YETENEK_RAG),
        _bulgu(sov, yetenek=sov.YETENEK_ARACLAR),
    ))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800, simdi=_simdi())
    satir = kapi.durum_satiri(simdi=_simdi())
    assert "geçersiz kılındı" in satir
    assert "araclar (kapalı)" in satir


# ── vasi.py entegrasyonu ─────────────────────────────────────────────────────

def test_yetenek_engeli_acikken_none_donduruyor(vasi_module):
    assert vasi_module.yetenek_engeli(vasi_module.sovereign.YETENEK_RAG) is None


def test_yetenek_engeli_mesaji_uc_seyi_soyluyor(vasi_module):
    """Ne kapandi, NEDEN kapandi, nasil acilir.

    "Kullanilamiyor" diyen bir mesaj operatoru kodu degistirmeye iter.
    """
    sov = vasi_module.sovereign
    kapi = vasi_module.YETENEK_KAPISI
    kapi.uygula(_sonuc(sov, _bulgu(sov, kontrol="politika_kod_uyumu", mesaj="INTERNAL")))
    try:
        mesaj = vasi_module.yetenek_engeli(sov.YETENEK_RAG)
        assert sov.YETENEK_RAG in mesaj              # ne
        assert "politika_kod_uyumu" in mesaj         # neden
        assert "/gecersiz_kil" in mesaj              # nasil
        assert "/denetle" in mesaj
    finally:
        kapi.uygula(_sonuc(sov))


def test_rag_komutlari_kapiyi_soruyor(vasi_module):
    """Uc RAG komutu da kapiyi sormali; biri unutulursa hole acilir."""
    for ad in ("cmd_bul", "cmd_sor", "cmd_indeksle"):
        kaynak = inspect.getsource(getattr(vasi_module, ad))
        assert "yetenek_engeli(sovereign.YETENEK_RAG)" in kaynak, ad


def test_hatiralar_kapi_kapaliyken_gonderilmiyor(vasi_module):
    sov = vasi_module.sovereign
    kapi = vasi_module.YETENEK_KAPISI
    kapi.uygula(_sonuc(sov, _bulgu(sov, yetenek=sov.YETENEK_HAFIZA)))
    try:
        assert vasi_module._aktif_hatiralar() == []
    finally:
        kapi.uygula(_sonuc(sov))


def test_arac_sarmalayicisi_ithal_sinirinda(vasi_module):
    """Kapi her cagri yerinde degil, ithal sinirinda olmali.

    execution.run_model_with_tools takma adla ithal edilip vasi.py'de
    ayni adla kapili bir sarmalayici tanimlaniyor. Boylece yeni bir
    cagri yeri eklense de kendiliginden kapsaniyor.
    """
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    assert "run_model_with_tools as _araclarla_calistir" in kaynak

    sarmalayici = inspect.getsource(vasi_module.run_model_with_tools)
    assert "YETENEK_KAPISI.acik(sovereign.YETENEK_ARACLAR)" in sarmalayici
    assert "run_model_without_tools" in sarmalayici


def test_hicbir_yerde_ham_arac_fonksiyonu_dogrudan_cagrilmiyor(vasi_module):
    """Sarmalayici atlanamaz: _araclarla_calistir yalnizca icinde gecer."""
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    cagrilar = kaynak.count("_araclarla_calistir(")
    assert cagrilar == 1, f"Ham fonksiyon {cagrilar} yerde cagriliyor; yalnizca sarmalayicidan cagrilmali"


def test_gecersiz_kil_komutu_onay_istiyor(vasi_module):
    """Bir guvenlik kontrolunu kapatmak, onaysiz yapilamaz."""
    kaynak = inspect.getsource(vasi_module.cmd_gecersiz_kil)
    assert "set_pending(" in kaynak
    assert "gecersiz_kil" in vasi_module.ONAY_GEREKEN_KOMUTLAR


def test_gecersiz_kil_denetciden_gecti(vasi_module):
    """Yeni komut denetcinin kendi kuralina uyuyor mu?"""
    goruntu = vasi_module.guvenlik_anlik_goruntusu()
    assert "gecersiz_kil" in goruntu["onay_gereken_komutlar"]
    assert "gecersiz_kil" in goruntu["onay_isteyen_komutlar"]


def test_baslangic_denetimi_hata_verse_de_sistem_aciliyor(vasi_module):
    """Denetci, korudugu seyden daha buyuk bir risk olmamali."""
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    blok = kaynak[kaynak.index("_baslangic_sonucu = sovereign.audit"):]
    blok = blok[:blok.index("app = Application.builder()")] if "app = Application.builder()" in blok else blok[:2000]
    assert "except Exception" in blok


def test_override_ttl_tanimli_ve_sonlu(vasi_module):
    assert 0 < vasi_module.SOVEREIGN_OVERRIDE_TTL_SECONDS <= 24 * 3600


# ── Mesajin kendisi ulasabiliyor mu ──────────────────────────────────────────

def test_hicbir_mesaj_bicimlendirme_ayristiricisindan_gecmiyor(vasi_module):
    """Uretilen degisken metin markup ayristiricisina verilmez.

    Kontrol adlari ve bulgu metinleri alt cizgi doludur:
    politika_kod_uyumu, /kod_patch, rag_allowed. Markdown
    ayristiricisi alt cizgiyi italik isareti sayar. Tek sayida alt
    cizgi kalirsa Telegram 400 doner ve mesaji HIC GONDERMEZ.

    Sonuc bir goruntu bozuklugu degil: guvenlik reddi sessizce
    kaybolur. Komut calismaz, kullanici nedenini ogrenemez -- kontrol
    kendisini anlatamaz hale gelir.
    """
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    assert "parse_mode" not in kaynak, (
        "vasi.py duz metin gonderir. Uretilen metni bicimlendirme "
        "ayristiricisindan gecirmek mesajin hic ulasmamasina yol acabilir."
    )


def test_gercekci_bir_bulgu_tek_sayida_alt_cizgi_uretebiliyor(vasi_module):
    """Yukaridaki testin NEDEN var oldugunu gosterir.

    Tehlike teorik degil: gercek bir bulgu metni tek sayida alt cizgi
    uretiyor. Markdown ile gonderilse bu mesaj teslim edilmezdi.
    """
    sov = vasi_module.sovereign
    kapi = vasi_module.YETENEK_KAPISI
    kapi.uygula(_sonuc(sov, _bulgu(
        sov, kontrol="onay_kapilari", yetenek=sov.YETENEK_RAG,
        mesaj="Kalici etkisi olup onay istemeyen komut: /kod_patch.",
    )))
    try:
        mesaj = vasi_module.yetenek_engeli(sov.YETENEK_RAG)
        assert mesaj.count("_") % 2 == 1, "ornek artik tehlikeli degil, guncelle"
        assert "*" not in mesaj
    finally:
        kapi.uygula(_sonuc(sov))


# ── Politika izin mantigi ────────────────────────────────────────────────────

def _politika(**siniflar):
    """{'SECRET': True, 'PUBLIC': False} -> tam politika sozlugu."""
    return {s: {"rag_allowed": v} for s, v in siniflar.items()}


def test_secret_indekslenebilir_yapilirsa_yakalaniyor(vasi_module):
    """Testlerin yakalayip denetcinin kacirdigi durum buydu.

    SECRET.rag_allowed true yapilinca YAPISAL hicbir sey bozulmaz:
    sinif listede, kodda taniniyor. Bozulan ANLAM -- en gizli sinif
    indekslenmeye acilmis oluyor.
    """
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_politika_izin_mantigi({
        "sinif_onceligi": ("SECRET", "PRIVATE", "PROJECT", "PUBLIC"),
        "politika_siniflari": _politika(
            SECRET=True, PRIVATE=False, PROJECT=True, PUBLIC=True
        ),
    })
    assert len(bulgular) == 1
    b = bulgular[0]
    assert b.durdurabilir
    assert b.yetenek == sov.YETENEK_RAG
    assert "SECRET" in b.mesaj and "rag_allowed" in b.mesaj


def test_dogru_politika_temiz_geciyor(vasi_module):
    """Gercek politika: SECRET/PRIVATE kapali, PROJECT/PUBLIC acik."""
    sov = vasi_module.sovereign
    assert sov.kontrol_politika_izin_mantigi({
        "sinif_onceligi": ("SECRET", "PRIVATE", "PROJECT", "PUBLIC"),
        "politika_siniflari": _politika(
            SECRET=False, PRIVATE=False, PROJECT=True, PUBLIC=True
        ),
    }) == []


def test_private_acilip_project_kapatilirsa_yakalaniyor(vasi_module):
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_politika_izin_mantigi({
        "sinif_onceligi": ("SECRET", "PRIVATE", "PROJECT", "PUBLIC"),
        "politika_siniflari": _politika(
            SECRET=False, PRIVATE=True, PROJECT=False, PUBLIC=True
        ),
    })
    assert len(bulgular) == 1
    assert "PRIVATE" in bulgular[0].mesaj and "PROJECT" in bulgular[0].mesaj


def test_izin_alani_eksikse_kapali_sayiliyor(vasi_module):
    """Tanimsiz alan False: gevsek tarafta sorun degil, sikida ihlal."""
    sov = vasi_module.sovereign
    assert sov.kontrol_politika_izin_mantigi({
        "sinif_onceligi": ("SECRET", "PUBLIC"),
        "politika_siniflari": {"SECRET": {}, "PUBLIC": {"rag_allowed": True}},
    }) == []


def test_her_izin_alani_ayri_degerlendiriliyor(vasi_module):
    """rag_allowed temizken external_share_allowed bozuksa yine bulunur."""
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_politika_izin_mantigi({
        "sinif_onceligi": ("SECRET", "PUBLIC"),
        "politika_siniflari": {
            "SECRET": {"rag_allowed": False, "external_share_allowed": True},
            "PUBLIC": {"rag_allowed": True, "external_share_allowed": False},
        },
    })
    assert len(bulgular) == 1
    assert "external_share_allowed" in bulgular[0].mesaj
    # RAG disindaki alanlar icin kapatacak bir kolumuz yok: yalnizca rapor.
    assert bulgular[0].yetenek == sov.YETENEK_YOK
    assert bulgular[0].durdurabilir is False


# ── Sinif alanlari (girinti kaymasi) ─────────────────────────────────────────

def test_sinif_icine_dusmus_blok_yakalaniyor(vasi_module):
    """Gercek olay: INTERNAL blogu bir seviye iceri yapistirildi.

    Sonuc SECRET'in icinde bos bir INTERNAL anahtari ve ezilmis bir
    rag_allowed degeri oldu. YAML tekrar eden anahtari sessizce ezer.
    """
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_sinif_alanlari({
        "politika_siniflari": {
            "PUBLIC": {"description": "x", "rag_allowed": True},
            "SECRET": {
                "description": "y", "rag_allowed": True,
                "INTERNAL": None,          # girintisi kaymis blogun kalintisi
            },
        },
    })
    assert len(bulgular) == 1
    assert "SECRET" in bulgular[0].mesaj
    assert "INTERNAL" in bulgular[0].mesaj
    assert "Girinti" in bulgular[0].mesaj


def test_temiz_politikada_beklenmeyen_alan_yok(vasi_module):
    sov = vasi_module.sovereign
    assert sov.kontrol_sinif_alanlari({
        "politika_siniflari": {
            "SECRET": {
                "description": "x", "gemini_allowed": False,
                "rag_allowed": False, "external_share_allowed": False,
            },
        },
    }) == []


def test_iki_kontrol_ayni_olayi_farkli_soyluyor(vasi_module):
    """Biri TEHLIKEYI, digeri YERI bildirir.

    "Bir sey yanlis" ile "su satir yanlis" ayni cumle degil. Gercek
    olayda ikisi birden cikmali.
    """
    sov = vasi_module.sovereign
    goruntu = {
        "sinif_onceligi": ("SECRET", "PRIVATE", "PROJECT", "PUBLIC"),
        "politika_siniflari": {
            "SECRET": {"rag_allowed": True, "INTERNAL": None},
            "PRIVATE": {"rag_allowed": False},
            "PROJECT": {"rag_allowed": True},
            "PUBLIC": {"rag_allowed": True},
        },
    }
    sonuc = sov.audit(goruntu)
    kontroller = {b.kontrol for b in sonuc.bulgular}
    assert "politika_izin_mantigi" in kontroller   # tehlike
    assert "sinif_alanlari" in kontroller          # yer

    tehlike = next(b for b in sonuc.bulgular if b.kontrol == "politika_izin_mantigi")
    yer = next(b for b in sonuc.bulgular if b.kontrol == "sinif_alanlari")
    assert tehlike.durdurabilir is True    # RAG kapanir
    assert yer.durdurabilir is False       # yalnizca yol gosterir


# ══════════════════════════════════════════════════════════════════════════════
# FAZ 3 — PARMAK IZI VE ZAMAN ICINDE SAPMA
# ══════════════════════════════════════════════════════════════════════════════

def _goruntu(**ek):
    temel = {
        "izinli_araclar": {"a", "b"},
        "sunulan_araclar": {"a", "b"},
        "sinif_onceligi": ("SECRET", "PUBLIC"),
        "politika_siniflari": {"SECRET": {"rag_allowed": False}},
        "prompta_girebilen": ("user",),
        "gecerli_kaynaklar": ("user", "web"),
        "onay_gereken_komutlar": frozenset({"yaz"}),
        "onay_isteyen_komutlar": {"yaz"},
        "aracsiz_fonksiyon_kaynagi": "def f(): pass",
    }
    temel.update(ek)
    return temel


# ── Parmak izi: saf fonksiyon ────────────────────────────────────────────────

def test_parmak_izi_sayaclari_kapsamiyor(vasi_module):
    """EN ONEMLI TEST: sayaclar her komutta degisir.

    Kapsama girselerdi her denetim "sapma var" derdi. Duzenli yanlis
    alarm veren bir kontrol, bir hafta icinde kapatilir.
    """
    sov = vasi_module.sovereign
    a = sov.parmak_izi(_goruntu(komut_sayisi=5, hata_sayisi=0))
    b = sov.parmak_izi(_goruntu(komut_sayisi=900, hata_sayisi=40))
    assert a == b
    assert "komut_sayisi" not in a and "hata_sayisi" not in a


def test_parmak_izi_izlenen_alanlar_acik_liste(vasi_module):
    """Yasak listesi degil, izin listesi.

    Yeni bir alan anlik goruntuye eklendiginde kendiliginden
    izlenmeye baslamaz -- bilincli olarak listeye yazilir.
    """
    sov = vasi_module.sovereign
    izi = sov.parmak_izi(_goruntu(yepyeni_alan="deger"))
    assert "yepyeni_alan" not in izi
    assert set(izi) <= set(sov.IZLENEN_ALANLAR)


def test_kume_kanonik_hali_sirali(vasi_module):
    """Kume ozetlenirken SIRALANMALI.

    Ilk yazdigim test iki ayni kumeyi karsilastiriyordu ve hicbir sey
    sinamiyordu: ayni surecte ayni kume hep ayni sirayla dolasilir, o
    yuzden siralamayi kaldirdigimda test yine gecti. Kirip bakmasaydim
    fark etmezdim.

    Asil risk sureclerin ARASINDA: PYTHONHASHSEED degisince kume
    dolasim sirasi degisir. Siralanmazsa her yeniden baslatma sapma
    gorunur -- ve duzenli yanlis alarm veren kontrol kapatilir.
    Dogrudan ciktinin sirali oldugunu dogruluyoruz.

    Uc elemanla yazmayi da denedim; o da yakalamadi. Uc elemanli bir
    kumenin tesadufen sirali dolasilma ihtimali yuksek. On iki
    elemanda bu ihtimal 1/12! -- pratikte sifir.
    """
    import json as _json
    sov = vasi_module.sovereign
    elemanlar = [f"arac_{i:02d}" for i in range(12)]
    kume = set(reversed(elemanlar))
    assert sov._kanonik(kume) == _json.dumps(sorted(elemanlar), ensure_ascii=False)


def test_parmak_izi_gercek_degisikligi_goruyor(vasi_module):
    sov = vasi_module.sovereign
    a = sov.parmak_izi(_goruntu())
    b = sov.parmak_izi(_goruntu(izinli_araclar={"a", "b", "yeni_arac"}))
    assert a["izinli_araclar"] != b["izinli_araclar"]


def test_uzun_alan_ozetleniyor(vasi_module):
    """Kaynak kodu satir satir veritabanina yazilmamali."""
    sov = vasi_module.sovereign
    izi = sov.parmak_izi(_goruntu(aracsiz_fonksiyon_kaynagi="x" * 5000))
    deger = izi["aracsiz_fonksiyon_kaynagi"]
    assert deger.startswith("sha256:")
    assert len(deger) < 40


def test_kisa_alan_oldugu_gibi_saklaniyor(vasi_module):
    """Kisa alanlarda raporun "ne degisti" diyebilmesi icin."""
    sov = vasi_module.sovereign
    izi = sov.parmak_izi(_goruntu())
    assert "user" in izi["prompta_girebilen"]


def test_parmak_izi_yan_etkisiz(vasi_module):
    """Saf fonksiyon: anlik goruntuyu degistirmemeli."""
    sov = vasi_module.sovereign
    g = _goruntu()
    kopya = {k: (set(v) if isinstance(v, set) else v) for k, v in g.items()}
    sov.parmak_izi(g)
    assert g["izinli_araclar"] == kopya["izinli_araclar"]
    assert set(g) == set(kopya)


# ── Zaman sapmasi kontrolu ───────────────────────────────────────────────────

def test_ilk_denetimde_sapma_raporlanmiyor(vasi_module):
    """Karsilastiracak gecmis yoksa sessiz kal."""
    sov = vasi_module.sovereign
    assert sov.kontrol_zaman_sapmasi(_goruntu()) == []


def test_degismemis_sistem_sapma_uretmiyor(vasi_module):
    sov = vasi_module.sovereign
    g = _goruntu()
    assert sov.kontrol_zaman_sapmasi({**g, "onceki_parmak_izi": sov.parmak_izi(g)}) == []


def test_degisen_alan_raporlaniyor_ama_durdurmuyor(vasi_module):
    """DEGISIKLIK, SAPMA DEGILDIR.

    Deterministik -- "su alan degisti" bir olgudur. Ama onemi BILGI
    ve hicbir yetenek kapanmaz. Tur ile onem ayri eksenler oldugu
    icin bu ikisi ayni anda soylenebiliyor.
    """
    sov = vasi_module.sovereign
    onceki = sov.parmak_izi(_goruntu())
    simdiki = _goruntu(izinli_araclar={"a", "b", "yeni_arac"})
    bulgular = sov.kontrol_zaman_sapmasi({**simdiki, "onceki_parmak_izi": onceki})

    assert len(bulgular) == 1
    b = bulgular[0]
    assert b.tur == sov.DETERMINISTIK
    assert b.onem == sov.BILGI
    assert b.yetenek == sov.YETENEK_YOK
    assert b.durdurabilir is False
    assert "izinli_araclar" in b.mesaj


def test_sapma_mesaji_zamani_soyluyor(vasi_module):
    sov = vasi_module.sovereign
    onceki = sov.parmak_izi(_goruntu())
    bulgular = sov.kontrol_zaman_sapmasi({
        **_goruntu(prompta_girebilen=("user", "web")),
        "onceki_parmak_izi": onceki,
        "onceki_parmak_izi_zamani": "26.09 13:04",
    })
    assert "26.09 13:04" in bulgular[0].mesaj


def test_kaybolan_alan_da_sapma_sayiliyor(vasi_module):
    """Bir alanin ortadan kalkmasi da bir degisikliktir."""
    sov = vasi_module.sovereign
    onceki = sov.parmak_izi(_goruntu())
    eksik = _goruntu()
    del eksik["gecerli_kaynaklar"]
    bulgular = sov.kontrol_zaman_sapmasi({**eksik, "onceki_parmak_izi": onceki})
    assert len(bulgular) == 1
    assert "gecerli_kaynaklar" in bulgular[0].mesaj


def test_zaman_sapmasi_hicbir_yetenegi_kapatmiyor(vasi_module):
    """Kapi uzerinden dogrulama: bu bulgu hicbir seyi kapatmamali."""
    sov = vasi_module.sovereign
    onceki = sov.parmak_izi(_goruntu())
    simdiki = _goruntu(izinli_araclar={"bambaska"})
    sonuc = sov.audit({**simdiki, "onceki_parmak_izi": onceki})
    kapi = sov.YetenekKapisi()
    kapi.uygula(sonuc)
    assert kapi.kapali == {} or sov.YETENEK_RAG not in {
        b.yetenek for b in sonuc.bulgular if b.kontrol == "zaman_sapmasi"
    }
    assert all(not b.durdurabilir for b in sonuc.bulgular if b.kontrol == "zaman_sapmasi")


# ── Katman kurali korunuyor mu ───────────────────────────────────────────────

def test_sovereign_hala_veritabani_bilmiyor(vasi_module):
    """Kalicilik ayri dosyada: sovereign.py servise bagli kalmamali."""
    kaynak = Path(vasi_module.sovereign.__file__).read_text(encoding="utf-8")
    for yasak in ("psycopg", "sovereign_store", "_connect", "SELECT ", "INSERT "):
        assert yasak not in kaynak, f"sovereign.py veritabanina bulasti: {yasak}"


def test_iz_okunamazsa_denetim_yine_calisiyor(vasi_module, monkeypatch):
    """Veritabani duserse zaman sapmasi susar, denetim devam eder."""
    def patlat():
        raise RuntimeError("baglanti yok")
    monkeypatch.setattr(vasi_module.sovereign_store, "son_iz", patlat)
    monkeypatch.setattr(vasi_module.memory, "is_configured", lambda: True)

    alanlar = vasi_module._onceki_iz_alanlari()
    assert alanlar == {}
    sonuc = vasi_module.sovereign.audit(_goruntu())
    assert sonuc.hatali_kontrol == []


def test_baslangic_denetimi_iz_kaydetmiyor(vasi_module):
    """Taban cizgisi yalnizca /denetle ile ilerler.

    Baslangic kaydetseydi su olurdu: politika degistirilir, yeniden
    baslatilir, baslangic farki bulur ve KONTEYNER GUNLUGUNE yazar,
    sonra yeni hali taban cizgisi yapar. Bir sonraki /denetle fark
    goremez -- sapma tespit edilmis ama kimseye ulasmamis olur.

    Bu dagitimda politika imaja gomulu, yani her politika degisikligi
    zaten bir yeniden baslatma. Baslangic kaydetseydi zaman sapmasi
    Telegram'da hic gorunmezdi.
    """
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    bas = kaynak.index("_baslangic_sonucu = sovereign.audit")
    son = kaynak.index("app = Application.builder()", bas)
    assert "_izi_kaydet" not in kaynak[bas:son], (
        "baslangic denetimi iz kaydediyor; taban cizgisi insan gormeden ilerler"
    )


def test_denetle_komutu_iz_kaydediyor(vasi_module):
    """Taban cizgisini ilerleten tek yer /denetle olmali."""
    assert "_izi_kaydet(goruntu)" in inspect.getsource(vasi_module.cmd_denetle)


def test_baslangic_raporu_bulguya_gore_veriliyor(vasi_module):
    """Kapatmayan bir bulgu da bulgudur; "temiz" demek yalan olur."""
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    bas = kaynak.index("_baslangic_sonucu = sovereign.audit")
    son = kaynak.index("app = Application.builder()", bas)
    blok = kaynak[bas:son]
    assert "_baslangic_sonucu.temiz" in blok, (
        "baslangic raporu kapanan yetenege gore veriliyor; bulguya gore olmali"
    )


# ── /saglik satiri ───────────────────────────────────────────────────────────

def test_saglik_raporunda_sovereign_var(vasi_module):
    """Faz 4'un eksik kalan parcasi: denetci saglik raporunda gorunmeli."""
    assert "build_sovereign_health()" in inspect.getsource(vasi_module.build_health_report)


def test_kapali_yetenek_saglikta_hata(vasi_module):
    """Kapali bir yetenek HATA. Sistem calisiyor ama eksik calisiyor.

    Saglik raporunda gizlenirse operator "neden /bul calismiyor?"
    sorusunun cevabini kodda arar.
    """
    sov = vasi_module.sovereign
    kapi = vasi_module.YETENEK_KAPISI
    kapi.uygula(_sonuc(sov, _bulgu(sov, kontrol="politika_kod_uyumu")))
    try:
        h = vasi_module.build_sovereign_health()
        assert h.status == "error"
        assert "rag" in h.details
        assert "/denetle" in h.details
    finally:
        kapi.uygula(_sonuc(sov))


def test_gecersiz_kilinmis_yetenek_saglikta_uyari(vasi_module):
    """Gecersiz kilma hata degil, ama sessiz de kalmamali."""
    sov = vasi_module.sovereign
    kapi = vasi_module.YETENEK_KAPISI
    kapi.uygula(_sonuc(sov, _bulgu(sov)))
    kapi.gecersiz_kil(sov.YETENEK_RAG, 1800)
    try:
        h = vasi_module.build_sovereign_health()
        assert h.status == "warn"
        assert "geçersiz kılındı" in h.details
    finally:
        kapi.geri_al(sov.YETENEK_RAG)
        kapi.uygula(_sonuc(sov))


def test_temizken_kontrol_sayisi_gosteriliyor(vasi_module):
    sov = vasi_module.sovereign
    vasi_module.YETENEK_KAPISI.uygula(_sonuc(sov))
    h = vasi_module.build_sovereign_health()
    assert h.status in ("ok", "warn")
    assert str(len(sov.KONTROLLER)) in h.details