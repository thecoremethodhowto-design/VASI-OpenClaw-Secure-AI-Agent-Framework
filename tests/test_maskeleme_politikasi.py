"""Maskeleme POLITIKASI.

KURAL: Yetkili kullanicinin kimligi her yerde maskelenir; yetkisiz
olaninki hicbir yerde.

  Yetkili kullanici  -> MASKELI (***321)
      Sistem tek kullaniciya kilitli. Yetkilendirmeden sonra yazilan
      her satirdaki kimlik zaten belli; hicbir soruyu cevaplamiyor,
      ama ekran goruntusune, video karesine ve depoya giriyor.

  Yetkisiz erisim    -> MASKESIZ
      Burada kimlik tek onemli bilgi: kim denedi.

ICERIK KURALI: Durum degistiren islemin icerigi (/hatirla neyi
hatirlatti) denetim izine girer -- o bir olgudur. Sohbet icerigi
hicbir loga girmez.

Dosya iki kisim. Once DAVRANIS: fonksiyonu gercekten cagir, yazilan
satira bak. Sonra YAPISAL KURAL: tum log cagrilarini tara. Davranis
testi tek bir yolu kanitlar; yapisal kural yarin eklenecek satiri da
yakalar. Sovereign'daki kapinin import sinirina konmasiyla ayni mantik.
"""
import ast
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parents[1]


class _Topla(logging.Handler):
    def __init__(self):
        super().__init__()
        self.satirlar = []

    def emit(self, kayit):
        self.satirlar.append(kayit.getMessage())


@pytest.fixture()
def log_topla():
    """'vasi' logger'ina yazilan her satiri toplar."""
    topla = _Topla()
    lg = logging.getLogger("vasi")
    eski = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(topla)
    yield topla
    lg.removeHandler(topla)
    lg.setLevel(eski)


def _sahte_guncelleme(user_id):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=int(user_id)),
        effective_chat=SimpleNamespace(id=int(user_id), type="private"),
        message=SimpleNamespace(
            forward_origin=None, date=datetime.now(timezone.utc)
        ),
    )


# ── 1. DAVRANIS ──────────────────────────────────────────────────────────────

def test_rate_limit_asimi_maskeli_loglaniyor(vasi_module, log_topla):
    """Rate limit yetkilendirmeden SONRA calisir: kimlik senin."""
    access = sys.modules["access"]
    for _ in range(access.RATE_LIMIT_REQUESTS + 1):
        access.check_rate_limit("987654321")

    uyari = [s for s in log_topla.satirlar if "Rate limit" in s]
    assert uyari, "rate limit uyarisi yazilmadi"
    assert "***321" in uyari[-1]
    assert "987654321" not in uyari[-1], f"Tam kimlik sizdi: {uyari[-1]}"


def test_yetkisiz_erisim_maskesiz_loglaniyor(vasi_module, log_topla):
    """Baskasinin kimligi maskelenirse iz ise yaramaz."""
    access = sys.modules["access"]
    yabanci = "555000111"
    assert yabanci != access.MY_TELEGRAM_ID

    sonuc = access.is_authorized(_sahte_guncelleme(yabanci))

    assert sonuc is False
    uyari = [s for s in log_topla.satirlar if "Yetkisiz" in s]
    assert uyari, "yetkisiz erisim uyarisi yazilmadi"
    assert yabanci in uyari[-1], (
        f"Yetkisiz erisim kimligi maskelenmis: {uyari[-1]}"
    )


def test_iki_maske_ayni_sonucu_veriyor(vasi_module):
    """Iki kopya, tek bicim.

    access.py katman kurali geregi observability'yi import edemiyor,
    bu yuzden maske fonksiyonunun iki kopyasi var. Ayrisirlarsa ayni
    kimlik iki farkli bicimde yazilir ve izler eslestirilemez.
    """
    access = sys.modules["access"]
    from observability import mask_user_id

    girdiler = ("", "1", "12", "123", "1234", "987654321", "1234567890",
                None, 0, 7, 1234, 987654321,           # Telegram kimligi SAYIDIR
                "sistem")                              # botun kendisi: kimlik degil
    for girdi in girdiler:
        assert access.maske_kimlik(girdi) == mask_user_id(girdi), repr(girdi)
    assert mask_user_id(987654321) == "***321"
    assert mask_user_id("987654321") == "***321"
    assert mask_user_id("sistem") == "sistem"


# ── 2. YAPISAL KURAL (tum cagri noktalari) ───────────────────────────────────

SEVIYELER = {"debug", "info", "warning", "error", "exception", "critical"}
KIMLIK_ADLARI = {"user_id", "uid"}
ICERIK_ADLARI = {"metin", "konu", "soru", "mesaj", "text", "icerik", "prompt"}

# Bilerek maskesiz birakilan TEK satir. Bu kume buyurse, birisi
# kurali delmek icin gerekce bulmus demektir: once burayi oku.
IZINLI_HAM_KIMLIK = {("access.py", "Yetkisiz erişim denemesi")}


def _ad(dugum):
    if isinstance(dugum, ast.Name):
        return dugum.id
    if isinstance(dugum, ast.Attribute):
        return _ad(dugum.value) + "." + dugum.attr
    if isinstance(dugum, ast.Subscript):
        return _ad(dugum.value) + "[]"
    if isinstance(dugum, ast.Call):
        return _ad(dugum.func) + "()"
    return "?"


def _log_ifadeleri():
    """(dosya, satir_no, sabit_metin, [bicimlenen ifadeler]) uretir."""
    for dosya in sorted(KOK.glob("*.py")):
        kaynak = dosya.read_text(encoding="utf-8")
        for d in ast.walk(ast.parse(kaynak)):
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in SEVIYELER
                    and _ad(d.func.value).endswith("logger")):
                continue
            for arg in d.args:
                if not isinstance(arg, ast.JoinedStr):
                    continue
                sabit = "".join(
                    v.value for v in arg.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                )
                ifadeler = [_ad(v.value) for v in arg.values
                            if isinstance(v, ast.FormattedValue)]
                yield dosya.name, d.lineno, sabit, ifadeler


def test_hicbir_log_satiri_ham_kimlik_yazmiyor():
    ihlaller = []
    for dosya, no, sabit, ifadeler in _log_ifadeleri():
        for ifade in ifadeler:
            kok = ifade.split(".")[0].split("[")[0]
            ham = ifade.endswith("effective_user.id") or kok in KIMLIK_ADLARI
            if not ham:
                continue
            izinli = any(dosya == f and parca in sabit
                         for f, parca in IZINLI_HAM_KIMLIK)
            if not izinli:
                ihlaller.append(f"{dosya}:{no}  {{{ifade}}}  '{sabit.strip()}'")
    assert not ihlaller, "Maskesiz kimlik yazan log satirlari:\n  " + "\n  ".join(ihlaller)


def test_hicbir_log_satiri_sohbet_icerigi_yazmiyor():
    ihlaller = []
    for dosya, no, sabit, ifadeler in _log_ifadeleri():
        for ifade in ifadeler:
            kok = ifade.split(".")[0].split("[")[0]
            if kok in ICERIK_ADLARI:
                ihlaller.append(f"{dosya}:{no}  {{{ifade}}}  '{sabit.strip()}'")
    assert not ihlaller, "Sohbet icerigi yazan log satirlari:\n  " + "\n  ".join(ihlaller)


def test_izinli_istisna_gercekten_var():
    """Istisna listesi olu bir girdi tasimasin.

    Satir silinir ya da yeniden adlandirilirsa istisna bos kalir ve
    yarin baska bir satir ayni metni kullanarak kurali delebilir.
    """
    bulunan = {(d, p) for d, _, sabit, _ in _log_ifadeleri()
               for (f, p) in IZINLI_HAM_KIMLIK if d == f and p in sabit}
    assert bulunan == IZINLI_HAM_KIMLIK, (
        f"Istisna listesinde karsiligi olmayan girdi: {IZINLI_HAM_KIMLIK - bulunan}"
    )


def test_access_audit_event_kullanmiyor():
    """access.py audit_event() cagirmaya baslarsa yetkisiz erisim
    kayitlari da maskelenir ve bunu kimse fark etmez."""
    kaynak = (KOK / "access.py").read_text(encoding="utf-8")
    assert "audit_event(" not in kaynak
