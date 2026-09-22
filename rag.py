"""RAG katmani: belge parcalama, gomme (embedding) ve anlamsal arama.

TEMEL ILKE: RAG'i guvenli yapan sey icerigi dislamak degil, icerigin
ne YAPABILECEGINI kisitlamaktir.

Belgeleri dislayamayiz -- RAG'in asil degeri onlari bulmakta. Ama
getirilen bir parca, icinde gizli bir talimat tasiyabilir. Somut yol:

    /ara_senaryo -> Gemini web'de arar -> yerel model senaryo yazar
    -> youtube/senaryolar/ara_senaryo_*.md -> PUBLIC, rag_allowed
    -> indekslenir -> haftalar sonra bir aramada geri gelir

Web'deki bir sayfadaki gizli talimat, dort adim dolasip modelin onune
"senin kendi senaryon" gibi gorunerek gelir. Bu yuzden:

  1. Arama yalnizca acik komutla yapilir (/bul, /sor). Duz sohbette
     otomatik arama YOKTUR.
  2. /sor sirasinda model ARAC CAGIRAMAZ. Getirilen belgedeki bir
     enjeksiyon cevabi etkileyebilir ama dis dunyaya ulasamaz.
  3. Embedding yalnizca YEREL host'ta yapilir. Belge icerigi sirf
     vektore cevrilmek icin makineden cikmaz.
  4. Web kaynakli icerik dislanmaz, ETIKETLENIR.

DEPOLAMA: Mevcut PostgreSQL'de duz REAL[] sutunu, benzerlik Python'da.
pgvector yok -- resmi postgres imaji icermiyor, baska bir yayincinin
imajina gecmek yeni bir tedarik zinciri karari olurdu. Bu olcekte
(birkac bin parca) duz hesap milisaniyeler surer.
"""
import hashlib
import logging
import math
import os
import re
import threading
from pathlib import Path

import requests

from access import WORKSPACE, classify_file, is_local_host, is_rag_allowed
from memory import MemoryError_ as DbHatasi
from memory import _connect as _db_baglan
from memory import is_configured as db_yapilandirildi

logger = logging.getLogger("vasi")

# ── YAPILANDIRMA ──────────────────────────────────────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# bge-m3: Turkce erisim karsilastirmalarinda en yuksek skor, 1024 boyut,
# 8192 token girdi. Ingilizce odakli modeller Turkce gibi eklemeli
# dillerde belirgin sekilde kotu sonuc veriyor.
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "bge-m3")
EMBED_TIMEOUT = int(os.getenv("RAG_EMBED_TIMEOUT", "120"))

CHUNK_MAX_CHARS = int(os.getenv("RAG_CHUNK_MAX_CHARS", "1200"))
SEARCH_TOP_K = int(os.getenv("RAG_SEARCH_TOP_K", "5"))

# /sor icin en dusuk benzerlik. Ilgisiz parca gondermek, modeli bos
# baglamdan cevap uydurmaya iter. Deger bu indekste gozlemlenen
# skorlara gore secildi: ilgili parcalar ~0.60, ilgisizler ~0.35-0.45.
# Kendi verinizde farkli olabilir; /bul ile skorlara bakip ayarlayin.
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.50"))

# Yalnizca metin dosyalari. Ikili dosyalar anlamsiz parcalar uretir.
INDEKSLENEBILIR_UZANTILAR = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".csv"}

# Cok buyuk bir dosya yuzlerce parca ve dakikalarca embedding demek.
RAG_MAX_FILE_BYTES = int(os.getenv("RAG_MAX_FILE_BYTES", str(512 * 1024)))

# Iki /indeksle ayni anda calismasin: yarim kalan bir tarama,
# digerinin eski kayit temizligini bozabilir.
_INDEKS_KILIDI = threading.Lock()

# ── KOKEN ETIKETI ─────────────────────────────────────────────────────────────

# Web aramasi kullanan komutlarin urettigi dosyalar bu onekle baslar.
# Su an yalnizca /ara_senaryo indekslenen bir klasore yaziyor
# (youtube/senaryolar/ara_senaryo_*). /ara_not notlar/'a yazar --
# PRIVATE, hic indekslenmez.
WEB_KAYNAKLI_ONEKLER = ("ara_",)
GECERLI_KOKENLER = ("yerel", "web_kaynakli")

SEMA = """
CREATE TABLE IF NOT EXISTS rag_chunks (
    id              BIGSERIAL   PRIMARY KEY,
    path            TEXT        NOT NULL,
    chunk_index     INTEGER     NOT NULL,
    content         TEXT        NOT NULL,
    embedding       REAL[]      NOT NULL,
    provenance      TEXT        NOT NULL,
    classification  TEXT        NOT NULL,
    content_hash    TEXT        NOT NULL,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT rag_parca_benzersiz UNIQUE (path, chunk_index),
    CONSTRAINT rag_koken_gecerli   CHECK  (provenance IN ('yerel', 'web_kaynakli'))
);

CREATE INDEX IF NOT EXISTS rag_chunks_path ON rag_chunks (path);
"""


class RagHatasi(Exception):
    """RAG katmani hatasi. Cagiran taraf kullaniciya mesaj gosterir."""


# ── SAF FONKSIYONLAR ──────────────────────────────────────────────────────────

def _sert_bol(paragraf: str, max_chars: int) -> list[str]:
    """Siniri asan tek bir paragrafi kelime sinirindan boler."""
    parcalar = []
    while len(paragraf) > max_chars:
        kes = paragraf.rfind(" ", 0, max_chars)
        if kes <= 0:
            kes = max_chars
        parcalar.append(paragraf[:kes].strip())
        paragraf = paragraf[kes:].strip()
    if paragraf:
        parcalar.append(paragraf)
    return parcalar


def chunk_text(metin: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Metni paragraf sinirlarina saygi gosterecek sekilde parcalar.

    Kucuk paragraflar birlestirilir, siniri asan tek paragraf kelime
    sinirindan bolunur. Bos metin bos liste dondurur.
    """
    paragraflar = [p.strip() for p in re.split(r"\n\s*\n", metin or "") if p.strip()]
    parcalar: list[str] = []
    mevcut = ""

    for paragraf in paragraflar:
        if len(paragraf) > max_chars:
            if mevcut:
                parcalar.append(mevcut)
                mevcut = ""
            parcalar.extend(_sert_bol(paragraf, max_chars))
            continue

        aday = f"{mevcut}\n\n{paragraf}" if mevcut else paragraf
        if len(aday) <= max_chars:
            mevcut = aday
        else:
            parcalar.append(mevcut)
            mevcut = paragraf

    if mevcut:
        parcalar.append(mevcut)
    return parcalar


def detect_provenance(yol: str) -> str:
    """Bir dosyanin koken etiketini dondurur: 'yerel' veya 'web_kaynakli'.

    Etiketi dosya YOLU belirler, icerik degil. Icerige bakmak, belgenin
    icindeki bir metnin kendi etiketini degistirmesine izin verirdi --
    hafiza fazindaki "kaynak etiketini kod atar" ilkesinin karsiligi.
    """
    ad = Path(yol).name
    if ad.startswith(WEB_KAYNAKLI_ONEKLER):
        return "web_kaynakli"
    return "yerel"


def normalize(vektor: list[float]) -> list[float]:
    """Vektoru birim uzunluga getirir. Sifir vektor oldugu gibi doner."""
    norm = math.sqrt(sum(x * x for x in vektor))
    if norm == 0:
        return list(vektor)
    return [x / norm for x in vektor]


def cosine(a: list[float], b: list[float]) -> float:
    """Iki vektor arasindaki kosinus benzerligi (-1..1)."""
    if len(a) != len(b):
        raise RagHatasi(f"Boyut uyusmazligi: {len(a)} != {len(b)}")
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def content_hash(metin: str) -> str:
    """Icerik degisti mi? Yeniden indekslemeyi atlamak icin."""
    return hashlib.sha256((metin or "").encode("utf-8")).hexdigest()


# ── EMBEDDING ─────────────────────────────────────────────────────────────────

def embed(metinler: list[str]) -> list[list[float]]:
    """Metinleri vektore cevirir. YALNIZCA yerel host'ta.

    GUVENLIK: OLLAMA_HOST uzak bir adresse embedding REDDEDILIR. Belge
    icerigi sirf vektore cevrilmek icin makineden cikmamali.

    Model cagrilari LiteLLM uzerinden gecer ama embedding dogrudan
    Ollama'ya gider. Bilincli: gateway'deki bir takma ad yapilandirmayla
    bir bulut saglayicisina yonlendirilebilir. Dogrudan cagri, "yerel"
    ozelligini yapilandirmaya degil KODA baglar.
    """
    if not metinler:
        return []

    if not is_local_host(OLLAMA_HOST):
        raise RagHatasi(
            "Embedding yalnızca yerel host'ta yapılır; "
            f"OLLAMA_HOST uzak görünüyor. Belge içeriği makineden çıkmamalı."
        )

    try:
        yanit = requests.post(
            f"{OLLAMA_HOST}/api/embed",
            json={"model": EMBED_MODEL, "input": metinler},
            timeout=EMBED_TIMEOUT,
        )
    except requests.RequestException as e:
        raise RagHatasi(f"Ollama'ya ulaşılamadı: {e}") from e

    if yanit.status_code == 404:
        raise RagHatasi(
            f"Embedding modeli bulunamadı: {EMBED_MODEL}. "
            f"Önce indirin: ollama pull {EMBED_MODEL}"
        )
    if yanit.status_code >= 400:
        raise RagHatasi(f"Embedding hatası ({yanit.status_code}): {yanit.text[:200]}")

    try:
        vektorler = yanit.json()["embeddings"]
    except (KeyError, ValueError) as e:
        raise RagHatasi(f"Beklenmeyen embedding yanıtı: {e}") from e

    if len(vektorler) != len(metinler):
        raise RagHatasi(
            f"Embedding sayısı uyuşmuyor: {len(vektorler)} vektör, {len(metinler)} metin"
        )
    return [normalize(v) for v in vektorler]


# ── VERITABANI ────────────────────────────────────────────────────────────────

def init_schema() -> None:
    """Tabloyu ve indeksi olusturur. Zaten varsa dokunmaz."""
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(SEMA)
        conn.commit()
    logger.info("📚 RAG semasi hazir")


def health() -> tuple[str, str]:
    """(durum, detay) dondurur. build_health_report icin."""
    if not db_yapilandirildi():
        return "warn", "PostgreSQL yok (hafıza kapalı)"
    try:
        with _db_baglan() as conn:
            with conn.cursor() as cur:
                # Web kaynakli olan DOSYA sayilir, parca degil. /indeksle
                # raporu da dosya sayiyor; iki ekran ayni birimi kullanmali.
                # Parca sayilsaydi "4 dosya (5 web kaynakli)" gibi imkansiz
                # gorunen bir cumle cikiyordu.
                cur.execute(
                    "SELECT count(*), count(DISTINCT path), "
                    "count(DISTINCT path) FILTER (WHERE provenance = 'web_kaynakli') "
                    "FROM rag_chunks"
                )
                parca, dosya, web = cur.fetchone()
    except DbHatasi as e:
        return "error", str(e)[:80]
    except Exception as e:
        return "error", f"sorgu hatasi: {str(e)[:60]}"

    if parca == 0:
        return "warn", "indeks boş — /indeksle"
    if web:
        return "ok", f"{dosya} dosya ({web} web kaynaklı), {parca} parça"
    return "ok", f"{dosya} dosya, {parca} parça"


# ── INDEKSLEME ────────────────────────────────────────────────────────────────

def discover_files(workspace: Path | None = None) -> list[Path]:
    """Politikanin izin verdigi, indekslenebilir dosyalari bulur.

    Uc filtre, hepsi GECMELI:
      1. Access katmani izin veriyor (is_rag_allowed)
      2. Metin uzantisi ve boyut siniri
      3. Gercekten workspace icinde (sembolik bag disari tasimaz)
    """
    kok = (workspace or WORKSPACE).resolve()
    bulunan = []
    for yol in sorted(kok.rglob("*")):
        if yol.is_symlink() or not yol.is_file():
            continue
        try:
            gercek = yol.resolve()
            if not gercek.is_relative_to(kok):
                continue
            goreli = str(gercek.relative_to(kok)).replace("\\", "/")
        except (OSError, ValueError):
            continue
        if yol.suffix.lower() not in INDEKSLENEBILIR_UZANTILAR:
            continue
        if not is_rag_allowed(goreli):
            continue
        try:
            if yol.stat().st_size > RAG_MAX_FILE_BYTES:
                logger.info(f"📚 Boyut siniri asildi, atlandi: {goreli}")
                continue
        except OSError:
            continue
        bulunan.append(gercek)
    return bulunan


def indexed_hashes() -> dict[str, str]:
    """Indekslenmis dosyalarin icerik ozetleri: path -> hash."""
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT ON (path) path, content_hash FROM rag_chunks "
                "ORDER BY path, chunk_index"
            )
            return {p: h for p, h in cur.fetchall()}


def index_file(goreli: str, icerik: str) -> int:
    """Tek bir dosyayi indeksler, yazilan parca sayisini dondurur.

    Embedding ONCE yapilir, veritabanina SONRA yazilir. Embedding
    basarisiz olursa eski parcalar yerinde kalir -- yarim kalmis bir
    guncelleme indeksi bosaltmaz.
    """
    parcalar = chunk_text(icerik)
    if not parcalar:
        return 0

    vektorler = embed(parcalar)
    koken = detect_provenance(goreli)
    sinif = classify_file(goreli)
    ozet = content_hash(icerik)

    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rag_chunks WHERE path = %s", (goreli,))
            for i, (parca, vektor) in enumerate(zip(parcalar, vektorler)):
                cur.execute(
                    "INSERT INTO rag_chunks "
                    "(path, chunk_index, content, embedding, provenance, classification, content_hash) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (goreli, i, parca, vektor, koken, sinif, ozet),
                )
        conn.commit()
    return len(parcalar)


def remove_stale(gecerli: set[str]) -> int:
    """Artik indekslenmemesi gereken dosyalarin parcalarini siler.

    Iki durumu kapsar: dosya silinmis, ya da politika degismis ve dosya
    artik izinli degil. Ikincisi onemli: bir dosya SECRET'a gecerse,
    eski parcalari indekste kalmamali.
    """
    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT path FROM rag_chunks")
            mevcut = {p for (p,) in cur.fetchall()}
            eski = sorted(mevcut - gecerli)
            for yol in eski:
                cur.execute("DELETE FROM rag_chunks WHERE path = %s", (yol,))
        conn.commit()
    return len(eski)


def index_workspace() -> dict:
    """Workspace'i tarar, degisen dosyalari indeksler, eskileri temizler.

    Embedding servisi hata verirse tarama DURUR ve eski kayit temizligi
    YAPILMAZ. Yarim bir tarama sonucuna gore silme yapmak, henuz
    islenmemis dosyalarin parcalarini kaybettirebilirdi.
    """
    if not _INDEKS_KILIDI.acquire(blocking=False):
        raise RagHatasi("İndeksleme zaten çalışıyor.")
    try:
        kok = WORKSPACE.resolve()
        dosyalar = discover_files(kok)
        gecerli = {str(p.relative_to(kok)).replace("\\", "/") for p in dosyalar}
        mevcut = indexed_hashes()

        rapor = {"yeni": 0, "degismeyen": 0, "parca": 0,
                 "web": 0, "okunamayan": [], "silinen": 0}

        for yol in dosyalar:
            goreli = str(yol.relative_to(kok)).replace("\\", "/")
            try:
                icerik = yol.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                rapor["okunamayan"].append(goreli)
                continue

            if mevcut.get(goreli) == content_hash(icerik):
                rapor["degismeyen"] += 1
                continue

            # RagHatasi burada YUKARI firlar: servis ayakta degilse
            # butun dosyalar ayni hatayi verir, devam etmenin anlami yok.
            yazilan = index_file(goreli, icerik)
            rapor["yeni"] += 1
            rapor["parca"] += yazilan
            if detect_provenance(goreli) == "web_kaynakli":
                rapor["web"] += 1

        rapor["silinen"] = remove_stale(gecerli)
        return rapor
    finally:
        _INDEKS_KILIDI.release()


# ── ARAMA ─────────────────────────────────────────────────────────────────────

def search(
    sorgu: str,
    k: int | None = None,
    dosya_basina_tek: bool = False,
    min_skor: float | None = None,
) -> list[dict]:
    """Sorguya anlamca en yakin parcalari dondurur. Model KULLANMAZ.

    Sonuclar yalnizca kullaniciya gosterilir; hicbir yere gonderilmez.
    Bu yuzden /bul komutunda enjeksiyon riski yoktur: getirilen metin
    bir modelin onune degil, insanin onune gelir.

    DERINLEMESINE SAVUNMA: Indeks, indeksleme ANINDA izinli dosyalari
    icerir. Politika sonradan degisirse (bir dosya SECRET'a gecerse)
    eski parcalar bir sonraki /indeksle'ye kadar kalir. Bu yuzden
    arama sirasinda da politika tekrar kontrol edilir.

    dosya_basina_tek: Her dosyadan yalnizca en iyi parcayi tutar.
      /bul icin True -- "hangi belgelerimde geciyor" sorusuna bes FARKLI
      dosya gostermek daha kullanisli.
      /sor icin False -- ayni dosyanin birden fazla bolumu modele daha
      fazla baglam verir.

    min_skor: Bu esigin altindaki parcalar elenir. /bul icin None (hepsi
      gosterilir, skorlar gorunur); /sor icin RAG_MIN_SCORE.
    """
    sorgu = (sorgu or "").strip()
    if not sorgu:
        return []
    ust_sinir = k if k is not None else SEARCH_TOP_K

    (sorgu_vektoru,) = embed([sorgu])

    with _db_baglan() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT path, chunk_index, content, embedding, provenance FROM rag_chunks"
            )
            satirlar = cur.fetchall()

    # Politika dosyasi her cagrida diskten okunuyor; her yol icin
    # yalnizca bir kez sor.
    izin_onbellegi: dict[str, bool] = {}
    sonuclar = []
    for yol, sira, icerik, vektor, koken in satirlar:
        if yol not in izin_onbellegi:
            izin_onbellegi[yol] = is_rag_allowed(yol)
        if not izin_onbellegi[yol]:
            continue
        sonuclar.append({
            "path": yol,
            "chunk_index": sira,
            "content": icerik,
            "provenance": koken,
            "score": cosine(sorgu_vektoru, list(vektor)),
        })

    if min_skor is not None:
        sonuclar = [s for s in sonuclar if s["score"] >= min_skor]

    sonuclar.sort(key=lambda s: s["score"], reverse=True)

    # Tekillestirme KESMEDEN ONCE yapilmali. Once kesip sonra
    # tekillestirmek, k'dan az farkli dosya dondururdu.
    if dosya_basina_tek:
        gorulen: set[str] = set()
        tekil = []
        for s in sonuclar:
            if s["path"] not in gorulen:
                gorulen.add(s["path"])
                tekil.append(s)
        sonuclar = tekil

    return sonuclar[:ust_sinir]