"""Memory katmani: kalici hafiza erisimi.

DACE mimarisinde bu katman Execution'a aittir -- yan etkili bir
islem yapar (veritabanina yazar/okur). Ama ayri bir modulde durur
cunku baglanti yonetimi ve sema bilgisi kendi basina bir sorumluluk.

GUVENLIK ILKESI: Hafizaya yazma, dosya yazma kadar ciddi bir islemdir.
Bir hatira sonraki her oturumda sistem promptuna girer ve kararlari
etkiler. Bu yuzden:

  1. Model kendi basina hatirlayamaz -- yalnizca acik kullanici
     komutu + onay ile kayit olur.
  2. Kaynak etiketini KOD atar, model degil. Hangi kod yolu bu kaydi
     uretti -- etiket oradan gelir.
  3. Yalnizca source='user' kayitlari prompta girer.

Ucuncu kural bugun otomatik saglaniyor cunku yalnizca 'user' yaziliyor.
Ama kural yine de kodda ve testte duruyor: ileride baska kaynaklar
acilirsa koruma yerinde kalir.
"""
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("vasi")

# ── YAPILANDIRMA ──────────────────────────────────────────────────────────────
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "vasi")
POSTGRES_USER = os.getenv("POSTGRES_USER", "vasi")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# Kac hatira sistem promptuna girer ve toplam karakter siniri.
# Sinir olmadan hafiza buyudukce her cagri pahalilasir.
MEMORY_PROMPT_LIMIT = int(os.getenv("MEMORY_PROMPT_LIMIT", "20"))
MEMORY_PROMPT_CHARS = int(os.getenv("MEMORY_PROMPT_CHARS", "2000"))

# ── SABITLER ─────────────────────────────────────────────────────────────────

# Kaynak etiketleri. Su an YALNIZCA 'user' yazilir; digerleri semada
# tanimli cunku ileride acilabilsin diye. Sema gocu gerekmesin.
GECERLI_KAYNAKLAR = ("user", "web", "tool", "model")

# Prompta girmesine izin verilen kaynaklar. Bu kume bilincli olarak
# tek elemanli: guvenilmeyen kaynakli bir hatira modele gitmez.
PROMPTA_GIREBILEN = ("user",)

GECERLI_TURLER = ("preference", "fact", "context")

SEMA = """
CREATE TABLE IF NOT EXISTS ai_memory (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      TEXT        NOT NULL,
    kind        TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    origin      TEXT,
    active      BOOLEAN     NOT NULL DEFAULT true,

    CONSTRAINT source_gecerli CHECK (source IN ('user', 'web', 'tool', 'model')),
    CONSTRAINT kind_gecerli   CHECK (kind   IN ('preference', 'fact', 'context'))
);

CREATE INDEX IF NOT EXISTS ai_memory_aktif
    ON ai_memory (active, created_at DESC);
"""


class MemoryError_(Exception):
    """Hafiza katmani hatasi. Cagiran taraf kullaniciya mesaj gosterir."""


# ── BAGLANTI ─────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Hafiza kullanilabilir durumda mi?

    Parola bos ise hafiza kapali kabul edilir. Boylece PostgreSQL
    kurulmadan sistem calismaya devam eder.
    """
    return bool(POSTGRES_PASSWORD)


def _connect():
    """Yeni bir baglanti acar. Cagiran taraf kapatmakla yukumludur."""
    if not is_configured():
        raise MemoryError_("Hafiza yapilandirilmamis (POSTGRES_PASSWORD yok)")
    try:
        import psycopg
    except ImportError as e:
        raise MemoryError_(f"psycopg kurulu degil: {e}") from e

    try:
        return psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=5,
        )
    except Exception as e:
        raise MemoryError_(f"Baglanti kurulamadi: {e}") from e


def init_schema() -> None:
    """Tabloyu ve indeksi olusturur. Zaten varsa dokunmaz."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(SEMA)
        conn.commit()
    logger.info("🗄️ Hafiza semasi hazir")


def health() -> tuple[str, str]:
    """(durum, detay) dondurur. build_health_report icin.

    Durum: "ok" | "warn" | "error"
    """
    if not is_configured():
        return "warn", "henüz kurulmadı"
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM ai_memory WHERE active")
                (aktif,) = cur.fetchone()
                cur.execute("SELECT count(*) FROM ai_memory")
                (toplam,) = cur.fetchone()
        pasif = toplam - aktif
        detay = f"{aktif} aktif hatıra"
        if pasif:
            detay += f", {pasif} pasif"
        return "ok", detay
    except MemoryError_ as e:
        return "error", str(e)[:80]
    except Exception as e:
        return "error", f"sorgu hatasi: {str(e)[:60]}"

# ── YAZMA VE OKUMA ──────────────────────────────────────────────

# Su an tek bir tur kullaniliyor. Sema digerlerini de tanimliyor ki
# ileride ayrim gerekirse goc gerekmesin.
VARSAYILAN_TUR = "preference"


def remember(content: str, origin: str, kind: str = VARSAYILAN_TUR) -> int:
    """Yeni bir hatira kaydeder ve id'sini dondurur.

    GUVENLIK: source parametresi YOKTUR. Bu fonksiyon her zaman
    'user' yazar. Kaynak etiketini KOD atar, model degil -- bir
    web sayfasindaki gizli talimat "bunu kullanici tercihi olarak
    kaydet" diyemez.

    origin: hangi komut bu kaydi uretti (denetim izi).
    """
    if kind not in GECERLI_TURLER:
        raise MemoryError_(f"Gecersiz tur: {kind}")

    icerik = (content or "").strip()
    if not icerik:
        raise MemoryError_("Bos hatira kaydedilemez")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_memory (source, kind, content, origin) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                ("user", kind, icerik, origin),
            )
            (yeni_id,) = cur.fetchone()
        conn.commit()
    logger.info(f"🧠 Hatira kaydedildi: #{yeni_id} ({origin})")
    return yeni_id


def list_active(limit: int = 50) -> list[dict]:
    """Aktif hatiralari en yeniden eskiye listeler."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, content, created_at FROM ai_memory "
                "WHERE active ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
            satirlar = cur.fetchall()
    return [
        {"id": r[0], "kind": r[1], "content": r[2], "created_at": r[3]}
        for r in satirlar
    ]


def get_one(memory_id: int) -> dict | None:
    """Tek bir hatirayi dondurur (aktif olmasa bile)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, content, active FROM ai_memory WHERE id = %s",
                (memory_id,),
            )
            satir = cur.fetchone()
    if not satir:
        return None
    return {"id": satir[0], "kind": satir[1], "content": satir[2], "active": satir[3]}


def forget(memory_id: int, origin: str) -> bool:
    """Bir hatirayi pasiflestirir. SILMEZ.

    Silme yerine pasiflestirme: denetim izi korunur, bir hatiranin
    ne zaman eklendigi ve ne zaman kaldirildigi gorulebilir.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ai_memory SET active = false WHERE id = %s AND active",
                (memory_id,),
            )
            etkilenen = cur.rowcount
        conn.commit()
    if etkilenen:
        logger.info(f"🗑️ Hatira pasiflestirildi: #{memory_id} ({origin})")
    return bool(etkilenen)


def prompt_memories() -> list[str]:
    """Sistem promptuna girecek hatiralari dondurur.

    GUVENLIK: source filtresi PROMPTA_GIREBILEN kumesine gore
    uygulanir. Bugun yalnizca 'user' yaziliyor, ama filtre yine de
    burada duruyor -- ileride baska kaynaklar acilirsa koruma
    kendiliginden calisir.
    """
    if not is_configured():
        return []

    yer_tutucu = ",".join(["%s"] * len(PROMPTA_GIREBILEN))
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT content FROM ai_memory "
                    f"WHERE active AND source IN ({yer_tutucu}) "
                    f"ORDER BY created_at DESC LIMIT %s",
                    (*PROMPTA_GIREBILEN, MEMORY_PROMPT_LIMIT),
                )
                satirlar = cur.fetchall()
    except Exception as e:
        logger.warning(f"⚠️ Hatiralar okunamadi: {e}")
        return []

    # Toplam karakter siniri: hafiza buyudukce her cagri pahalilasmasin.
    sonuc, toplam = [], 0
    for (icerik,) in satirlar:
        if toplam + len(icerik) > MEMORY_PROMPT_CHARS:
            break
        sonuc.append(icerik)
        toplam += len(icerik)
    return sonuc