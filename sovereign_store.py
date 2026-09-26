"""Sapma denetcisinin hafizasi.

NEDEN AYRI DOSYA: sovereign.py hicbir yerel modulu import etmez ve
hicbir servise bagli degildir. Oyle kalmali -- denetci, denetledigi
hicbir seye bagimli olmamali, yoksa bozulan bir bilesen denetciyi de
sessize alir.

Kalicilik ayri bir is. Bu dosya veritabanina bagli; sovereign.py degil.
Boylece denetim mantigi PostgreSQL olmadan da test edilebiliyor -- ve
denetim, veritabani duserse calismaya devam ediyor.

NE SAKLAR: her denetimde alinan parmak izini ve zamanini. Bir sonraki
denetim bununla karsilastirilir. Icerik degil OZET saklanir; uzun
alanlar sha256 ile kisaltilir.
"""
import json
import logging
from datetime import datetime

from memory import MemoryError_ as DbHatasi
from memory import _connect as _db_baglan
from memory import is_configured as db_yapilandirildi

logger = logging.getLogger("vasi")

SEMA = """
CREATE TABLE IF NOT EXISTS sovereign_izleri (
    id          SERIAL PRIMARY KEY,
    olusturuldu TIMESTAMPTZ NOT NULL DEFAULT now(),
    parmak_izi  JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS sovereign_izleri_zaman
    ON sovereign_izleri (olusturuldu DESC);
"""


def init_schema() -> None:
    """Tabloyu ve indeksi olusturur. Zaten varsa dokunmaz."""
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(SEMA)
        conn.commit()
    logger.info("🛡️ Sovereign iz semasi hazir")


def son_iz() -> tuple[dict, datetime] | None:
    """En son kaydedilen parmak izi ve zamani. Kayit yoksa None."""
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT parmak_izi, olusturuldu FROM sovereign_izleri "
                "ORDER BY olusturuldu DESC LIMIT 1"
            )
            satir = cur.fetchone()
    if not satir:
        return None
    izi, zaman = satir
    return (izi if isinstance(izi, dict) else json.loads(izi)), zaman


def kaydet(izi: dict) -> None:
    """Yeni parmak izini yazar.

    Her denetimde yazilir: bir degisiklik BIR KEZ raporlanir, sonra
    yeni normal olur. Bu bilincli bir tercih -- her denetimde ayni
    uyariyi tekrarlayan bir sistem okunmaz hale gelir.

    Kayit kaybolmaz: her fark ayrica denetim gunlugune yazilir. Taban
    cizgisi ilerler, gecmis durur.
    """
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sovereign_izleri (parmak_izi) VALUES (%s)",
                (json.dumps(izi, ensure_ascii=False, sort_keys=True),),
            )
        conn.commit()


def temizle(saklanacak: int = 200) -> int:
    """Eski izleri budar. Silinen satir sayisini dondurur.

    Tablo sinirsiz buyumemeli: her denetim bir satir yaziyor.
    """
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM sovereign_izleri WHERE id NOT IN ("
                "  SELECT id FROM sovereign_izleri "
                "  ORDER BY olusturuldu DESC LIMIT %s)",
                (saklanacak,),
            )
            silinen = cur.rowcount
        conn.commit()
    return silinen


def health() -> tuple[str, str]:
    """(durum, detay) dondurur."""
    if not db_yapilandirildi():
        return "warn", "PostgreSQL yok; zaman içinde sapma izlenmiyor"
    try:
        with _db_baglan() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM sovereign_izleri")
                (adet,) = cur.fetchone()
        return "ok", f"{adet} denetim izi kayıtlı"
    except DbHatasi as e:
        return "error", str(e)
    except Exception as e:
        return "error", f"iz tablosu okunamadı: {e}"