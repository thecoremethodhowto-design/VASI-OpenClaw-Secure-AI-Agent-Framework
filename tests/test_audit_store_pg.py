"""Ikinci tanik, GERCEK bir PostgreSQL'e karsi.

Bu testler varsayilan olarak ATLANIR: testler botun gercek
veritabanina asla baglanmaz (conftest.py). Calistirmak icin bos, ATILABILIR
bir veritabani verin -- adi '_test' ile bitmeli, cunku her test tanik
tablosunu silip yeniden kuruyor:

    VASI_TEST_PG="host=127.0.0.1 port=5432 user=vasi password=... dbname=vasi_test" \\
        python -m pytest tests/test_audit_store_pg.py

Neden ayri: sahte tanikla yapilan testler (test_ikinci_tanik.py) yazicinin
ne yaptigini dogrular. Bunlar veritabaninin ne YAPTIGINI dogrular: yalnizca
ekleme kurali gercekten reddediyor mu, catallanma gercekten taninyor mu.
Semada yazili olmasi, calistigi anlamina gelmez.
"""
import importlib
import logging
import os
import sys
import uuid
from pathlib import Path

import pytest

DSN = os.getenv("VASI_TEST_PG", "")

pytestmark = pytest.mark.skipif(
    not DSN, reason="VASI_TEST_PG verilmedi: gercek veritabani testleri atlandi"
)

KOK = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pg(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import conninfo_to_dict

    ayar = conninfo_to_dict(DSN)
    if not str(ayar.get("dbname", "")).endswith("_test"):
        pytest.skip("VASI_TEST_PG bir test veritabanini gostermeli (adi _test ile bitmeli)")

    if str(KOK) not in sys.path:
        sys.path.insert(0, str(KOK))
    for ad in ("memory", "audit_store", "audit_chain"):
        sys.modules.pop(ad, None)
    memory = importlib.import_module("memory")
    audit_store = importlib.import_module("audit_store")
    audit_chain = importlib.import_module("audit_chain")
    monkeypatch.setattr(memory, "POSTGRES_HOST", ayar.get("host", "localhost"))
    monkeypatch.setattr(memory, "POSTGRES_PORT", int(ayar.get("port", 5432)))
    monkeypatch.setattr(memory, "POSTGRES_USER", ayar.get("user", "vasi"))
    monkeypatch.setattr(memory, "POSTGRES_PASSWORD", ayar.get("password", ""))
    monkeypatch.setattr(memory, "POSTGRES_DB", ayar["dbname"])

    def sql(komut):
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(komut)

    # Her test bos bir taniktan baslar. DROP, tetikleyicilere takilmaz:
    # yalnizca-ekleme kurali satirlari korur, tabloyu degil -- ayni yetkiye
    # sahip biri bunu yapabilir (guvenlik raporunda yazili sinir). Yazici
    # bunu artik ALGILIYOR: test_gercek_tanik_silinirse_alarm.
    sql("DROP TABLE IF EXISTS denetim_zinciri")
    sql("DROP FUNCTION IF EXISTS denetim_zinciri_yalnizca_ekleme() CASCADE")
    return audit_store, audit_chain, sql, psycopg


def test_sema_ilk_kullanimda_kuruluyor_ve_kayit_durumlari(pg):
    s, ac, _, _ = pg
    t = s.VeritabaniTanigi()
    assert t.son_halka() is None and t.halkalar() == []
    g = "AUDIT | bir | user=*** | x | sira=1"
    o = ac.ozet(ac.BASLANGIC, g)
    assert t.kaydet(1, o, g) == "kuruldu"                 # tablo yoktu: kuruldu ve yazildi
    assert t.kaydet(1, o, g) == "ayni"
    assert t.kaydet(1, "f" * 32, g) == "catal"
    assert t.kaydet(1, o, g + " X") == "catal"          # ozet ayni, icerik farkli
    assert t.son_halka() == (1, o)


def test_tanik_yalnizca_ekleme_kabul_ediyor(pg):
    s, ac, sql, psycopg = pg
    t = s.VeritabaniTanigi()
    g = "AUDIT | bir | user=*** | x | sira=1"
    t.kaydet(1, ac.ozet(ac.BASLANGIC, g), g)
    for komut in ("UPDATE denetim_zinciri SET govde = 'x'",
                  "DELETE FROM denetim_zinciri",
                  "TRUNCATE denetim_zinciri"):
        with pytest.raises(psycopg.Error, match="yalnizca ekleme kabul eder"):
            sql(komut)
    assert len(t.halkalar()) == 1


def test_bicimsiz_ozet_veritabanina_girmiyor(pg):
    s, _, _, psycopg = pg
    with pytest.raises(psycopg.errors.CheckViolation):
        s.VeritabaniTanigi().kaydet(1, "XYZ", "g")


def test_sema_tekrar_calistirilabilir_ve_halkalar_sirali(pg):
    s, ac, _, _ = pg
    s.init_schema()
    s.init_schema()
    t = s.VeritabaniTanigi()
    for sira in (3, 1, 2):
        t.kaydet(sira, "a" * 32, f"g | sira={sira}")
    assert [h[0] for h in t.halkalar()] == [1, 2, 3]


def test_gercek_tanikla_3_ekim_senaryosu(pg, tmp_path):
    """Yedek bot dururken geri konuyor; gercek veritabani hatirliyor."""
    s, ac, _, _ = pg
    yol = tmp_path / "denetim.log"

    def calistir(*olaylar):
        lg = logging.getLogger(f"pg-{uuid.uuid4().hex}")
        lg.propagate, lg.level = False, logging.INFO
        h = ac.ZincirliDosyaYazicisi(str(yol), tanik=s.VeritabaniTanigi(), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s - vasi - INFO - %(message)s"))
        lg.addHandler(h)
        for o in olaylar:
            lg.info(f"AUDIT | {o} | user=***422 | x")
        lg.removeHandler(h)
        h.close()

    calistir("ilk", "ikinci")
    yedek = yol.read_text(encoding="utf-8")
    calistir("sovereign_audit", "baska")
    yol.write_text(yedek, encoding="utf-8")                 # bot dururken

    r = ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))
    assert r.temiz, "dosya tek basina hala kandirilmali"
    halkalar = s.VeritabaniTanigi().halkalar()
    k, tanik_r = ac.iki_tanigi_karsilastir(r, halkalar)
    assert [sira for sira, _ in k.dosyada_yok] == [4, 5]     # 1: tanigin dogum kaydi
    assert "sovereign_audit" in ac.karsilastirma_metni(k, r, tanik_r)

    assert s.main([str(yol)]) == 1                          # komut satiri da soyluyor
    calistir("sonraki")
    r = ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))
    assert [(x.tur, x.sira) for x in r.sorunlar] == [("eksik", 6)]


def _calistirici(s, ac, yol):
    def calistir(*olaylar):
        lg = logging.getLogger(f"pg-{uuid.uuid4().hex}")
        lg.propagate, lg.level = False, logging.INFO
        h = ac.ZincirliDosyaYazicisi(str(yol), tanik=s.VeritabaniTanigi(), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s - vasi - INFO - %(message)s"))
        lg.addHandler(h)
        for o in olaylar:
            lg.info(f"AUDIT | {o} | user=***422 | x")
        lg.removeHandler(h)
        h.close()
    return calistir


def test_tablo_silinince_kaydet_kuruldu_diyor(pg):
    """Bot calisirken DROP TABLE: bir sonraki yazim tabloyu kurar ve SOYLER."""
    s, ac, sql, _ = pg
    t = s.VeritabaniTanigi()
    for sira in (1, 2):
        t.kaydet(sira, "a" * 32, f"g | sira={sira}")
    assert t.ilk_sira() == 1
    sql("DROP TABLE denetim_zinciri")
    assert t.ilk_sira() is None and t.son_halka() is None
    assert t.kaydet(3, "b" * 32, "g | sira=3") == "kuruldu"
    assert t.kaydet(4, "c" * 32, "g | sira=4") == "yazildi"
    assert t.ilk_sira() == 3


def test_gercek_tanik_silinirse_alarm(pg, tmp_path):
    """Bagimsiz incelemenin saldirisi, gercek veritabaniyla.

    Bot dururken: dosyanin sonu kesilir, tanik tablosu silinir (DROP
    TABLE). Acilista sema bos tabloyla geri gelir. Eskiden bot bunu
    'ilk kurulum' saniyordu ve her sey yesil yaniyordu.
    """
    s, ac, sql, _ = pg
    yol = tmp_path / "denetim.log"
    calistir = _calistirici(s, ac, yol)
    calistir("ilk", "ikinci")
    yedek = yol.read_text(encoding="utf-8")
    calistir("sovereign_audit", "baska")
    yol.write_text(yedek, encoding="utf-8")                 # bot dururken sondan sil
    sql("DROP TABLE denetim_zinciri")                       # ... ve tanigi sil
    s.init_schema()                                         # acilis: sema bos geri gelir
    calistir("sonraki")

    r = ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))
    assert any("tanık sıfırlanmış" in m.aciklama for m in r.mudahaleler), r.mudahaleler
    k, tanik_r = ac.iki_tanigi_karsilastir(r, s.VeritabaniTanigi().halkalar())
    assert k.sifirlanmis and k.taniksiz == [1, 2, 3]
    assert "Tanık sıfırlanmış" in ac.karsilastirma_metni(k, r, tanik_r)
    assert s.main([str(yol)]) == 1


def test_gercek_tanikla_rotasyon_ve_yeniden_baslatmalar_yanlis_alarm_vermiyor(pg, tmp_path):
    """Kucuk dosyalarla bircok rotasyon, dort yeniden baslatma, gercek veritabani.

    Ikinci incelemeden sonra rotasyon zincirde iz birakiyor (donme kaydi) ve
    tanik kac dosyanin gitmis olmasi gerektigini kendi kopyasindan sayiyor.
    Mesru isletimde hicbiri alarm uretmemeli."""
    s, ac, _, _ = pg
    yol = tmp_path / "denetim.log"

    def calistir(*olaylar):
        lg = logging.getLogger(f"pg-{uuid.uuid4().hex}")
        lg.propagate, lg.level = False, logging.INFO
        h = ac.ZincirliDosyaYazicisi(str(yol), tanik=s.VeritabaniTanigi(), encoding="utf-8",
                                     maxBytes=1500, backupCount=2)
        h.setFormatter(logging.Formatter("%(asctime)s - vasi - INFO - %(message)s"))
        lg.addHandler(h)
        for o in olaylar:
            lg.info(f"AUDIT | {o} | user=***422 | x")
        lg.removeHandler(h)
        h.close()

    for tur in range(4):
        calistir(*[f"tur{tur}_olay{i:02d}" for i in range(15)])
        r = ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))
        k, t = ac.iki_tanigi_karsilastir(r, s.VeritabaniTanigi().halkalar(), yedek_sayisi=2)
        assert r.temiz and k.uyusuyor and t.saglam, (tur, r.sorunlar, r.mudahaleler, k)
    assert k.dosya_oncesi > 0, "rotasyon en eski dosyayi silmedi: test bir sey sinamiyor"
    assert r.tanik_baslangici == 1                           # dogum kaydi donme kayitlarinda
