"""Denetim izinin ikinci tanigi: zincirin veritabanindaki kopyasi.

NEDEN VAR: Dosya tek basina, bot DURURKEN yapilan degisikligi
yakalayamaz (tests/test_audit_chain.py, test_SINIR_...). 3 Ekim 2026'da
canli yasandi: bot dururken eski bir yedek geri kondu ve iz "1 halka,
saglam" dedi. 22:16'daki bir denetim ve yazicinin kendi mudahale kaydi
iz birakmadan gitmisti. Veritabanindaki parmak izi sayaci ve Docker'in
logu o denetimi hatirliyordu; iz hatirlamiyordu.

NE SAKLAR: her halkanin sirasini, ozetini ve govdesini -- dosyadaki
satirin ta kendisini (ozet alani haric). Boylece dosyadan silinen bir
satirin NE oldugu da soylenebilir. Govde, dosyadakiyle ayni satirdir:
kimlik maskeli, sohbet icerigi yok.

YALNIZCA EKLEME: tablo UPDATE, DELETE ve TRUNCATE'i reddeder
(tetikleyici). Bu kural tek basina KAZALARA karsidir, tablonun sahibine
degil: Ekim 2026'ya kadar bot veritabanina tablonun sahibi (super
kullanici) olarak baglaniyordu. DROP TABLE tabloyu tetikleyicileriyle
birlikte goturuyordu; sahip tetikleyicileri de kapatabiliyordu. Bagimsiz
bir inceleme bunu 4 Ekim'de tek komutla gosterdi; "Gunlukler Yalan
Soyleyebilir mi?" videosunda iki deneme bununla yapildi.

AYRI HESAP (Ekim 2026): bot artik ayri, super olmayan bir hesapla
baglanir. Tanik tablosunun ve kuralin sahibi giris yapamayan baska bir
hesaptir; botun tanikta yalnizca SELECT ve INSERT yetkisi vardir. Tabloyu
kurmak, dusurmek, kurali kapatmak botun elinde DEGIL: kurulum super
kullanicinin isidir (scripts/postgres/tanik.sql). Bu dosyada sema yok.
yetki_durumu() botun gercekte hangi yetkiyle baglandigini OLCER: kurulum
yapilmamissa /saglik bunu soyler.

Algilama yine de yerinde: tanigin dogum kaydi dosyada
(audit_chain: denetim_tanigi_baslangici). Tanik silinir, bosaltilir ya
da basi kesilirse yazici bunu ize alarm olarak yazar; karsilastirma o
halkalari 'tanık sıfırlanmış' diye gosterir. Bot calisirken tablo
silinirse bot onu YENIDEN KURMAZ (kuramaz): kaydet() 'tablo_yok' der,
yazici alarmi yazar ve halkalari bellekte bekletir; tablo kurulum
betigiyle geri gelince sirayla yazar. Alarmla birlikte yeni bir dogum
kaydi yazilir: sonraki acilislar ayni sifirlamayi yeniden bildirmez.

AYNI MAKINENIN SINIRLARI (ikinci bagimsiz inceleme, 5 Ekim): dosyaya VE
veritabanina birlikte yazabilen biri yakalanmaz. Ayri hesap bu kisiyi
daraltir: botu ele geciren artik tanigi silemez, kurali kapatamaz. Ama
makineye ve veritabaninin super kullanicisina erisen biri (orn. `docker
compose exec postgres psql`) hala ikisini birlikte eski bir haline
dondurebilir ya da ikisine birden bir onay satiri ekleyebilir (onay
anahtarsizdir). Siradaki adim: zincirin ucunu makine disina capalamak.

KATMAN: audit_chain veritabanini bilmez; yazici bu nesneyi disaridan
alir (ZincirliDosyaYazicisi.tanik_bagla). Bu dosya veritabanini bilir.
audit_chain'i yalnizca komut satiri (main) kullanir -- iki kopyayi yan
yana koymak icin.

    docker compose exec vasi-core python -m audit_store
"""
import os
import sys

from memory import _connect as _db_baglan
from memory import is_configured as db_yapilandirildi

TABLO_YOK = "42P01"     # PostgreSQL sqlstate: undefined_table

# Sema adi her sorguda acikca yazilir: oturumun kendi gecici semasinda
# (pg_temp) ayni adla acilmis bir tablo, nitelenmemis bir sorguda
# gercek tanigin onune gecerdi.
TABLO = "public.denetim_zinciri"

# yetki_durumu() sonuclari
YALNIZCA_EKLEME = "yalnizca_ekleme"    # olmasi gereken: okur ve ekler, baska hicbir sey
FAZLA_YETKI = "fazla_yetki"            # super kullanici, sahip/sahibe uye, silme/degistirme...
EKSIK_YETKI = "eksik_yetki"            # ekleyemiyor ya da okuyamiyor
KURAL_EKSIK = "kural_eksik"            # yalnizca-ekleme kurali kapali/eksik ya da sahip giris yapabiliyor
TABLO_KURULMAMIS = "tablo_yok"         # tablo yok: kurulum betigi calismamis ya da tablo silinmis

TETIKLEYICILER = ("denetim_zinciri_degismez", "denetim_zinciri_bosaltilamaz")

# Her fonksiyon pg_catalog ile nitelenir: botun kendi semasindaki ayni
# adli bir fonksiyon olcumun yerine gecmesin.
YETKI_SORGUSU = """
SELECT r.rolsuper,
       c.oid IS NOT NULL,
       coalesce(pg_catalog.pg_has_role(r.oid, c.relowner, 'MEMBER'), false),
       c.oid IS NOT NULL
           AND pg_catalog.has_column_privilege(c.oid, 'sira', 'INSERT')
           AND pg_catalog.has_column_privilege(c.oid, 'ozet', 'INSERT')
           AND pg_catalog.has_column_privilege(c.oid, 'govde', 'INSERT'),
       c.oid IS NOT NULL AND pg_catalog.has_table_privilege(c.oid, 'SELECT'),
       c.oid IS NOT NULL AND (pg_catalog.has_table_privilege(c.oid, 'DELETE')
                              OR pg_catalog.has_table_privilege(c.oid, 'TRUNCATE')
                              OR pg_catalog.has_any_column_privilege(c.oid, 'UPDATE')),
       c.oid IS NOT NULL AND pg_catalog.has_column_privilege(c.oid, 'yazildi', 'INSERT'),
       pg_catalog.has_schema_privilege('public', 'CREATE'),
       (SELECT count(*) FROM pg_catalog.pg_trigger t
         WHERE t.tgrelid = c.oid AND t.tgname = ANY(%s) AND t.tgenabled = 'O'),
       (SELECT o.rolcanlogin FROM pg_catalog.pg_roles o WHERE o.oid = c.relowner),
       current_user
  FROM pg_catalog.pg_roles r
  LEFT JOIN pg_catalog.pg_class c ON c.oid = pg_catalog.to_regclass(%s)
 WHERE r.rolname = current_user
"""


def yetki_durumu() -> tuple[str, str]:
    """(durum, aciklama): botun tanik uzerindeki GERCEK yetkisi.

    Tahmin degil olcum: veritabanina botun kendi hesabiyla sorulur.
    Kurulum betigi calistirilmadan once bot super kullanicidir ve bu
    fonksiyon FAZLA_YETKI der. Sahiplik dolayli uyelikle de olculur:
    sahibe (bir ara hesap uzerinden bile) uye olan bot, SET ROLE ile
    sahip olabilir (bagimsiz inceleme, Ekim 2026).
    """
    with _db_baglan() as conn:
        satir = conn.execute(YETKI_SORGUSU, (list(TETIKLEYICILER), TABLO)).fetchone()
    (superk, var, sahibe_uye, ekler, okur, siler, zaman_yazar, public_kurar,
     acik_kural, sahip_giris, hesap) = satir
    if superk:
        return FAZLA_YETKI, f"bot süper kullanıcı ({hesap}): tanığı silebilir"
    if not var:
        return TABLO_KURULMAMIS, "tanık tablosu yok (kurulum betiği çalışmamış ya da tablo silinmiş)"
    sahip = sahibe_uye
    if sahip:
        return FAZLA_YETKI, (f"bot tanığın sahibi ya da sahibine üye ({hesap}): "
                             f"tabloyu düşürebilir, kuralı kapatabilir")
    if siler:
        return FAZLA_YETKI, f"bot tanıkta silme/değiştirme yetkili ({hesap})"
    if zaman_yazar:
        return FAZLA_YETKI, f"bot tanığın kayıt zamanını kendisi yazabilir ({hesap})"
    if public_kurar:
        return FAZLA_YETKI, f"bot 'public' şemasında nesne kurabilir ({hesap})"
    if acik_kural != len(TETIKLEYICILER):
        return KURAL_EKSIK, "tanığın yalnızca-ekleme kuralı kapalı ya da eksik"
    if sahip_giris:
        return KURAL_EKSIK, "tanığın sahibi giriş yapabilen bir hesap"
    if not (ekler and okur):
        return EKSIK_YETKI, f"bot tanığa yazamıyor ya da okuyamıyor ({hesap})"
    return YALNIZCA_EKLEME, f"bot yalnızca ekleyebilir ({hesap})"


def _tablo_yok(hata: Exception) -> bool:
    return getattr(hata, "sqlstate", None) == TABLO_YOK


class VeritabaniTanigi:
    """audit_chain.ZincirliDosyaYazicisi'nin bekledigi tanik.

    Her cagri kendi baglantisini acar ve kapatir: denetim olaylari
    seyrek (komut basina bir), surekli acik bir baglanti burada
    kazandirdigindan fazlasini -- kopan baglanti yonetimini -- getirir.
    """

    def ilk_sira(self):
        """Tanigin en eski halkasi -- tanik bossa ya da tablo yoksa None."""
        try:
            with _db_baglan() as conn:
                satir = conn.execute(f"SELECT min(sira) FROM {TABLO}").fetchone()
        except Exception as e:
            if _tablo_yok(e):
                return None
            raise
        return int(satir[0]) if satir and satir[0] is not None else None

    def son_halka(self):
        """(sira, ozet) -- tanik bossa ya da tablo henuz yoksa None."""
        try:
            with _db_baglan() as conn:
                satir = conn.execute(
                    f"SELECT sira, ozet FROM {TABLO} ORDER BY sira DESC LIMIT 1"
                ).fetchone()
        except Exception as e:
            if _tablo_yok(e):
                return None
            raise
        return (int(satir[0]), satir[1]) if satir else None

    def kaydet(self, sira: int, ozet: str, govde: str) -> str:
        """'yazildi' | 'ayni' (zaten vardi, birebir) | 'catal' (ayni sira, baska halka)
        | 'tablo_yok' (yazilamadi: tablo yok).

        Catal, ilk yazilani EZMEZ: tanik ilk gordugunu soyler.

        'tablo_yok': bot tabloyu YENIDEN KURMAZ. Kurmak super kullanicinin
        isi (scripts/postgres/tanik.sql); bot kurabilseydi, kurdugu
        tablonun sahibi olur ve onu yeniden dusurebilirdi. Tanik daha once
        tutulmaya baslamissa tablo SILINMIS demektir -- yazici bunu ize
        alarm olarak yazar ve halkalari tablo donene kadar bekletir.
        """
        try:
            return self._kaydet(sira, ozet, govde)
        except Exception as e:
            if _tablo_yok(e):
                return TABLO_KURULMAMIS
            raise

    def _kaydet(self, sira: int, ozet: str, govde: str) -> str:
        with _db_baglan() as conn:
            yazildi = conn.execute(
                f"INSERT INTO {TABLO} (sira, ozet, govde) VALUES (%s, %s, %s) "
                "ON CONFLICT (sira) DO NOTHING RETURNING sira",
                (sira, ozet, govde),
            ).fetchone()
            if yazildi:
                return "yazildi"
            mevcut = conn.execute(
                f"SELECT ozet, govde FROM {TABLO} WHERE sira = %s", (sira,)
            ).fetchone()
        return "ayni" if mevcut and tuple(mevcut) == (ozet, govde) else "catal"

    def halkalar(self) -> list:
        """[(sira, ozet, govde, yazildi), ...] sira sirasiyla."""
        try:
            with _db_baglan() as conn:
                satirlar = conn.execute(
                    f"SELECT sira, ozet, govde, yazildi FROM {TABLO} ORDER BY sira"
                ).fetchall()
        except Exception as e:
            if _tablo_yok(e):
                return []
            raise
        return [(int(s), o, g, y) for s, o, g, y in satirlar]


def main(argv=None) -> int:
    """0: iki tanik uyusuyor, dosya temiz · 1: sorun var · 2: karsilastirilamadi"""
    import audit_chain

    args = sys.argv[1:] if argv is None else argv
    yol = args[0] if args else os.getenv("AUDIT_LOG_FILE", "/app/denetim/denetim.log")
    if not db_yapilandirildi():
        print("PostgreSQL yapılandırılmamış: ikinci tanık yok.")
        return 2
    dosyalar = audit_chain.dosyalari_sirala(yol)
    if not dosyalar:
        print(f"Dosya bulunamadı: {yol}")
        return 2
    try:
        halkalar = VeritabaniTanigi().halkalar()
    except Exception as e:
        print(f"Tanık okunamadı: {e}")
        return 2
    dosya_r = audit_chain.dogrula_dosyalar(dosyalar)
    # Botla ayni yedek sayisi: rotasyonla gitmis olmasi gerekenleri tanik
    # kendi donme kayitlarindan sayar (vasi.LOG_BACKUP_COUNT ile ayni ortam degiskeni).
    k, tanik_r = audit_chain.iki_tanigi_karsilastir(
        dosya_r, halkalar, yedek_sayisi=int(os.getenv("LOG_BACKUP_COUNT", "5")))
    print(audit_chain.karsilastirma_metni(k, dosya_r, tanik_r))
    return 0 if (k.uyusuyor and tanik_r.saglam and dosya_r.temiz) else 1


if __name__ == "__main__":
    sys.exit(main())
