-- Denetim izinin ikinci taniginin kurulumu: tablo, kural, hesaplar.
--
-- Bu dosyayi SUPER KULLANICI calistirir, bot degil. Bot tanigi kuramaz,
-- silemez, degistiremez; yalnizca satir ekler ve okur.
--
-- Neden: "Gunlukler Yalan Soyleyebilir mi?" (Ekim 2026). Bot veritabanina
-- tablonun sahibi (super kullanici) olarak baglaniyordu. Yalnizca-ekleme
-- kurali satirlari koruyordu, tabloyu degil: bir denemede tablo
-- dusuruldu, digerinde kural kapatilip satir silindi, kural geri acildi.
-- Kural sahibine islemez; sahip botsa, botu ele geciren kurali da kapatir.
--
-- Uc hesap:
--   super kullanici (postgres.env'deki POSTGRES_USER, orn. 'vasi'):
--              yalnizca yonetim. Bu dosyayi o calistirir.
--   bot        (vasi.bot_rol) giris yapar, super degil. Kendi semasinda
--              (adi hesabin adi) hafiza/RAG/sovereign tablolarinin sahibi;
--              tanikta yalnizca okur ve ekler -- kayit zamanini bile yazamaz.
--   sahip      (vasi.sahip_rol) giris YAPAMAZ. Tanik tablosunun ve kuralin
--              sahibi. Kimse onunla baglanamaz.
--
-- Hesap adlari ve botun parolasi oturum ayari olarak gelir (duz SQL,
-- psql'e ozgu sozdizimi yok -- testler ayni dosyayi psycopg ile calistirir):
--   SET vasi.bot_rol = 'vasi_bot';  SET vasi.sahip_rol = 'denetim_sahibi';
--   SET vasi.bot_parola = '...';
-- scripts/postgres/kurulum.sh bunlari verir. Tekrar calistirmak guvenlidir:
-- var olani bozmaz, eksigi tamamlar, sonradan verilmis fazla yetkiyi geri alir.

BEGIN;

-- Bu oturum yalnizca sistem katalogundaki fonksiyonlari kullanir.
-- Bagimsiz inceleme (Ekim 2026): bot 'public'te kendi format() ya da
-- pg_has_role() fonksiyonunu kurabiliyordu; bu dosya super kullanici
-- olarak yeniden calistirilinca onun yerine botunki cagriliyor ve bot
-- kendini super kullanici yapiyordu (CVE-2018-1058 ile ayni sinif).
-- Artik bot 'public'te nesne de kuramaz (asagida); bu satir yine de durur.
SET LOCAL search_path = pg_catalog, pg_temp;

-- ── Hesaplar ────────────────────────────────────────────────────────────
DO $kur$
DECLARE
    bot    text := pg_catalog.current_setting('vasi.bot_rol', true);
    sahip  text := pg_catalog.current_setting('vasi.sahip_rol', true);
    parola text := pg_catalog.current_setting('vasi.bot_parola', true);
BEGIN
    IF coalesce(bot, '') = '' OR coalesce(sahip, '') = '' OR coalesce(parola, '') = '' THEN
        RAISE EXCEPTION 'vasi.bot_rol, vasi.sahip_rol ve vasi.bot_parola verilmeli';
    END IF;
    IF bot = sahip THEN
        RAISE EXCEPTION 'bot ve sahip ayni hesap olamaz: %', bot;
    END IF;
    IF bot = current_user OR sahip = current_user THEN
        RAISE EXCEPTION 'bot/sahip hesabi bu dosyayi calistiran super kullanici olamaz: %', current_user;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = sahip) THEN
        EXECUTE pg_catalog.format('CREATE ROLE %I NOLOGIN', sahip);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = bot) THEN
        EXECUTE pg_catalog.format('CREATE ROLE %I LOGIN', bot);
    END IF;

    -- Var olan hesap da olmasi gereken haline getirilir: biri onu super
    -- kullanici yaptiysa bu calistirma geri alir.
    EXECUTE pg_catalog.format('ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                              'NOREPLICATION NOBYPASSRLS', sahip);
    EXECUTE pg_catalog.format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                              'NOREPLICATION NOBYPASSRLS PASSWORD %L', bot, parola);
    -- Bot, sahibin yetkilerine hicbir yoldan ulasmamali. Dogrudan uyelik
    -- geri alinir; dolayli bir uyelik (bot -> X -> sahip) kalirsa kurulum
    -- DURUR: hangi baglantinin koparilacagina insan karar vermeli.
    IF EXISTS (SELECT FROM pg_catalog.pg_auth_members m
                 JOIN pg_catalog.pg_roles r ON r.oid = m.roleid
                 JOIN pg_catalog.pg_roles u ON u.oid = m.member
                WHERE r.rolname = sahip AND u.rolname = bot) THEN
        EXECUTE pg_catalog.format('REVOKE %I FROM %I', sahip, bot);
    END IF;
    IF pg_catalog.pg_has_role(bot, sahip, 'MEMBER') THEN
        RAISE EXCEPTION 'bot (%) sahip hesabina (%) dolayli olarak uye: bu uyeligi elle kaldir', bot, sahip;
    END IF;
END
$kur$;

-- ── Tanik tablosu ve yalnizca-ekleme kurali ────────────────────────────
CREATE TABLE IF NOT EXISTS public.denetim_zinciri (
    sira     BIGINT      PRIMARY KEY CHECK (sira > 0),
    ozet     TEXT        NOT NULL CHECK (ozet ~ '^[0-9a-f]{32}$'),
    govde    TEXT        NOT NULL,
    yazildi  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.denetim_zinciri_yalnizca_ekleme() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'denetim_zinciri yalnizca ekleme kabul eder: % reddedildi', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS denetim_zinciri_degismez ON public.denetim_zinciri;
CREATE TRIGGER denetim_zinciri_degismez
    BEFORE UPDATE OR DELETE ON public.denetim_zinciri
    FOR EACH ROW EXECUTE FUNCTION public.denetim_zinciri_yalnizca_ekleme();

DROP TRIGGER IF EXISTS denetim_zinciri_bosaltilamaz ON public.denetim_zinciri;
CREATE TRIGGER denetim_zinciri_bosaltilamaz
    BEFORE TRUNCATE ON public.denetim_zinciri
    FOR EACH STATEMENT EXECUTE FUNCTION public.denetim_zinciri_yalnizca_ekleme();

-- ── Sahiplik ve yetkiler ───────────────────────────────────────────────
DO $yetki$
DECLARE
    bot   text := pg_catalog.current_setting('vasi.bot_rol', true);
    sahip text := pg_catalog.current_setting('vasi.sahip_rol', true);
    t     text;
    kalan text;
BEGIN
    -- Tabloyu dusurmek, kurali kapatmak, sahipligi devretmek SAHIBE aittir.
    EXECUTE pg_catalog.format('ALTER TABLE public.denetim_zinciri OWNER TO %I', sahip);
    EXECUTE pg_catalog.format(
        'ALTER FUNCTION public.denetim_zinciri_yalnizca_ekleme() OWNER TO %I', sahip);

    -- Bot okur ve ekler; kayit zamanini (yazildi) veritabani yazar, bot degil.
    REVOKE ALL ON public.denetim_zinciri FROM PUBLIC;
    EXECUTE pg_catalog.format('REVOKE ALL ON public.denetim_zinciri FROM %I', bot);
    EXECUTE pg_catalog.format('GRANT SELECT ON public.denetim_zinciri TO %I', bot);
    EXECUTE pg_catalog.format(
        'GRANT INSERT (sira, ozet, govde) ON public.denetim_zinciri TO %I', bot);

    -- Botun kendi semasi, kendi adiyla: arama yolundaki "$user" ona denk
    -- gelir, bot tablolarini ad nitelemeden kurar ve bulur. 'public'te
    -- nesne KURAMAZ: oraya kurdugu bir fonksiyon, super kullanicinin elle
    -- actigi bir oturumda onun yetkisiyle calisabilirdi.
    EXECUTE pg_catalog.format('CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I', bot, bot);
    EXECUTE pg_catalog.format('REVOKE CREATE ON SCHEMA public FROM %I', bot);
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    EXECUTE pg_catalog.format('GRANT USAGE ON SCHEMA public TO %I', bot);

    -- Onceki kurulumdan 'public'te kalan tablolar super kullanicinindi:
    -- botun semasina tasinir ve bota devredilir (dizinleri ve SERIAL
    -- dizileri tabloyla birlikte gider).
    FOREACH t IN ARRAY ARRAY['ai_memory', 'rag_chunks', 'sovereign_izleri'] LOOP
        IF pg_catalog.to_regclass('public.' || t) IS NOT NULL THEN
            EXECUTE pg_catalog.format('ALTER TABLE public.%I SET SCHEMA %I', t, bot);
        END IF;
        IF pg_catalog.to_regclass(pg_catalog.format('%I.%I', bot, t)) IS NOT NULL THEN
            EXECUTE pg_catalog.format('ALTER TABLE %I.%I OWNER TO %I', bot, t, bot);
        END IF;
    END LOOP;

    -- 'public'te botun sahip oldugu bir sey kalmamali (fonksiyon, operator,
    -- tablo, tur). Kaldiysa kurulum DURUR: once ne oldugu incelenmeli.
    SELECT pg_catalog.string_agg(ad, ', ') INTO kalan FROM (
        SELECT p.oid::regprocedure::text AS ad
          FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid = p.proowner
         WHERE p.pronamespace = 'public'::regnamespace AND r.rolname = bot
        UNION ALL
        SELECT o.oid::regoperator::text
          FROM pg_catalog.pg_operator o JOIN pg_catalog.pg_roles r ON r.oid = o.oprowner
         WHERE o.oprnamespace = 'public'::regnamespace AND r.rolname = bot
        UNION ALL
        SELECT c.oid::regclass::text
          FROM pg_catalog.pg_class c JOIN pg_catalog.pg_roles r ON r.oid = c.relowner
         WHERE c.relnamespace = 'public'::regnamespace AND r.rolname = bot
        UNION ALL
        SELECT ty.oid::regtype::text
          FROM pg_catalog.pg_type ty JOIN pg_catalog.pg_roles r ON r.oid = ty.typowner
         WHERE ty.typnamespace = 'public'::regnamespace AND r.rolname = bot
           AND ty.typrelid = 0
    ) x;
    IF kalan IS NOT NULL THEN
        RAISE EXCEPTION 'bot (%) public semasinda nesne sahibi: %. Incele ve kaldir.', bot, kalan;
    END IF;
END
$yetki$;

COMMIT;
