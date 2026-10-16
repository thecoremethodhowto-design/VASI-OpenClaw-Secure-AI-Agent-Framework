"""Ikinci tanik, GERCEK bir PostgreSQL'e karsi -- botun KENDI hesabiyla.

Bu testler varsayilan olarak ATLANIR: testler botun gercek
veritabanina asla baglanmaz (conftest.py). Calistirmak icin bos, ATILABILIR
bir veritabani ve o sunucunun SUPER KULLANICISINI verin -- adi '_test' ile
bitmeli, cunku testler tanik tablosunu silip yeniden kuruyor:

    VASI_TEST_PG="host=127.0.0.1 port=5432 user=vasi password=... dbname=vasi_test" \\
        python -m pytest tests/test_audit_store_pg.py

Tanik, kurulumda kullanilan DOSYANIN AYNISIYLA kurulur
(scripts/postgres/tanik.sql). Test hesaplari ayri adlar tasir
(vasi_bot_test, denetim_sahibi_test): ayni sunucudaki gercek bot
hesabina dokunulmaz.

Neden ayri: sahte tanikla yapilan testler (test_ikinci_tanik.py) yazicinin
ne yaptigini dogrular. Bunlar veritabaninin ne YAPTIGINI dogrular: yalnizca
ekleme kurali gercekten reddediyor mu, botun hesabi gercekten silemiyor mu.
Semada ya da kurulum betiginde yazili olmasi, calistigi anlamina gelmez.
"""
import importlib
import logging
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

DSN = os.getenv("VASI_TEST_PG", "")

pytestmark = pytest.mark.skipif(
    not DSN, reason="VASI_TEST_PG verilmedi: gercek veritabani testleri atlandi"
)

KOK = Path(__file__).resolve().parents[1]
KURULUM_SQL = KOK / "scripts" / "postgres" / "tanik.sql"
BOT = "vasi_bot_test"
SAHIP = "denetim_sahibi_test"
BOT_PAROLA = uuid.uuid4().hex


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

    def bot_olarak(kullanici=BOT, parola=BOT_PAROLA):
        """Botun baglantisi: memory modulunun ayarlari."""
        monkeypatch.setattr(memory, "POSTGRES_USER", kullanici)
        monkeypatch.setattr(memory, "POSTGRES_PASSWORD", parola)

    monkeypatch.setattr(memory, "POSTGRES_HOST", ayar.get("host", "localhost"))
    monkeypatch.setattr(memory, "POSTGRES_PORT", int(ayar.get("port", 5432)))
    monkeypatch.setattr(memory, "POSTGRES_DB", ayar["dbname"])
    bot_olarak()

    def sql(komut):
        """SUPER KULLANICI olarak (yonetici, saldirgan ya da kurulum)."""
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(komut)

    def bot_sql(komut):
        """Botun KENDI hesabiyla: botu ele geciren birinin elindeki yetki."""
        bot_dsn = {**ayar, "user": BOT, "password": BOT_PAROLA}
        with psycopg.connect(**bot_dsn, autocommit=True) as c:
            return c.execute(komut)

    def kur():
        """scripts/postgres/kurulum.sh'nin yaptigi: ayarlar + tanik.sql, super kullanici."""
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute("SELECT set_config('vasi.bot_rol', %s, false), "
                      "set_config('vasi.sahip_rol', %s, false), "
                      "set_config('vasi.bot_parola', %s, false)", (BOT, SAHIP, BOT_PAROLA))
            c.execute(KURULUM_SQL.read_text(encoding="utf-8"))

    # Her test temiz baslar: test botunun her yerde sahip oldugu her sey ve
    # aldigi her yetki silinir (onceki bir test ya da kanit.py'nin bir
    # bozmasi geride bir sey birakmis olabilir), tanik bos kurulur.
    with psycopg.connect(DSN, autocommit=True) as c:
        for rol in (BOT, SAHIP):
            if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (rol,)).fetchone():
                c.execute(f'DROP OWNED BY "{rol}"')
    sql("DROP TABLE IF EXISTS public.denetim_zinciri")
    sql("DROP FUNCTION IF EXISTS public.denetim_zinciri_yalnizca_ekleme() CASCADE")
    kur()
    return SimpleNamespace(s=audit_store, ac=audit_chain, sql=sql, bot_sql=bot_sql,
                           kur=kur, bot_olarak=bot_olarak, psycopg=psycopg)


def _g(sira):
    return f"AUDIT | olay | user=*** | x | sira={sira}"


def test_kayit_durumlari(pg):
    s, ac = pg.s, pg.ac
    t = s.VeritabaniTanigi()
    assert t.son_halka() is None and t.halkalar() == []
    g = _g(1)
    o = ac.ozet(ac.BASLANGIC, g)
    assert t.kaydet(1, o, g) == "yazildi"
    assert t.kaydet(1, o, g) == "ayni"
    assert t.kaydet(1, "f" * 32, g) == "catal"
    assert t.kaydet(1, o, g + " X") == "catal"          # ozet ayni, icerik farkli
    assert t.son_halka() == (1, o)


def test_bot_tanigi_silemez_kurali_kapatamaz(pg):
    """'Gunlukler Yalan Soyleyebilir mi?'deki iki deneme, bu kez botun hesabiyla.

    1. deneme: tabloyu dusurmek. 4. deneme: kurali kapat, satiri sil, kurali
    ac. Ikisi de botun veritabani yetkisiyle yapilmisti. Artik reddediliyor --
    tetikleyiciye bile ulasmadan, yetkide.
    """
    s, ac, psycopg = pg.s, pg.ac, pg.psycopg
    t = s.VeritabaniTanigi()
    t.kaydet(1, ac.ozet(ac.BASLANGIC, _g(1)), _g(1))
    reddedilenler = {
        "UPDATE public.denetim_zinciri SET govde = 'x'": "permission denied",
        "DELETE FROM public.denetim_zinciri": "permission denied",
        "TRUNCATE public.denetim_zinciri": "permission denied",
        "DROP TABLE public.denetim_zinciri": "must be owner",
        "ALTER TABLE public.denetim_zinciri DISABLE TRIGGER USER": "must be owner",
        f"ALTER TABLE public.denetim_zinciri OWNER TO {BOT}": "must be owner",
        "CREATE OR REPLACE FUNCTION public.denetim_zinciri_yalnizca_ekleme() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN OLD; END $$":
            "must be owner|permission denied for schema public",
        f"SET ROLE {SAHIP}": "permission denied",
    }
    for komut, hata in reddedilenler.items():
        with pytest.raises(psycopg.Error, match=hata):
            pg.bot_sql(komut)
    assert len(t.halkalar()) == 1
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME


def test_kural_super_kullaniciya_da_satir_sildirmiyor(pg):
    """Tetikleyici yerinde: yetkisi olan da satiri sessizce silemez."""
    s, ac, psycopg = pg.s, pg.ac, pg.psycopg
    t = s.VeritabaniTanigi()
    t.kaydet(1, ac.ozet(ac.BASLANGIC, _g(1)), _g(1))
    for komut in ("UPDATE public.denetim_zinciri SET govde = 'x'",
                  "DELETE FROM public.denetim_zinciri",
                  "TRUNCATE public.denetim_zinciri"):
        with pytest.raises(psycopg.Error, match="yalnizca ekleme kabul eder"):
            pg.sql(komut)
    assert len(t.halkalar()) == 1


def test_bicimsiz_ozet_veritabanina_girmiyor(pg):
    with pytest.raises(pg.psycopg.errors.CheckViolation):
        pg.s.VeritabaniTanigi().kaydet(1, "XYZ", "g")


def test_tablo_yoksa_bot_kurmuyor(pg):
    """Bot tabloyu kurabilseydi kurdugu tablonun sahibi olurdu -- ve onu
    yeniden dusurebilirdi. 'tablo_yok' der, tablo yok kalir."""
    s = pg.s
    t = s.VeritabaniTanigi()
    t.kaydet(1, "a" * 32, _g(1))
    pg.sql("DROP TABLE public.denetim_zinciri")             # super kullanici
    assert t.ilk_sira() is None and t.son_halka() is None and t.halkalar() == []
    assert t.kaydet(2, "b" * 32, _g(2)) == s.TABLO_KURULMAMIS
    assert s.yetki_durumu()[0] == s.TABLO_KURULMAMIS
    pg.kur()                                                # yonetici geri kurar
    assert t.kaydet(2, "b" * 32, _g(2)) == "yazildi"
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME


def test_yetki_durumu_olcuyor_ve_kurulum_onariyor(pg):
    """Iddia degil olcum: hesap sonradan genisletilirse /saglik bunu gormeli."""
    s = pg.s
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME

    pg.sql(f"GRANT DELETE ON public.denetim_zinciri TO {BOT}")
    durum, aciklama = s.yetki_durumu()
    assert durum == s.FAZLA_YETKI and "silme" in aciklama
    pg.kur()                                                # betik fazlayi geri alir
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME

    pg.sql(f"ALTER TABLE public.denetim_zinciri OWNER TO {BOT}")
    durum, aciklama = s.yetki_durumu()
    assert durum == s.FAZLA_YETKI and "sahibi" in aciklama
    pg.kur()
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME

    pg.sql(f"REVOKE INSERT ON public.denetim_zinciri FROM {BOT}")
    assert s.yetki_durumu()[0] == s.EKSIK_YETKI
    pg.kur()

    pg.sql(f"ALTER ROLE {BOT} SUPERUSER")
    try:
        durum, aciklama = s.yetki_durumu()
        assert durum == s.FAZLA_YETKI and "süper" in aciklama
    finally:
        pg.kur()                                            # NOSUPERUSER'a geri ceker
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME


def test_eski_kurulum_super_kullaniciyla_baglaniyorsa_fazla_yetki(pg):
    """Kurulum betigi calismadan once bot super kullaniciydi: /saglik soylemeli."""
    from psycopg.conninfo import conninfo_to_dict
    ayar = conninfo_to_dict(DSN)
    pg.bot_olarak(ayar["user"], ayar.get("password", ""))
    durum, aciklama = pg.s.yetki_durumu()
    assert durum == pg.s.FAZLA_YETKI and "süper" in aciklama


def test_kurulum_tekrar_calistirilabilir_veriyi_korur(pg):
    s = pg.s
    t = s.VeritabaniTanigi()
    for sira in (3, 1, 2):
        t.kaydet(sira, "a" * 32, _g(sira))
    pg.kur()
    pg.kur()
    assert [h[0] for h in t.halkalar()] == [1, 2, 3]


def test_kurulum_onceki_tablolari_botun_semasina_tasir(pg):
    """Eski kurulumda hafiza tablolari 'public'teydi ve super kullanicinindi.
    Bot onlari kendisi yonetiyor (CREATE TABLE IF NOT EXISTS, SERIAL) ama
    artik kendi semasinda: 'public'te nesne kuramaz. Ad nitelemeyen
    sorgular (memory.py, rag.py) "$user" sayesinde onlari bulur."""
    pg.sql(f"DROP TABLE IF EXISTS public.ai_memory, {BOT}.ai_memory")
    pg.sql("CREATE TABLE public.ai_memory (id BIGSERIAL PRIMARY KEY, x TEXT)")
    pg.sql("INSERT INTO public.ai_memory (x) VALUES ('eski')")
    pg.kur()
    try:
        pg.bot_sql("CREATE TABLE IF NOT EXISTS ai_memory (id BIGSERIAL PRIMARY KEY, x TEXT)")
        pg.bot_sql("INSERT INTO ai_memory (x) VALUES ('yeni')")
        assert pg.bot_sql("SELECT count(*) FROM ai_memory").fetchone()[0] == 2
        with pytest.raises(pg.psycopg.Error, match="permission denied for schema public"):
            pg.bot_sql("CREATE TABLE public.baska (x int)")
    finally:
        pg.sql(f"DROP TABLE IF EXISTS public.ai_memory, {BOT}.ai_memory")


def test_kurulum_botun_public_tuzagina_dusmuyor(pg):
    """Bagimsiz inceleme (Ekim 2026): bot 'public'te format() ya da
    pg_has_role() kurup kurulumun yeniden calismasini bekliyordu; super
    kullanici olarak calisan betik botunkini cagiriyor, bot kendini super
    kullanici yapiyordu. Eski kurulumdaki gibi bota 'public'te CREATE
    verilir, tuzak kurulur, betik yeniden calisir: bot super olmamali,
    kurulum da tuzagi bulup DURMALI."""
    pg.sql(f"GRANT CREATE ON SCHEMA public TO {BOT}")
    tuzak = (f"LANGUAGE plpgsql AS $$ BEGIN EXECUTE 'ALTER ROLE {BOT} SUPERUSER'; "
             f"RETURN true; END $$")
    pg.bot_sql(f"CREATE FUNCTION public.format(text, text) RETURNS text {tuzak.replace('RETURN true', 'RETURN $1')}")
    pg.bot_sql(f"CREATE FUNCTION public.pg_has_role(text, text, text) RETURNS boolean {tuzak}")
    try:
        with pytest.raises(pg.psycopg.Error, match="public semasinda nesne sahibi"):
            pg.kur()
        with pg.psycopg.connect(DSN) as c:
            assert c.execute(f"SELECT rolsuper FROM pg_roles WHERE rolname = '{BOT}'").fetchone()[0] is False
    finally:
        pg.sql("DROP FUNCTION IF EXISTS public.format(text, text)")
        pg.sql("DROP FUNCTION IF EXISTS public.pg_has_role(text, text, text)")
        pg.sql(f"ALTER ROLE {BOT} NOSUPERUSER")
    pg.kur()
    with pytest.raises(pg.psycopg.Error, match="permission denied for schema public"):
        pg.bot_sql("CREATE FUNCTION public.f() RETURNS int LANGUAGE sql AS 'SELECT 1'")


def test_dolayli_uyelik_olculuyor_ve_kurulum_durduruyor(pg):
    """bot -> ara hesap -> sahip: SET ROLE ile sahip olunur. INHERIT FALSE
    olsa bile. Olcum bunu gormeli, kurulum 'onardim' dememeli."""
    s = pg.s
    ara = "vasi_ara_test"
    pg.sql(f"DROP ROLE IF EXISTS {ara}")
    pg.sql(f"CREATE ROLE {ara} NOLOGIN")
    try:
        pg.sql(f"GRANT {SAHIP} TO {ara}")
        pg.sql(f"GRANT {ara} TO {BOT} WITH INHERIT FALSE")
        durum, aciklama = s.yetki_durumu()
        assert durum == s.FAZLA_YETKI and "sahibine üye" in aciklama
        with pytest.raises(pg.psycopg.Error, match="dolayli olarak uye"):
            pg.kur()
    finally:
        pg.sql(f"DROP ROLE IF EXISTS {ara}")
    pg.kur()
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME


def test_bot_kayit_zamanini_yazamaz(pg):
    """Tanik 'ne zaman yazildi'yi de soyler; o zamani bot degil veritabani yazar."""
    with pytest.raises(pg.psycopg.Error, match="permission denied"):
        pg.bot_sql("INSERT INTO public.denetim_zinciri (sira, ozet, govde, yazildi) "
                   f"VALUES (1, '{'a' * 32}', 'g', '2000-01-01')")
    assert pg.s.VeritabaniTanigi().kaydet(1, "a" * 32, _g(1)) == "yazildi"


def test_kural_kapatilirsa_olcum_soyluyor(pg):
    s = pg.s
    pg.sql("ALTER TABLE public.denetim_zinciri DISABLE TRIGGER denetim_zinciri_degismez")
    durum, aciklama = s.yetki_durumu()
    assert durum == s.KURAL_EKSIK and "kuralı" in aciklama
    pg.kur()                                                # kurali yeniden kurar
    assert s.yetki_durumu()[0] == s.YALNIZCA_EKLEME


def test_kurulum_betigi_psql_ile_uctan_uca(pg, tmp_path):
    """kurulum.sh'nin kendisi: psql degiskenleri, tirnaklama, \\i yolu.
    Konteynerde psql yok: orada atlanir; postgres konteynerinde elle calisir."""
    import shutil
    import subprocess
    from psycopg.conninfo import conninfo_to_dict
    if shutil.which("psql") is None:
        pytest.skip("psql yok")
    ayar = conninfo_to_dict(DSN)
    parola = "tırnak ' çift \" dolar $ boşluk"
    ortam = {
        "PATH": os.environ.get("PATH", ""),
        "PGHOST": ayar.get("host", "localhost"), "PGPORT": str(ayar.get("port", 5432)),
        "PGPASSWORD": ayar.get("password", ""),
        "POSTGRES_USER": ayar["user"], "POSTGRES_DB": ayar["dbname"],
        "POSTGRES_PASSWORD": ayar.get("password", ""),
        "VASI_BOT_USER": BOT, "VASI_TANIK_SAHIBI": SAHIP, "VASI_BOT_PASSWORD": parola,
        "VASI_KURULUM_SQL": str(KURULUM_SQL),
    }
    r = subprocess.run(["sh", str(KOK / "scripts" / "postgres" / "kurulum.sh")],
                       env=ortam, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    pg.bot_olarak(BOT, parola)
    try:
        assert pg.s.yetki_durumu()[0] == pg.s.YALNIZCA_EKLEME
    finally:
        pg.kur()                                            # test parolasina geri don


def test_SINIR_super_kullanici_tanigi_hala_silebilir(pg):
    """Bu test GECMELI. Gectigi surece zincirin ucu makine disina capalanmali.

    Ayri hesap botu ele gecireni durdurur. Makineye ve veritabaninin super
    kullanicisina erisen biri (`docker compose exec postgres psql`) hala
    'Gunlukler Yalan Soyleyebilir mi?'deki 4. denemeyi yapar: kurali kapat,
    satiri sil, kurali ac. Tanik ayni makinede oldukca bunu kod kapatamaz.
    """
    s = pg.s
    t = s.VeritabaniTanigi()
    for sira in (1, 2, 3):
        t.kaydet(sira, "a" * 32, _g(sira))
    pg.sql("ALTER TABLE public.denetim_zinciri DISABLE TRIGGER USER")
    pg.sql("DELETE FROM public.denetim_zinciri WHERE sira = 3")
    pg.sql("ALTER TABLE public.denetim_zinciri ENABLE TRIGGER USER")
    assert [h[0] for h in t.halkalar()] == [1, 2], "Bu artik engelleniyorsa bu testi guncelle"


def test_gercek_tanikla_3_ekim_senaryosu(pg, tmp_path):
    """Yedek bot dururken geri konuyor; gercek veritabani hatirliyor."""
    s, ac = pg.s, pg.ac
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


def test_bot_calisirken_tablo_silinirse_kurmuyor_bekletiyor_ve_soyluyor(pg, tmp_path):
    """Bot calisirken super kullanici tabloyu dusurur. Bot onu yeniden KURMAZ:
    alarmi ize yazar, halkalari bellekte bekletir; yonetici tabloyu geri
    kurunca bekleyenler sirayla yazilir. Kayip halkalar 'tanık sıfırlanmış'
    olarak gorunur -- sessizce kapanmaz."""
    s, ac = pg.s, pg.ac
    yol = tmp_path / "denetim.log"
    lg = logging.getLogger(f"pg-{uuid.uuid4().hex}")
    lg.propagate, lg.level = False, logging.INFO
    h = ac.ZincirliDosyaYazicisi(str(yol), tanik=s.VeritabaniTanigi(), encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s - vasi - INFO - %(message)s"))
    lg.addHandler(h)
    try:
        lg.info("AUDIT | ilk | user=***422 | x")            # sira 1: dogum kaydi, 2: ilk
        lg.info("AUDIT | ikinci | user=***422 | x")         # 3
        pg.sql("DROP TABLE public.denetim_zinciri")
        lg.info("AUDIT | ucuncu | user=***422 | x")         # tablo yok
        assert "tablosu yok" in (h.tanik_durumu or ""), h.tanik_durumu
        assert s.yetki_durumu()[0] == s.TABLO_KURULMAMIS, "bot tabloyu yeniden kurmamaliydi"
        pg.kur()                                            # yonetici geri kurar
        lg.info("AUDIT | dorduncu | user=***422 | x")       # bekleyenler yazilir
    finally:
        lg.removeHandler(h)
        h.close()

    r = ac.dogrula_dosyalar(ac.dosyalari_sirala(yol))
    assert any("tablo silinmiş" in m.aciklama for m in r.mudahaleler), r.mudahaleler
    halkalar = s.VeritabaniTanigi().halkalar()
    k, tanik_r = ac.iki_tanigi_karsilastir(r, halkalar)
    assert k.sifirlanmis and k.taniksiz == [1, 2, 3], k
    assert not k.dosyada_yok and not k.farkli, k
    assert halkalar[0][0] == 4                               # yeni tanik bekleyen ilk halkadan
    assert tanik_r.saglam


def test_gercek_tanik_silinirse_alarm(pg, tmp_path):
    """Bagimsiz incelemenin saldirisi, gercek veritabaniyla.

    Bot dururken: dosyanin sonu kesilir, tanik tablosu silinir (DROP
    TABLE, artik yalnizca super kullanici yapabilir), sonra bos geri kurulur.
    Eskiden bot bunu 'ilk kurulum' saniyordu ve her sey yesil yaniyordu.
    """
    s, ac = pg.s, pg.ac
    yol = tmp_path / "denetim.log"
    calistir = _calistirici(s, ac, yol)
    calistir("ilk", "ikinci")
    yedek = yol.read_text(encoding="utf-8")
    calistir("sovereign_audit", "baska")
    yol.write_text(yedek, encoding="utf-8")                 # bot dururken sondan sil
    pg.sql("DROP TABLE public.denetim_zinciri")             # ... ve tanigi sil (super kullanici)
    pg.kur()                                                # tablo bos geri gelir
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
    s, ac = pg.s, pg.ac
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
