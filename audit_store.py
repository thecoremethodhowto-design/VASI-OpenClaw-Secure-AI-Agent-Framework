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
(tetikleyici). Bu kural KAZALARA karsidir, tablonun sahibine degil: bot
veritabanina tablonun sahibi (resmi postgres imajinda super kullanici)
olarak baglaniyor. DROP TABLE tabloyu tetikleyicileriyle birlikte
goturur; super kullanici tetikleyicileri devre disi da birakabilir.
Bagimsiz bir inceleme bunu 4 Ekim'de tek komutla gosterdi.

O yuzden asil koruma ALGILAMA: tanigin dogum kaydi dosyada
(audit_chain: denetim_tanigi_baslangici). Tanik silinir, bosaltilir ya
da basi kesilirse yazici bunu ize alarm olarak yazar; karsilastirma o
halkalari 'tanık sıfırlanmış' diye gosterir. Bot calisirken silinen
tablo bir sonraki yazimda yeniden kurulur ve kaydet() bunu 'kuruldu'
diye soyler. Alarmla birlikte yeni bir dogum kaydi yazilir: sonraki
acilislar ayni sifirlamayi yeniden bildirmez.

AYNI MAKINENIN SINIRLARI (ikinci bagimsiz inceleme, 5 Ekim): dosyaya VE
veritabanina birlikte yazabilen biri yakalanmaz. Ikisini birlikte
yeniden yazabilir; daha ucuzu, ikisini birlikte eski bir haline
dondurebilir (dosyayi tanik oncesine kesip tabloyu silmek "ilk
kurulum"dan ayirt edilemez) ya da ikisine birden bir onay satiri
ekleyebilir (onay anahtarsizdir). Siradaki adim: taniga yalnizca ekleme
yetkisi olan ayri bir hesap ve zincirin ucunu makine disina capalamak.

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

SEMA = """
CREATE TABLE IF NOT EXISTS denetim_zinciri (
    sira     BIGINT      PRIMARY KEY CHECK (sira > 0),
    ozet     TEXT        NOT NULL CHECK (ozet ~ '^[0-9a-f]{32}$'),
    govde    TEXT        NOT NULL,
    yazildi  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION denetim_zinciri_yalnizca_ekleme() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'denetim_zinciri yalnizca ekleme kabul eder: % reddedildi', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS denetim_zinciri_degismez ON denetim_zinciri;
CREATE TRIGGER denetim_zinciri_degismez
    BEFORE UPDATE OR DELETE ON denetim_zinciri
    FOR EACH ROW EXECUTE FUNCTION denetim_zinciri_yalnizca_ekleme();

DROP TRIGGER IF EXISTS denetim_zinciri_bosaltilamaz ON denetim_zinciri;
CREATE TRIGGER denetim_zinciri_bosaltilamaz
    BEFORE TRUNCATE ON denetim_zinciri
    FOR EACH STATEMENT EXECUTE FUNCTION denetim_zinciri_yalnizca_ekleme();
"""


def _tablo_yok(hata: Exception) -> bool:
    return getattr(hata, "sqlstate", None) == TABLO_YOK


def init_schema() -> None:
    """Tabloyu ve tetikleyicileri kurar. Tekrar calistirilabilir."""
    with _db_baglan() as conn:
        conn.execute(SEMA)


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
                satir = conn.execute("SELECT min(sira) FROM denetim_zinciri").fetchone()
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
                    "SELECT sira, ozet FROM denetim_zinciri ORDER BY sira DESC LIMIT 1"
                ).fetchone()
        except Exception as e:
            if _tablo_yok(e):
                return None
            raise
        return (int(satir[0]), satir[1]) if satir else None

    def kaydet(self, sira: int, ozet: str, govde: str) -> str:
        """'yazildi' | 'ayni' (zaten vardi, birebir) | 'catal' (ayni sira, baska halka)
        | 'kuruldu' (tablo yoktu: kuruldu ve yazildi).

        Catal, ilk yazilani EZMEZ: tanik ilk gordugunu soyler. 'kuruldu'
        ilk kurulumda olagan; tanik daha once tutulmaya baslamissa tablo
        SILINMIS demektir -- yazici bunu ize alarm olarak yazar.
        """
        try:
            return self._kaydet(sira, ozet, govde)
        except Exception as e:
            if not _tablo_yok(e):
                raise
        init_schema()           # sema baslangicta kurulamadiysa ya da tablo silindiyse
        sonuc = self._kaydet(sira, ozet, govde)
        return "kuruldu" if sonuc == "yazildi" else sonuc

    def _kaydet(self, sira: int, ozet: str, govde: str) -> str:
        with _db_baglan() as conn:
            yazildi = conn.execute(
                "INSERT INTO denetim_zinciri (sira, ozet, govde) VALUES (%s, %s, %s) "
                "ON CONFLICT (sira) DO NOTHING RETURNING sira",
                (sira, ozet, govde),
            ).fetchone()
            if yazildi:
                return "yazildi"
            mevcut = conn.execute(
                "SELECT ozet, govde FROM denetim_zinciri WHERE sira = %s", (sira,)
            ).fetchone()
        return "ayni" if mevcut and tuple(mevcut) == (ozet, govde) else "catal"

    def halkalar(self) -> list:
        """[(sira, ozet, govde, yazildi), ...] sira sirasiyla."""
        try:
            with _db_baglan() as conn:
                satirlar = conn.execute(
                    "SELECT sira, ozet, govde, yazildi FROM denetim_zinciri ORDER BY sira"
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
