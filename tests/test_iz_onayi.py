"""Faz 5: denetim izinin onayi, acilis kaydi ve denetcinin izi denetlemesi.

ONAY: kurcalama kaniti kalici. Ama hic temizlenemeyen bir uyari bir
sure sonra okunmaz olur -- ve bir sonraki gercek mudahale eskilerin
gurultusu icinde kaybolur. /iz_onayla bulgulari SILMEZ; "gordum,
inceledim" kaydini zincire ekler. Onay da bir halka: tanikta da durur,
sessizce eklenemez ya da silinemez.
"""
import asyncio
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import audit_chain as ac  # noqa: E402
from test_ikinci_tanik import _SahteTanik, _Yazici, _satirlar, _yaz_satirlar  # noqa: E402


def _dosya(yol):
    return ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))


def _kurcalanmis_iz(yol, tanik):
    """Bot dururken iki satiri silinmis bir iz: kirik + mudahale + tanikta fark."""
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki")
    yedek = _satirlar(yol)
    with _Yazici(yol, tanik) as y:
        y.yaz("uc", "dort")
    _yaz_satirlar(yol, yedek)
    with _Yazici(yol, tanik) as y:                  # yeniden basladi: bildirim + bes
        y.yaz("bes")
    r = _dosya(yol)
    assert not r.temiz
    return r


def _onayla(yol, tanik, kapsam, *sonra):
    """/iz_onayla'nin yaptigi: acik bulgularin KIMLIKLERIYLE onay satiri."""
    r = _dosya(yol)
    k, t = ac.iki_tanigi_karsilastir(r, tanik.halkalar())
    _, kimlikler = ac.acik_bulgular(r, k, t)
    with _Yazici(yol, tanik) as y:
        y.lg.info(f"AUDIT | {ac.ONAY_OLAYI} | user=***456 | "
                  f"{ac.onay_ayrintisi(kapsam, kimlikler)}")
        y.yaz(*sonra)


# ── 1. Dogrulayici: onay neyi kapsar, neyi kapsamaz ──────────────────────────

def test_onay_bulgulari_silmiyor_gecmise_tasiyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, kapsam=once.son_sira)

    r = _dosya(yol)
    assert r.temiz, (r.sorunlar, r.mudahaleler)
    # sira 1 tanigin dogum kaydi; 'uc' ve 'dort' sira 4-5 idi
    assert [(x.tur, x.sira) for x in r.onaylanan] == [("eksik", 6), ("mudahale", 6)]
    assert "onaylı geçmiş: 2 bulgu" in ac.ozet_satiri(r)
    metin = ac.rapor_metni(r)
    assert "✔ Onaylanmış geçmiş — 2 bulgu" in metin and "sıra 4–5 kayıp" in metin
    assert metin.rstrip().endswith("✅ Zincir sağlam.")


def test_onaydan_sonraki_mudahale_yeniden_uyariyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, once.son_sira, "alti", "yedi")

    s = _satirlar(yol)
    s[-1] = s[-1].replace("yedi", "YEDI")           # onaydan SONRA degistir
    _yaz_satirlar(yol, s)
    r = _dosya(yol)
    assert not r.saglam
    assert [x.tur for x in r.sorunlar] == ["degistirilmis"]
    assert len(r.onaylanan) == 2                    # eski gecmis yine onayli


def test_araya_sokulmus_sahte_onay_hicbir_seyi_onaylamiyor(tmp_path):
    """Bicimi kusursuz (dogru kimlik listesi), ama zincire bagli degil."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    k, t = ac.iki_tanigi_karsilastir(once, tanik.halkalar())
    _, kimlikler = ac.acik_bulgular(once, k, t)
    s = _satirlar(yol)
    s.append(f"AUDIT | {ac.ONAY_OLAYI} | user=***456 | "
             f"{ac.onay_ayrintisi(once.son_sira, kimlikler)} "
             f"| sira={once.son_sira + 1} | ozet={'a' * 32}")
    _yaz_satirlar(yol, s)

    r = _dosya(yol)
    assert r.onay is None and not r.onaylanan
    assert not r.saglam


def test_kendini_ya_da_gelecegi_kapsayan_onay_gecersiz(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, kapsam=once.son_sira + 50)
    r = _dosya(yol)
    assert r.onay is None and not r.temiz


def test_onay_satiri_dosyadan_silinirse_bulgular_geri_geliyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, once.son_sira, "sonraki")
    s = _satirlar(yol)
    del s[-2]                                        # onay satirini sil
    _yaz_satirlar(yol, s)

    r = _dosya(yol)
    assert r.onay is None
    assert [x.tur for x in r.sorunlar] == ["eksik", "eksik"]
    k = ac.karsilastir(r.halkalar, tanik.halkalar())
    assert once.son_sira + 1 in [s for s, _ in k.dosyada_yok], "tanik onayi hatirlamali"


def test_sirasiz_bulgu_kapsamin_hemen_ardindaysa_onaylanmiyor(tmp_path):
    """Onay istendikten SONRA eklenmis olabilecek bir satir onayli sayilmaz."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")
    s = _satirlar(yol)
    s.insert(1, "yabanci satir A")                   # sira 1'den sonra: kapsam icinde
    s.append("yabanci satir B")                      # sira 4'ten sonra: kapsamin sinirinda
    _yaz_satirlar(yol, s)
    _onayla(yol, tanik, kapsam=4)

    r = _dosya(yol)
    assert [x.konum for x in r.onaylanan] == ["iz.log:2"]
    assert [x.tur for x in r.sorunlar] == ["yabanci"]


def test_komut_satiri_onaydan_sonra_temiz_ama_gecmisi_gosteriyor(tmp_path, capsys):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    assert ac.main([str(yol)]) == 1
    _onayla(yol, tanik, once.son_sira)
    capsys.readouterr()
    assert ac.main([str(yol)]) == 0
    assert "Onaylanmış geçmiş" in capsys.readouterr().out


def test_karsilastirma_onaydaki_listeyi_gecmise_tasiyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, once.son_sira)

    r = _dosya(yol)
    k, _ = ac.iki_tanigi_karsilastir(r, tanik.halkalar())
    assert k.uyusuyor and k.onaylanan == [("dosyada yok", 4), ("dosyada yok", 5)]
    assert "onaylı: 2 halka" in ac.tanik_ozet_satiri(k, ac.tanik_raporu(tanik.halkalar()))
    assert "✔ Onaylanmış geçmiş (kapsam sıra ≤" in ac.karsilastirma_metni(
        k, r, ac.tanik_raporu(tanik.halkalar()))


def test_tanigin_kendi_zinciri_de_onayi_taniyor(tmp_path):
    """Onay satiri taniga da yazilir; tanigin kendi dogrulamasi onu gorur."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    once = _kurcalanmis_iz(yol, tanik)
    _onayla(yol, tanik, once.son_sira)
    assert ac.tanik_raporu(tanik.halkalar()).onay is not None


# ── 2. Bot: /iz_onayla ───────────────────────────────────────────────────────

class _Mesaj:
    def __init__(self):
        self.gonderilenler, self.forward_origin = [], None
        self.date = datetime.now(timezone.utc)

    async def reply_text(self, metin, **kwargs):
        self.gonderilenler.append((metin, kwargs))


def _guncelleme():
    return SimpleNamespace(message=_Mesaj(), effective_user=SimpleNamespace(id=123456),
                           effective_chat=SimpleNamespace(id=123456, type="private"))


class _Sorgu:
    def __init__(self, veri):
        self.data, self.metin = veri, None

    async def answer(self):
        pass

    async def edit_message_text(self, metin, **kwargs):
        self.metin = metin


def _onay_dugmesi(v, context, veri="pending:yes"):
    sorgu = _Sorgu(veri)
    upd = SimpleNamespace(callback_query=sorgu, effective_user=SimpleNamespace(id=123456),
                          effective_chat=SimpleNamespace(id=123456, type="private"),
                          message=None)
    asyncio.run(v.callback_handler(upd, context))
    return sorgu.metin


@pytest.fixture()
def tanikli(vasi_module, monkeypatch):
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    tanik = _SahteTanik()
    v._audit_yazici.tanik_bagla(tanik)
    return v, tanik


def _bot_dururken_sondan_sil(v, tanik, n=2):
    """Gercek akis: yaz, durdur, sil, yeniden baslat (yazici yeniden kurulur)."""
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    _yaz_satirlar(v.AUDIT_LOG_FILE, _satirlar(v.AUDIT_LOG_FILE)[:-n])
    v._audit_yazici.close()
    yeni = ac.ZincirliDosyaYazicisi(v.AUDIT_LOG_FILE, tanik=tanik, encoding="utf-8")
    yeni.setFormatter(v._log_bicimi)
    yeni.addFilter(v._SadeceAudit())
    logging.getLogger("vasi").removeHandler(v._audit_yazici)
    logging.getLogger("vasi").addHandler(yeni)
    yeni._vasi_denetim_yazicisi = True
    v._audit_yazici = yeni


def test_onaylanacak_bir_sey_yoksa_onay_istemiyor(tanikli):
    v, _ = tanikli
    v.audit_event("bir", "123456", "x")
    update, context = _guncelleme(), SimpleNamespace(args=[], user_data={})
    asyncio.run(v.cmd_iz_onayla(update, context))
    assert "Onaylanacak bulgu yok" in update.message.gonderilenler[-1][0]
    assert "pending_action" not in context.user_data


def test_iz_onayla_once_gosteriyor_onaydan_sonra_yaziyor(tanikli):
    v, tanik = tanikli
    _bot_dururken_sondan_sil(v, tanik)
    assert v.build_denetim_izi_health().status == "warn"

    update, context = _guncelleme(), SimpleNamespace(args=[], user_data={})
    asyncio.run(v.cmd_iz_onayla(update, context))
    metin, kwargs = update.message.gonderilenler[-1]
    assert "reply_markup" in kwargs, "onay butonu yok"
    assert "tanıkta var, dosyada yok" in metin
    bekleyen = context.user_data["pending_action"]
    assert bekleyen["action"] == "iz_onayla"
    assert ac.ONAY_OLAYI not in Path(v.AUDIT_LOG_FILE).read_text(encoding="utf-8")

    sonuc = _onay_dugmesi(v, context)
    assert sonuc.startswith("✔ Onaylandı")
    satirlar = _satirlar(v.AUDIT_LOG_FILE)
    assert any(f"| {ac.ONAY_OLAYI} |" in s and f"kapsam={bekleyen['kapsam']}" in s
               for s in satirlar)

    saglik = v.build_denetim_izi_health()
    assert saglik.status == "ok", saglik.details
    assert "onaylı geçmiş" in saglik.details and "onaylı: 2 halka" in saglik.details


def test_onay_bekleyen_yazici_bildirimini_de_kapsiyor(tanikli):
    """Bot dururken silinmis: bildirim henuz dosyada degil. Istek onu yazdirir."""
    v, tanik = tanikli
    _bot_dururken_sondan_sil(v, tanik)
    assert v._audit_yazici._bekleyen, "bildirim bekliyor olmaliydi"

    update, context = _guncelleme(), SimpleNamespace(args=[], user_data={})
    asyncio.run(v.cmd_iz_onayla(update, context))
    assert "dosya tanığın gerisinde" in update.message.gonderilenler[-1][0]
    _onay_dugmesi(v, context)
    assert v.build_denetim_izi_health().status == "ok"


def test_iptal_edilen_onay_hicbir_seyi_onaylamiyor(tanikli):
    v, tanik = tanikli
    _bot_dururken_sondan_sil(v, tanik)
    update, context = _guncelleme(), SimpleNamespace(args=[], user_data={})
    asyncio.run(v.cmd_iz_onayla(update, context))
    _onay_dugmesi(v, context, "pending:no")
    assert ac.ONAY_OLAYI not in Path(v.AUDIT_LOG_FILE).read_text(encoding="utf-8")
    assert v.build_denetim_izi_health().status == "warn"


def test_iz_onayla_onay_kapisinda(vasi_module):
    v = vasi_module
    assert "iz_onayla" in v.ONAY_GEREKEN_KOMUTLAR
    assert "iz_onayla" in v._onay_isteyen_komutlar()
    assert "/iz_onayla" in v.HELP_TEXT
    assert 'CommandHandler("iz_onayla"' in Path(v.__file__).read_text(encoding="utf-8")


# ── 3. Her acilis ize yazilir ────────────────────────────────────────────────

def test_sistem_kimligi_maskelenmiyor(vasi_module):
    v = vasi_module
    v.audit_event("baslangic_denetimi", v.SISTEM_KIMLIGI, "bulgu=0")
    assert "| user=sistem |" in _satirlar(v.AUDIT_LOG_FILE)[-1]


def test_her_acilis_ize_yaziliyor_tanik_baglandiktan_sonra(vasi_module):
    """Acilis satiri, bekleyen tanik bildirimini de hemen dosyaya gecirir."""
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    ana = kaynak[kaynak.index('if __name__ == "__main__":'):]
    assert ana.index("tanik_bagla(") < ana.index('"baslangic_denetimi", SISTEM_KIMLIGI')
    blok = ana[ana.index("_baslangic_sonucu = sovereign.audit"):ana.index("app = Application.builder()")]
    assert blok.count('"baslangic_denetimi", SISTEM_KIMLIGI') == 2, "hata yolunda da yazilmali"
    assert 'audit_event("sovereign_yetenek_kapandi", SISTEM_KIMLIGI' in blok


# ── 4. Denetci izi de denetliyor ─────────────────────────────────────────────

def _iz(**kw):
    temel = {"kalicilik": "kalici", "kalicilik_aciklama": "kalıcı · /app/denetim",
             "zincir": {"saglam": True, "temiz": True, "ozet": "zincir sağlam (3 halka)"},
             "tanik": {"tamam": True, "kritik": False, "ozet": "tanık uyuşuyor (3 halka)"}}
    temel.update(kw)
    return {"denetim_izi": temel}


@pytest.mark.parametrize("goruntu, beklenen", [
    ({}, []),
    (_iz(), []),
    (_iz(kalicilik="gecici"), [("iz_kaliciligi", "uyari")]),
    (_iz(zincir={"saglam": False, "temiz": False, "ozet": "zincir kırık: sıra 8"}),
     [("iz_butunlugu", "kritik")]),
    (_iz(zincir={"saglam": True, "temiz": False, "ozet": "dış müdahale kaydı: sıra 3"}),
     [("iz_butunlugu", "uyari")]),
    (_iz(tanik={"tamam": False, "kritik": True, "ozet": "tanık: 2 halka dosyada yok"}),
     [("iz_tanigi", "kritik")]),
    (_iz(tanik={"tamam": False, "kritik": False, "ozet": "tanık okunamadı"}),
     [("iz_tanigi", "uyari")]),
    ({"denetim_izi": {"hata": "disk"}}, [("iz_butunlugu", "uyari")]),
])
def test_denetci_izi_denetliyor_ama_hicbir_seyi_kapatmiyor(vasi_module, goruntu, beklenen):
    sov = vasi_module.sovereign
    bulgular = sov.kontrol_iz_butunlugu(goruntu)
    assert [(b.kontrol, b.onem) for b in bulgular] == beklenen
    assert not any(b.durdurabilir for b in bulgular), "Raporla, durdurma"
    for b in bulgular:                       # ozet, mesajin onekini tekrarlamamali
        m = b.mesaj.lower()
        assert "kırık: zincir kırık" not in m and "tanık: tanık" not in m, b.mesaj


def test_denetle_kurcalanmis_izi_soyluyor(tanikli):
    v, tanik = tanikli
    _bot_dururken_sondan_sil(v, tanik)
    sonuc = v.sovereign.audit(v.guvenlik_anlik_goruntusu())
    tanik_bulgusu = [b for b in sonuc.bulgular if b.kontrol == "iz_tanigi"]
    assert tanik_bulgusu and tanik_bulgusu[0].mesaj.startswith("Tanık: 2 halka dosyada yok")
    assert not sonuc.kapanacak_yetenekler


def test_guvenlik_raporu_onay_iddiasi_davranistan_geliyor(vasi_module, monkeypatch):
    """Rapor 'onay butonuyla' derse komut gercekten onay istemeli -- iki yonde."""
    v = vasi_module
    assert "kaydını Telegram onay butonuyla zincire" in v.build_security_report()
    monkeypatch.setattr(v, "ONAY_GEREKEN_KOMUTLAR", v.ONAY_GEREKEN_KOMUTLAR - {"iz_onayla"})
    rapor = v.build_security_report()
    assert "ONAY İSTEMEDEN" in rapor and "onay butonuyla zincire" not in rapor
