"""Denetim izinin ikinci tanigi: zincirin dosyadan bagimsiz kopyasi.

test_audit_chain.py::test_SINIR_... dosyanin TEK BASINA neyi
yakalayamadigini gosteriyor ve gecmeye devam ediyor. Bu dosya ayni
saldirilarin tanik devredeyken yakalandigini gosteriyor.

3 Ekim 2026'da canli yasanan senaryo burada birebir kuruluyor: bot
dururken eski bir yedek geri konuyor; dosya "saglam" diyor, cunku son
satirlarin silinmesi bir ozet zincirini bozmaz.

Bu testler veritabanina BAGLANMAZ: tanik, ayni uc metodu bellekte
uygulayan sahte bir nesne. Gercek PostgreSQL'e karsi olan testler
test_audit_store_pg.py'de ve yalnizca bir test veritabani verilince
calisir.
"""
import asyncio
import logging
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parents[1]
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))
import audit_chain as ac  # noqa: E402


class _SahteTanik:
    """VeritabaniTanigi ile ayni metodlar -- bellekte."""

    def __init__(self):
        self.kayit = {}                 # sira -> (ozet, govde)
        self.kapali = False             # True: veritabani kapali gibi her cagri patlar
        self.okuma_kapali = False       # True: yalnizca son_halka patlar
        self.tablo_yok = False          # True: tablo silinmis (DROP TABLE)

    def _kontrol(self):
        if self.kapali:
            raise ConnectionError("veritabanı kapalı")

    def sifirla(self):
        """Saldirgan: docker compose exec postgres psql -c 'DROP TABLE denetim_zinciri'."""
        self.kayit.clear()
        self.tablo_yok = True

    def sema_kur(self):
        """Bot acilisi: audit_store.init_schema() tabloyu BOS olarak yeniden kurar."""
        self.tablo_yok = False

    def son_halka(self):
        self._kontrol()
        if self.okuma_kapali:
            raise ConnectionError("okunamadı")
        if not self.kayit:
            return None
        s = max(self.kayit)
        return s, self.kayit[s][0]

    def ilk_sira(self):
        self._kontrol()
        return min(self.kayit) if self.kayit else None

    def kaydet(self, sira, ozet, govde):
        self._kontrol()
        kuruldu = self.tablo_yok        # gercek tanik: tablo yoksa kurar ve yazar
        self.tablo_yok = False
        if sira in self.kayit:
            return "ayni" if self.kayit[sira] == (ozet, govde) else "catal"
        self.kayit[sira] = (ozet, govde)
        return "kuruldu" if kuruldu else "yazildi"

    def halkalar(self):
        self._kontrol()
        return [(s, o, g, None) for s, (o, g) in sorted(self.kayit.items())]


class _Yazici:
    """Tanikli yazici. Her nesne bir 'calisma': kapaninca bot durmus olur."""

    def __init__(self, yol, tanik, bicim="%(message)s"):
        self.lg = logging.getLogger(f"tanik-test-{uuid.uuid4().hex}")
        self.lg.propagate = False
        self.lg.setLevel(logging.INFO)
        self.h = ac.ZincirliDosyaYazicisi(str(yol), tanik=tanik, encoding="utf-8")
        self.h.setFormatter(logging.Formatter(bicim))
        self.lg.addHandler(self.h)

    def yaz(self, *olaylar):
        for olay in olaylar:
            self.lg.info(f"AUDIT | {olay} | user=***456 | ayrinti")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.lg.removeHandler(self.h)
        self.h.close()


def _satirlar(yol):
    return Path(yol).read_text(encoding="utf-8").splitlines()


def _yaz_satirlar(yol, satirlar):
    Path(yol).write_text("\n".join(satirlar) + "\n", encoding="utf-8")


def _dosya(yol):
    return ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))


def _iki_tanik(yol, tanik):
    r = _dosya(yol)
    return r, ac.karsilastir(r.halkalar, tanik.halkalar())


def _bastan_hesapla(satirlar):
    yeni, onceki = [], ac.BASLANGIC
    for sira, satir in enumerate(satirlar, 1):
        govde, _, _ = ac.halka_coz(satir)
        govde = re.sub(r"\| sira=\d+$", f"| sira={sira}", govde)
        oz = ac.ozet(onceki, govde)
        yeni.append(f"{govde} | ozet={oz}")
        onceki = oz
    return yeni


# ── 1. Tanik her halkayi goruyor ─────────────────────────────────────────────

def test_her_halka_tanikta_da_var(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc")

    dosyadaki = [ac.halka_coz(s) for s in _satirlar(yol)]
    assert [(s, o, g) for g, s, o in dosyadaki] == [
        (s, o, g) for s, o, g, _ in tanik.halkalar()]
    # 1. halka tanigin dogum kaydi: tanik bu halkadan beri tutuyor.
    assert ac.TANIK_BASLANGICI in _satirlar(yol)[0]
    r, k = _iki_tanik(yol, tanik)
    assert k.uyusuyor and k.eslesen == 4 and r.temiz


# ── 2. Dosyanin tek basina yakalayamadigi: bot DURURKEN ──────────────────────

def test_3_ekim_bot_dururken_geri_konan_yedek_yakalaniyor(tmp_path):
    """Canli yasanan: yedek geri kondu, dosya 'saglam' dedi.

    Tanik yokken: yeniden baslayan yazici dosyanin ucuna inanir, iz
    silinenin ustunden sorunsuz devam eder (test_SINIR_...). Tanikla:
    zincir tanigin ucundan surer, bosluk dosyanin KENDISINDE de gorunur.
    """
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("ilk", "ikinci")
    yedek = _satirlar(yol)
    with _Yazici(yol, tanik) as y:
        y.yaz("denetim_2216", "baska_bir_olay")      # sira 4 ve 5 (1: dogum kaydi)
    _yaz_satirlar(yol, yedek)                        # bot dururken geri koy
    assert _dosya(yol).temiz, "dosya tek basina hala kandiriliyor olmali"

    r, k = _iki_tanik(yol, tanik)                     # yeniden baslamadan once bile
    assert [s for s, _ in k.dosyada_yok] == [4, 5]

    with _Yazici(yol, tanik) as y:                   # bot yeniden basladi
        y.yaz("sonraki")

    s = _satirlar(yol)
    assert ac.TANIK_OLAYI in s[-2] and "sonraki" in s[-1]
    r, k = _iki_tanik(yol, tanik)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 6)]
    assert "sıra 4–5 kayıp" in r.sorunlar[0].aciklama
    assert [s for s, _ in k.dosyada_yok] == [4, 5]
    assert [m.sira for m in r.mudahaleler] == [6]


@pytest.mark.parametrize("saldiri, dosyada, ilk_kirik", [
    ("sil",      {"farkli": [3, 4, 5], "dosyada_yok": [6]}, ("eksik", 7)),
    ("degistir", {"farkli": [3, 4, 5, 6], "dosyada_yok": []}, ("degistirilmis", 7)),
])
def test_bot_dururken_bastan_hesaplanan_zincir_yakalaniyor(tmp_path, saldiri, dosyada, ilk_kirik):
    """test_SINIR_'deki saldirinin ta kendisi -- bu kez tanik devrede."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz(*[f"olay_{i}" for i in range(5)])
    s = _satirlar(yol)
    i = next(n for n, satir in enumerate(s) if "| olay_1 |" in satir)     # sira 3
    if saldiri == "sil":
        del s[i]
    else:
        s[i] = s[i].replace("olay_1", "olay_X")
    _yaz_satirlar(yol, _bastan_hesapla(s))
    assert _dosya(yol).temiz, "dosya tek basina kusursuz gorunmeli"

    r, k = _iki_tanik(yol, tanik)
    assert k.farkli == dosyada["farkli"]
    assert [s for s, _ in k.dosyada_yok] == dosyada["dosyada_yok"]

    with _Yazici(yol, tanik) as y:
        y.yaz("sonraki")
    r = _dosya(yol)
    assert (r.sorunlar[0].tur, r.sorunlar[0].sira) == ilk_kirik
    assert r.mudahaleler, "tanikla uyusmazlik ize yazilmadi"


# ── 3. Tanik kapaliyken: raporla, durdurma ───────────────────────────────────

def test_tanik_kapaliyken_iz_yazilmaya_devam_ediyor(tmp_path, caplog):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    tanik.kapali = True
    with caplog.at_level(logging.INFO, logger="audit_chain"):
        with _Yazici(yol, tanik) as y:
            assert y.h.tanik_durumu.startswith("tanık okunamadı")
            y.yaz("bir", "iki", "uc")
            assert y.h.tanik_durumu.startswith("tanığa yazılamadı")
            tanik.kapali = False                     # veritabani geri geldi
            y.yaz("dort")
            assert y.h.tanik_durumu is None

    # 1-3 kesintide; 4 tanigin dogum kaydi (tanik ilk kez bu yazimda okundu),
    # 5 kesintinin tamamlandigi kaydi, 6 'dort'. Kesintide yazilanlar da
    # artik tanikta: bot dururken sondan silinirlerse tanik gorur.
    s = _satirlar(yol)
    assert len(s) == 6, "tanik kapaliyken dosyaya yazilmadi"
    assert "ilk_sira=1 |" in s[3] and ac.TANIK_TAMAMLAMA in s[4] and "| dort |" in s[5]
    assert sorted(tanik.kayit) == [1, 2, 3, 4, 5, 6]
    mesajlar = [r.getMessage() for r in caplog.records]
    kesinti = [m for m in mesajlar if "dosyaya yazmaya devam ediliyor" in m]
    assert len(kesinti) == 1, f"kesinti bir kez soylenmeli, her yazimda degil: {kesinti}"
    assert sum("yeniden erişildi" in m for m in mesajlar) == 1


def test_tanik_baslangicta_hazir_degilse_ilk_yazimda_hizalaniyor(tmp_path):
    """Veritabani botla ayni anda kalkiyor; ilk saniyelerde hazir olmayabilir."""
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik) as y:
        y.yaz("bir", "iki", "uc", "dort")
    _yaz_satirlar(yol, _satirlar(yol)[:2])            # bot dururken sondan sil

    tanik.kapali = True
    with _Yazici(yol, tanik) as y:                   # acilista tanik yok
        tanik.kapali = False                         # ... ilk yazimdan once geldi
        y.yaz("sonraki")
    r = _dosya(yol)
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 6)]


def test_catallanma_ilk_yazilani_ezmiyor_ve_raporlaniyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    tanik.kayit[1] = ("f" * 32, "baska bir satir | sira=1")
    tanik.okuma_kapali = True                         # hizalama hic yapilamiyor
    with _Yazici(yol, tanik) as y:
        y.yaz("bir")
        assert y.h.tanik_durumu.startswith("çatallanma: sıra 1")
    assert tanik.kayit[1] == ("f" * 32, "baska bir satir | sira=1")


# ── 4. Karsilastirma: saf fonksiyon ──────────────────────────────────────────

def _halkalar(siralar, degisik=()):
    """Gercek bir zincir; 'degisik' siralardaki govde farkli."""
    dosya, tanik, onceki = [], [], ac.BASLANGIC
    for s in range(1, max(siralar) + 1):
        govde = f"AUDIT | olay_{s} | user=*** | x | sira={s}"
        oz = ac.ozet(onceki, govde)
        onceki = oz
        if s in siralar:
            tanik.append((s, oz, govde, None))
            dosya.append((s, oz, f"iz.log:{s}", govde + (" X" if s in degisik else "")))
    return dosya, tanik


def test_karsilastirma_halka_halka():
    dosya, tanik = _halkalar(range(1, 6))
    k = ac.karsilastir(dosya, tanik)
    assert k.uyusuyor and k.eslesen == 5

    k = ac.karsilastir([h for h in dosya if h[0] != 4], tanik)
    assert [s for s, _ in k.dosyada_yok] == [4] and not k.uyusuyor

    k = ac.karsilastir([h for h in dosya], [h for h in tanik if h[0] != 3])
    assert k.taniksiz == [3] and not k.uyusuyor


def test_ozeti_ayni_icerigi_farkli_satir_da_yakalaniyor():
    """Dosyanin kendi dogrulayicisi bunu zaten yakalar; burada da yakalanmali."""
    dosya, tanik = _halkalar(range(1, 5), degisik={3})
    k = ac.karsilastir(dosya, tanik)
    assert k.farkli == [3]


def test_tanik_oncesi_ve_rotasyon_sorun_sayilmiyor():
    dosya, tanik = _halkalar(range(1, 7))
    k = ac.karsilastir(dosya, [h for h in tanik if h[0] >= 3])     # tanik sonradan kuruldu
    assert k.uyusuyor and k.tanik_oncesi == 2 and k.eslesen == 4

    k = ac.karsilastir([h for h in dosya if h[0] >= 4], tanik)     # eski dosyalar dondu
    assert k.uyusuyor and k.dosya_oncesi == 3 and k.eslesen == 3


def test_tanigin_kendi_zinciri_dogrulaniyor():
    _, tanik = _halkalar(range(1, 5))
    s, oz, govde, z = tanik[1]
    tanik[1] = (s, oz, govde.replace("olay_2", "olay_X"), z)
    assert not ac.tanik_raporu(tanik).saglam


def test_rapor_silinen_olaylari_adlariyla_soyluyor(tmp_path):
    yol, tanik = tmp_path / "iz.log", _SahteTanik()
    with _Yazici(yol, tanik, bicim="%(asctime)s - vasi - INFO - %(message)s") as y:
        y.yaz("ilk")
        yedek = _satirlar(yol)
        y.yaz("sovereign_audit")
    _yaz_satirlar(yol, yedek)

    r, k = _iki_tanik(yol, tanik)
    metin = ac.karsilastirma_metni(k, r, ac.tanik_raporu(tanik.halkalar()))
    assert "❌ 1 halka tanıkta var, dosyada yok:" in metin
    assert re.search(r"sıra 3 · \d\d\.\d\d \d\d:\d\d:\d\d · sovereign_audit", metin), metin
    assert "✅" not in metin


# ── 5. Botla birlikte ────────────────────────────────────────────────────────

def _calistir(coro):
    return asyncio.run(coro)


class _SahteMesaj:
    def __init__(self):
        from datetime import datetime, timezone
        self.gonderilenler = []
        self.forward_origin = None
        self.date = datetime.now(timezone.utc)

    async def reply_text(self, metin, **kwargs):
        self.gonderilenler.append(metin)


def _guncelleme():
    return SimpleNamespace(
        message=_SahteMesaj(),
        effective_user=SimpleNamespace(id=123456),
        effective_chat=SimpleNamespace(id=123456, type="private"),
    )


@pytest.fixture()
def tanikli_bot(vasi_module, monkeypatch):
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    tanik = _SahteTanik()
    v._audit_yazici.tanik_bagla(tanik)
    return v, tanik


def test_saglik_tanik_yokken_bilgi_verir_uyarmaz(vasi_module, monkeypatch):
    """PostgreSQL hic yoksa kok sebep zaten PostgreSQL satirinda uyari."""
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    v.audit_event("bir", "123456", "x")
    satir = v.build_denetim_izi_health()
    assert satir.status == "ok"
    assert "tanık yok (PostgreSQL kapalı)" in satir.details


def test_saglik_tanik_bekleniyorken_yoksa_uyarir(vasi_module, monkeypatch):
    v = vasi_module
    monkeypatch.setattr(v, "dosya_sistemi_turu", lambda yol, baglamalar=None: "ext4")
    monkeypatch.setattr(v.memory, "is_configured", lambda: True)
    satir = v.build_denetim_izi_health()
    assert satir.status == "warn"
    assert "tanık bağlı değil" in satir.details


def test_saglik_tanikla_uyusuyor(tanikli_bot):
    v, _ = tanikli_bot
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    satir = v.build_denetim_izi_health()
    assert satir.status == "ok", satir.details
    assert "tanık uyuşuyor (4 halka)" in satir.details        # dogum kaydi + 3 olay


def test_saglik_dosya_tanigin_gerisindeyse_uyarir(tanikli_bot):
    v, _ = tanikli_bot
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    s = _satirlar(v.AUDIT_LOG_FILE)
    _yaz_satirlar(v.AUDIT_LOG_FILE, s[:2])                     # dogum kaydi + olay_0
    satir = v.build_denetim_izi_health()
    assert satir.status == "warn"
    assert "tanık: 2 halka dosyada yok (sıra 3–4)" in satir.details


def test_saglik_okunamayan_tanigi_gizlemiyor(tanikli_bot):
    v, tanik = tanikli_bot
    tanik.kapali = True
    satir = v.build_denetim_izi_health()
    assert satir.status == "warn"
    assert "tanık okunamadı" in satir.details


def test_cok_satirli_veritabani_hatasi_saglik_satirini_bolmuyor(tanikli_bot, monkeypatch):
    """psycopg hatalari 'connection failed: ...\n\tIs the server running...' gibi gelir."""
    v, tanik = tanikli_bot

    def patlat():
        raise ConnectionError("connection failed: refused\n\tIs the server running?")

    monkeypatch.setattr(tanik, "halkalar", patlat)
    assert "\n" not in v.build_denetim_izi_health().details

    monkeypatch.setattr(tanik, "kaydet", lambda *a: patlat())
    v.audit_event("bir", "123456", "x")
    assert "\n" not in v._audit_yazici.tanik_durumu


def test_iz_dogrula_once_raporluyor_sonra_kendini_yaziyor(tanikli_bot):
    v, tanik = tanikli_bot
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    update = _guncelleme()
    _calistir(v.cmd_iz_dogrula(update, SimpleNamespace(args=[])))

    metin = "\n".join(update.message.gonderilenler)
    assert "✅ İki tanık uyuşuyor: 4 halka." in metin          # dogum kaydi + 3 olay
    son = _satirlar(v.AUDIT_LOG_FILE)[-1]
    assert "AUDIT | iz_dogrulama |" in son and "uyusuyor=4" in son
    assert sorted(tanik.kayit) == [1, 2, 3, 4, 5]


def test_iz_dogrula_silineni_soyluyor(tanikli_bot):
    v, _ = tanikli_bot
    for i in range(3):
        v.audit_event(f"olay_{i}", "123456", "x")
    _yaz_satirlar(v.AUDIT_LOG_FILE, _satirlar(v.AUDIT_LOG_FILE)[:2])   # dogum + olay_0
    update = _guncelleme()
    _calistir(v.cmd_iz_dogrula(update, SimpleNamespace(args=[])))
    metin = "\n".join(update.message.gonderilenler)
    assert "❌ 2 halka tanıkta var, dosyada yok:" in metin
    assert "olay_1" in metin and "olay_2" in metin


def test_iz_dogrula_komutu_kayitli_ve_yardimda(vasi_module):
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    assert 'CommandHandler("iz_dogrula"' in kaynak
    assert "/iz_dogrula" in vasi_module.HELP_TEXT


def test_tanik_sema_kurulduktan_sonra_baglaniyor(vasi_module):
    """Once sema, sonra baglama: baglanirken tanik okunur."""
    kaynak = Path(vasi_module.__file__).read_text(encoding="utf-8")
    ana = kaynak[kaynak.index('if __name__ == "__main__":'):]
    assert "audit_store.init_schema()" in ana and "tanik_bagla(" in ana
    assert ana.index("audit_store.init_schema()") < ana.index("tanik_bagla(")


def test_guvenlik_raporu_tanik_iddiasi_davranistan_geliyor(vasi_module):
    """Rapor 'her halka veritabaninda da' derse tanik gercekten bagli olmali."""
    v = vasi_module
    rapor = v.build_security_report()
    assert v._audit_yazici.tanik is None
    assert "Kapalı (PostgreSQL yok)" in rapor
    assert "veritabanında da tutulur" not in rapor

    v._audit_yazici.tanik_bagla(_SahteTanik())
    rapor = v.build_security_report()
    assert "veritabanında da tutulur" in rapor
    assert "Kapalı (PostgreSQL yok)" not in rapor


def test_audit_store_yalnizca_hafiza_katmanina_dayaniyor():
    import ast
    yerel = {p.stem for p in KOK.glob("*.py")}
    agac = ast.parse((KOK / "audit_store.py").read_text(encoding="utf-8"))
    importlar = set()
    for d in ast.walk(agac):
        if isinstance(d, ast.Import):
            importlar |= {a.name.split(".")[0] for a in d.names}
        elif isinstance(d, ast.ImportFrom) and d.module:
            importlar.add(d.module.split(".")[0])
    assert importlar & yerel <= {"memory", "audit_chain"}, importlar & yerel


def test_tanik_semasi_yalnizca_ekleme_kabul_ediyor():
    """Veritabani seviyesinde de: kodda degil yalnizca, semada.

    Davranisin kendisi (gercekten reddediliyor mu) gercek bir PostgreSQL
    ister: test_audit_store_pg.py.
    """
    import audit_store
    sema = " ".join(audit_store.SEMA.split())
    assert "BEFORE UPDATE OR DELETE ON denetim_zinciri" in sema
    assert "BEFORE TRUNCATE ON denetim_zinciri" in sema
    assert "sira BIGINT PRIMARY KEY" in sema
    assert "CHECK (ozet ~ '^[0-9a-f]{32}$')" in sema
