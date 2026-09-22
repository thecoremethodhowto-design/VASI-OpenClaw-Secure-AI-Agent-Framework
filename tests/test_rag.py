"""RAG katmani: parcalama, koken etiketi, gomme ve sema.

Bu testler PostgreSQL ya da Ollama GEREKTIRMEZ. Ag cagrilari sahte
nesnelerle degistirilir.
"""
import ast
import inspect
from pathlib import Path

import pytest


# ── Parcalama ────────────────────────────────────────────────────────────────

def test_bos_metin_bos_liste(vasi_module):
    r = vasi_module.rag
    assert r.chunk_text("") == []
    assert r.chunk_text("   \n\n  ") == []
    assert r.chunk_text(None) == []


def test_kisa_metin_tek_parca(vasi_module):
    assert vasi_module.rag.chunk_text("Kisa bir paragraf.") == ["Kisa bir paragraf."]


def test_kucuk_paragraflar_birlestiriliyor(vasi_module):
    r = vasi_module.rag
    metin = "Birinci.\n\nIkinci.\n\nUcuncu."
    parcalar = r.chunk_text(metin, max_chars=100)
    assert len(parcalar) == 1
    assert "Birinci." in parcalar[0] and "Ucuncu." in parcalar[0]


def test_hicbir_parca_siniri_asmiyor(vasi_module):
    r = vasi_module.rag
    metin = "\n\n".join(["kelime " * 60] * 8) + "\n\n" + "uzun " * 500
    for parca in r.chunk_text(metin, max_chars=300):
        assert len(parca) <= 300, f"{len(parca)} karakterlik parca siniri asiyor"


def test_uzun_paragraf_kelime_sinirindan_bolunuyor(vasi_module):
    r = vasi_module.rag
    paragraf = " ".join(f"kelime{i}" for i in range(200))
    parcalar = r.chunk_text(paragraf, max_chars=150)
    assert len(parcalar) > 1
    for parca in parcalar:
        # Her parca tam kelimelerden olusmali; yarim kelime yok
        for kelime in parca.split():
            assert kelime.startswith("kelime") and kelime[6:].isdigit()


def test_parcalama_icerik_kaybetmiyor(vasi_module):
    """Bolme sirasinda hicbir kelime dusmemeli."""
    r = vasi_module.rag
    kelimeler = [f"k{i}" for i in range(400)]
    metin = "\n\n".join(" ".join(kelimeler[i:i + 40]) for i in range(0, 400, 40))
    geri = " ".join(r.chunk_text(metin, max_chars=200)).split()
    assert geri == kelimeler


# ── Koken etiketi ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("yol,beklenen", [
    ("youtube/senaryolar/ara_senaryo_20260920_1030.md", "web_kaynakli"),
    ("youtube/senaryolar/senaryo_20260920_1030.md", "yerel"),
    ("projeler/vasi/notlar.md", "yerel"),
    ("README.md", "yerel"),
    ("arastirma/ara_ozet_x.md", "web_kaynakli"),
])
def test_koken_dosya_yolundan_belirleniyor(vasi_module, yol, beklenen):
    assert vasi_module.rag.detect_provenance(yol) == beklenen


def test_koken_icerige_bakmiyor(vasi_module):
    """KRITIK: bir belge kendi etiketini degistirememeli.

    Etiket icerikten okunsaydi, belgenin icine yazilmis bir metin
    "bu yerel icerik" diyerek web kaynakli olmayi gizleyebilirdi.
    Hafiza fazindaki "kaynak etiketini kod atar" ilkesinin karsiligi.
    """
    sig = inspect.signature(vasi_module.rag.detect_provenance)
    assert list(sig.parameters) == ["yol"], (
        "detect_provenance icerik parametresi aliyor; belge kendi "
        "etiketini etkileyebilir hale gelmis"
    )


def test_koken_degerleri_semayla_uyumlu(vasi_module):
    r = vasi_module.rag
    for koken in r.GECERLI_KOKENLER:
        assert f"'{koken}'" in r.SEMA


# ── Vektor matematigi ────────────────────────────────────────────────────────

def test_normalize_birim_uzunluk(vasi_module):
    import math
    v = vasi_module.rag.normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)
    assert v == pytest.approx([0.6, 0.8])


def test_normalize_sifir_vektor(vasi_module):
    assert vasi_module.rag.normalize([0.0, 0.0]) == [0.0, 0.0]


@pytest.mark.parametrize("a,b,beklenen", [
    ([1.0, 0.0], [1.0, 0.0], 1.0),
    ([1.0, 0.0], [0.0, 1.0], 0.0),
    ([1.0, 0.0], [-1.0, 0.0], -1.0),
    ([2.0, 0.0], [5.0, 0.0], 1.0),
])
def test_cosine(vasi_module, a, b, beklenen):
    assert vasi_module.rag.cosine(a, b) == pytest.approx(beklenen)


def test_cosine_boyut_uyusmazligi(vasi_module):
    with pytest.raises(vasi_module.rag.RagHatasi):
        vasi_module.rag.cosine([1.0, 2.0], [1.0, 2.0, 3.0])


def test_content_hash(vasi_module):
    h = vasi_module.rag.content_hash
    assert h("abc") == h("abc")
    assert h("abc") != h("abd")


# ── Embedding ────────────────────────────────────────────────────────────────

class SahteYanit:
    def __init__(self, durum=200, govde=None, metin=""):
        self.status_code = durum
        self._govde = govde or {}
        self.text = metin

    def json(self):
        return self._govde


def test_embedding_uzak_hosta_gitmiyor(vasi_module, monkeypatch):
    """KRITIK: belge icerigi makineden cikmamali.

    OLLAMA_HOST uzak bir adrese ayarlanirsa embedding REDDEDILMELI --
    ve reddedilmesi yetmez, o adrese HIC istek atilmamali.
    """
    r = vasi_module.rag
    cagrilar = []
    monkeypatch.setattr(r, "OLLAMA_HOST", "https://embedding.bulut-saglayici.com")
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: cagrilar.append(a))

    with pytest.raises(r.RagHatasi) as hata:
        r.embed(["gizli belge icerigi"])

    assert "yerel" in str(hata.value).lower()
    assert cagrilar == [], "uzak hosta istek atilmis"


@pytest.mark.parametrize("host", [
    "http://localhost:11434",
    "http://127.0.0.1:11434",
    "http://host.docker.internal:11434",
    "http://ollama:11434",
])
def test_embedding_yerel_hostlara_izinli(vasi_module, monkeypatch, host):
    r = vasi_module.rag
    monkeypatch.setattr(r, "OLLAMA_HOST", host)
    monkeypatch.setattr(
        r.requests, "post",
        lambda *a, **k: SahteYanit(govde={"embeddings": [[3.0, 4.0]]}),
    )
    assert r.embed(["x"]) == [pytest.approx([0.6, 0.8])]


def test_bos_liste_istek_atmiyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    cagrilar = []
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: cagrilar.append(a))
    assert r.embed([]) == []
    assert cagrilar == []


def test_embedding_dogru_uca_gidiyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    yakalanan = {}

    def sahte_post(url, json=None, timeout=None):
        yakalanan.update(url=url, govde=json)
        return SahteYanit(govde={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})

    monkeypatch.setattr(r, "OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setattr(r.requests, "post", sahte_post)
    r.embed(["a", "b"])

    assert yakalanan["url"].endswith("/api/embed")
    assert yakalanan["govde"]["model"] == r.EMBED_MODEL
    assert yakalanan["govde"]["input"] == ["a", "b"]


def test_embedding_sonuclari_normalize_ediliyor(vasi_module, monkeypatch):
    import math
    r = vasi_module.rag
    monkeypatch.setattr(r, "OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setattr(
        r.requests, "post",
        lambda *a, **k: SahteYanit(govde={"embeddings": [[10.0, 0.0, 0.0]]}),
    )
    v = r.embed(["x"])[0]
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)


def test_embedding_sayi_uyusmazligi_yakalaniyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    monkeypatch.setattr(r, "OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setattr(
        r.requests, "post",
        lambda *a, **k: SahteYanit(govde={"embeddings": [[1.0]]}),
    )
    with pytest.raises(r.RagHatasi):
        r.embed(["a", "b"])


def test_eksik_model_yardimci_mesaj_veriyor(vasi_module, monkeypatch):
    """Model indirilmemisse kullanici ne yapacagini bilmeli."""
    r = vasi_module.rag
    monkeypatch.setattr(r, "OLLAMA_HOST", "http://localhost:11434")
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: SahteYanit(durum=404))
    with pytest.raises(r.RagHatasi) as hata:
        r.embed(["x"])
    assert "ollama pull" in str(hata.value)


def test_baglanti_hatasi_ragHatasi_oluyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    monkeypatch.setattr(r, "OLLAMA_HOST", "http://localhost:11434")

    def patlayan(*a, **k):
        raise r.requests.RequestException("baglanti yok")

    monkeypatch.setattr(r.requests, "post", patlayan)
    with pytest.raises(r.RagHatasi):
        r.embed(["x"])


# ── Sema ─────────────────────────────────────────────────────────────────────

def test_sema_pgvector_kullanmiyor(vasi_module):
    """Resmi postgres imaji pgvector icermiyor.

    Kullanmak, baska bir yayincinin imajina gecmeyi -- yeni bir tedarik
    zinciri kararini -- gerektirirdi. Bu olcekte duz REAL[] yeterli.
    """
    sema = vasi_module.rag.SEMA
    assert "REAL[]" in sema
    assert "vector(" not in sema.lower()
    assert "CREATE EXTENSION" not in sema.upper()


def test_sema_tekrar_calistirilabilir(vasi_module):
    sema = vasi_module.rag.SEMA
    assert "CREATE TABLE IF NOT EXISTS" in sema
    assert "CREATE INDEX IF NOT EXISTS" in sema


def test_sema_koken_kisiti(vasi_module):
    """Veritabani seviyesinde de gecersiz koken reddedilmeli."""
    assert "CONSTRAINT rag_koken_gecerli" in vasi_module.rag.SEMA


def test_sema_parca_benzersiz(vasi_module):
    """Ayni dosyanin ayni parcasi iki kez indekslenmemeli."""
    assert "UNIQUE (path, chunk_index)" in vasi_module.rag.SEMA


# ── Baglanti ve katmanlar ────────────────────────────────────────────────────

def test_rag_semasi_baslangicta_kuruluyor(vasi_module):
    """Hafiza fazinda init_schema() yazilmis ama cagrilmamisti."""
    kaynak = (Path(vasi_module.__file__)).read_text(encoding="utf-8")
    baslangic = kaynak[kaynak.index('if __name__ == "__main__":'):]
    assert "rag.init_schema()" in baslangic


def test_rag_saglik_raporuna_bagli(vasi_module):
    kaynak = inspect.getsource(vasi_module.build_health_report)
    assert "build_rag_health()" in kaynak
    assert 'HealthCheck("RAG", "warn", details="henüz kurulmadı")' not in kaynak


def test_rag_yalnizca_access_ve_memorye_bagimli(vasi_module):
    """RAG bir veri katmani: Access'ten politika, Memory'den baglanti."""
    kaynak = Path(vasi_module.rag.__file__).read_text(encoding="utf-8")
    agac = ast.parse(kaynak)
    importlar = set()
    for d in ast.walk(agac):
        if isinstance(d, ast.Import):
            importlar.update(a.name.split(".")[0] for a in d.names)
        elif isinstance(d, ast.ImportFrom) and d.module and d.level == 0:
            importlar.add(d.module.split(".")[0])

    yerel = {"vasi", "access", "context", "execution", "decision", "memory", "observability"}
    assert importlar & yerel <= {"access", "memory"}, (
        f"rag.py izin verilmeyen bagimliliklar: {(importlar & yerel) - {'access', 'memory'}}"
    )


def test_yerel_host_listesi_tek_yerde(vasi_module):
    """Guvenlik listesi kopyalanirsa biri guncellenir, digeri kalir."""
    for dosya in ("execution.py", "rag.py", "vasi.py"):
        kaynak = (Path(vasi_module.__file__).parent / dosya).read_text(encoding="utf-8")
        assert "LOCAL_OLLAMA_HOSTS = {" not in kaynak, f"{dosya} listeyi yeniden tanimliyor"

    kaynak = Path(vasi_module.access.__file__).read_text(encoding="utf-8")
    assert "LOCAL_OLLAMA_HOSTS = {" in kaynak


@pytest.mark.parametrize("url,beklenen", [
    ("http://localhost:11434", True),
    ("http://host.docker.internal:11434", True),
    ("https://api.bulut.com", False),
    ("http://192.168.1.50:11434", False),
])
def test_is_local_host(vasi_module, url, beklenen):
    assert vasi_module.access.is_local_host(url) is beklenen


# ── Siniflandirma onceligi ───────────────────────────────────────────────────

@pytest.mark.parametrize("yol", [
    ".env",
    "projeler/.env",
    "projeler/alt/klasor/.env.local",
    "projeler/secrets.txt",
    "youtube/api_keys.txt",
    "youtube/.env.production",
    "arastirma/secrets.md",
])
def test_gizli_dosya_her_klasorde_secret(vasi_module, yol):
    """KRITIK: en kisitlayici sinif kazanmali.

    Siniflandirma YAML'daki sirayla yapiliyordu ve SECRET en sondaydi.
    projeler/.env once "projeler/**" desenine uyup PROJECT sayiliyordu
    -- rag_allowed: true. Indeksleme calissaydi API anahtarlari
    parcalanip veritabanina yazilacakti.

    Fark edilmemisti cunku tum siniflarda gemini_allowed: false idi;
    yanlis siniflandirmanin hicbir etkisi yoktu. RAG, siniflandirmanin
    davranisi degistirdigi ilk ozellik.
    """
    a = vasi_module.access
    assert a.classify_file(yol) == "SECRET", f"{yol} -> {a.classify_file(yol)}"
    assert a.is_rag_allowed(yol) is False


@pytest.mark.parametrize("yol,sinif,rag", [
    ("projeler/vasi.py", "PROJECT", True),
    ("youtube/senaryolar/senaryo_1.md", "PUBLIC", True),
    ("youtube/senaryolar/ara_senaryo_1.md", "PUBLIC", True),
    ("notlar/NOTES.md", "PRIVATE", False),
    ("notlar/rapor_1104.md", "PRIVATE", False),
    ("siniflandirilmamis.txt", "PRIVATE", False),
])
def test_mesru_dosyalar_sinifini_koruyor(vasi_module, yol, sinif, rag):
    """Oncelik kurali gizli olmayan dosyalari etkilememeli."""
    a = vasi_module.access
    assert a.classify_file(yol) == sinif
    assert a.is_rag_allowed(yol) is rag


def test_oncelik_yaml_sirasina_bagli_degil(vasi_module):
    """Kural kodda durmali; YAML'da siniflarin sirasi degisse de gecerli."""
    kaynak = inspect.getsource(vasi_module.access.classify_file)
    assert "SINIF_ONCELIGI" in kaynak
    assert "for classification, globs in patterns.items():" not in kaynak


def test_oncelik_en_kisitlayicidan_basliyor(vasi_module):
    assert vasi_module.access.SINIF_ONCELIGI[0] == "SECRET"


def test_politika_siniflari_tanimli(vasi_module):
    """YAML'a yeni bir sinif eklenirse oncelik listesi de guncellenmeli.

    Aksi halde yeni sinif en sona duser ve gevsek siniflarin arkasinda
    kalir -- ayni hata baska bir kilikta geri gelir.
    """
    a = vasi_module.access
    politika = a._load_classification_policy()
    yaml_siniflari = set(politika.get("patterns", {}))
    eksik = yaml_siniflari - set(a.SINIF_ONCELIGI)
    assert not eksik, f"SINIF_ONCELIGI'nde tanimsiz siniflar: {eksik}"


def test_rag_izni_varsayilan_hayir(vasi_module, monkeypatch):
    """Politika okunamazsa hicbir dosya indekslenmemeli."""
    a = vasi_module.access
    monkeypatch.setattr(a, "_load_classification_policy", lambda: {})
    assert a.is_rag_allowed("youtube/senaryo.md") is False
    assert a.is_rag_allowed("projeler/x.py") is False


# ── Dosya kesfi (gercek dosyalarla) ──────────────────────────────────────────

def _yaz(kok, yol, icerik="icerik"):
    p = kok / yol
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(icerik, encoding="utf-8")
    return p


def _goreli(kok, yollar):
    return {str(p.relative_to(kok.resolve())) for p in yollar}


def test_kesif_yalnizca_izinli_siniflari_buluyor(vasi_module, tmp_path):
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/senaryolar/senaryo_1.md")
    _yaz(kok, "projeler/vasi/notlar.md")
    _yaz(kok, "notlar/NOTES.md")
    _yaz(kok, "siniflandirilmamis.md")

    bulunan = _goreli(kok, r.discover_files(kok))
    assert bulunan == {"youtube/senaryolar/senaryo_1.md", "projeler/vasi/notlar.md"}


def test_kesif_gizli_dosyalari_atliyor(vasi_module, tmp_path):
    """KRITIK: siniflandirma acigi taramada da kapali olmali.

    Proje klasorundeki bir .env dosyasi -- son derece yaygin -- eskiden
    PROJECT sayilip indekslenecekti.
    """
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "projeler/vasi/app.py", "print('merhaba')")
    _yaz(kok, "projeler/vasi/.env", "OPENAI_API_KEY=sk-gercek-anahtar")
    _yaz(kok, "projeler/vasi/secrets.txt", "parola=12345")
    _yaz(kok, "youtube/api_keys.txt", "anahtar")

    bulunan = _goreli(kok, r.discover_files(kok))
    assert bulunan == {"projeler/vasi/app.py"}, f"gizli dosya taramaya girdi: {bulunan}"


def test_kesif_ikili_uzantilari_atliyor(vasi_module, tmp_path):
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/kapak.png")
    _yaz(kok, "youtube/video.mp4")
    _yaz(kok, "youtube/senaryo.md")
    assert _goreli(kok, r.discover_files(kok)) == {"youtube/senaryo.md"}


def test_kesif_boyut_sinirini_uyguluyor(vasi_module, tmp_path, monkeypatch):
    r = vasi_module.rag
    monkeypatch.setattr(r, "RAG_MAX_FILE_BYTES", 100)
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/kucuk.md", "a" * 50)
    _yaz(kok, "youtube/buyuk.md", "a" * 500)
    assert _goreli(kok, r.discover_files(kok)) == {"youtube/kucuk.md"}


def test_kesif_sembolik_bagi_izlemiyor(vasi_module, tmp_path):
    """Workspace icindeki bir bag, disaridaki bir dosyayi indekse sokmamali."""
    r = vasi_module.rag
    kok = tmp_path / "ws"
    disarida = tmp_path / "disarida" / "gizli.md"
    disarida.parent.mkdir(parents=True)
    disarida.write_text("workspace disindaki gizli icerik")

    (kok / "youtube").mkdir(parents=True)
    (kok / "youtube" / "bag.md").symlink_to(disarida)
    _yaz(kok, "youtube/gercek.md")

    assert _goreli(kok, r.discover_files(kok)) == {"youtube/gercek.md"}


# ── Sahte veritabani ─────────────────────────────────────────────────────────

class SahteImlec:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=None):
        self.db.sorgular.append((sql, params))

    def fetchall(self):
        return self.db.sonraki_sonuc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class SahteDb:
    def __init__(self, sonuc=None):
        self.sorgular = []
        self.sonraki_sonuc = sonuc or []
        self.commit_sayisi = 0

    def cursor(self):
        return SahteImlec(self)

    def commit(self):
        self.commit_sayisi += 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_embedding_hatasinda_veritabanina_yazilmiyor(vasi_module, monkeypatch):
    """Once embedding, sonra yazma. Yarim guncelleme indeksi bosaltmamali."""
    r = vasi_module.rag
    db = SahteDb()
    monkeypatch.setattr(r, "_db_baglan", lambda: db)

    def patlayan(metinler):
        raise r.RagHatasi("Ollama kapali")

    monkeypatch.setattr(r, "embed", patlayan)

    with pytest.raises(r.RagHatasi):
        r.index_file("youtube/senaryo.md", "bir paragraf")

    assert db.sorgular == [], "embedding basarisizken veritabanina dokunulmus"


def test_index_file_eski_parcalari_degistiriyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    db = SahteDb()
    monkeypatch.setattr(r, "_db_baglan", lambda: db)
    monkeypatch.setattr(r, "embed", lambda m: [[1.0, 0.0]] * len(m))

    n = r.index_file("youtube/senaryolar/ara_senaryo_1.md", "birinci\n\nikinci")

    assert n == 1
    assert db.sorgular[0][0].startswith("DELETE FROM rag_chunks")
    ekleme = db.sorgular[1][1]
    assert ekleme[0] == "youtube/senaryolar/ara_senaryo_1.md"
    assert ekleme[4] == "web_kaynakli", "koken etiketi yazilmamis"
    assert db.commit_sayisi == 1


def test_eski_kayit_temizligi(vasi_module, monkeypatch):
    """Silinen ya da artik izinli olmayan dosyalar indeksten cikmali."""
    r = vasi_module.rag
    db = SahteDb(sonuc=[("a.md",), ("b.md",), ("projeler/.env",)])
    monkeypatch.setattr(r, "_db_baglan", lambda: db)

    silinen = r.remove_stale({"a.md"})

    assert silinen == 2
    silinen_yollar = {p[0] for s, p in db.sorgular if s.startswith("DELETE")}
    assert silinen_yollar == {"b.md", "projeler/.env"}


# ── Orkestrasyon ─────────────────────────────────────────────────────────────

def _orkestrasyon_kur(r, monkeypatch, kok, mevcut_ozetler=None, patlayan=None):
    olaylar = {"indekslenen": [], "temizlik": None}
    monkeypatch.setattr(r, "WORKSPACE", kok)
    monkeypatch.setattr(r, "indexed_hashes", lambda: mevcut_ozetler or {})

    def sahte_index(goreli, icerik):
        if patlayan and goreli == patlayan:
            raise r.RagHatasi("servis kapali")
        olaylar["indekslenen"].append(goreli)
        return 2

    def sahte_temizlik(gecerli):
        olaylar["temizlik"] = gecerli
        return 0

    monkeypatch.setattr(r, "index_file", sahte_index)
    monkeypatch.setattr(r, "remove_stale", sahte_temizlik)
    return olaylar


def test_degismeyen_dosya_atlaniyor(vasi_module, monkeypatch, tmp_path):
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/a.md", "ayni icerik")
    _yaz(kok, "youtube/b.md", "yeni icerik")

    olaylar = _orkestrasyon_kur(
        r, monkeypatch, kok, {"youtube/a.md": r.content_hash("ayni icerik")}
    )
    rapor = r.index_workspace()

    assert olaylar["indekslenen"] == ["youtube/b.md"]
    assert rapor["degismeyen"] == 1 and rapor["yeni"] == 1


def test_servis_hatasinda_temizlik_yapilmiyor(vasi_module, monkeypatch, tmp_path):
    """Yarim bir taramaya gore silme yapilirsa islenmemis dosyalar kaybolur."""
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/a.md", "a")
    _yaz(kok, "youtube/b.md", "b")

    olaylar = _orkestrasyon_kur(r, monkeypatch, kok, patlayan="youtube/a.md")
    with pytest.raises(r.RagHatasi):
        r.index_workspace()

    assert olaylar["temizlik"] is None, "hatadan sonra eski kayit temizligi calismis"


def test_web_kaynakli_dosyalar_raporda_sayiliyor(vasi_module, monkeypatch, tmp_path):
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/senaryolar/ara_senaryo_1.md", "web")
    _yaz(kok, "youtube/senaryolar/senaryo_1.md", "yerel")

    _orkestrasyon_kur(r, monkeypatch, kok)
    assert r.index_workspace()["web"] == 1


def test_ayni_anda_iki_indeksleme_calismiyor(vasi_module):
    r = vasi_module.rag
    assert r._INDEKS_KILIDI.acquire(blocking=False)
    try:
        with pytest.raises(r.RagHatasi) as hata:
            r.index_workspace()
        assert "zaten" in str(hata.value)
    finally:
        r._INDEKS_KILIDI.release()


def test_kilit_hatadan_sonra_serbest_kaliyor(vasi_module, monkeypatch, tmp_path):
    """Bir hata kilidi kilitli birakirsa bir daha indeksleme yapilamaz."""
    r = vasi_module.rag
    kok = tmp_path / "ws"
    _yaz(kok, "youtube/a.md", "a")
    _orkestrasyon_kur(r, monkeypatch, kok, patlayan="youtube/a.md")

    with pytest.raises(r.RagHatasi):
        r.index_workspace()
    assert r._INDEKS_KILIDI.acquire(blocking=False), "kilit serbest birakilmamis"
    r._INDEKS_KILIDI.release()


# ── Telegram komutu ──────────────────────────────────────────────────────────

def test_indeksle_komutu_kayitli(vasi_module):
    assert inspect.iscoroutinefunction(vasi_module.cmd_indeksle)
    assert "/indeksle" in vasi_module.HELP_TEXT


def test_indeksle_botu_dondurmuyor(vasi_module):
    """Embedding dakikalar surebilir; ana dongude calismamali."""
    kaynak = inspect.getsource(vasi_module.cmd_indeksle)
    assert "asyncio.to_thread(rag.index_workspace)" in kaynak


def test_indeksle_denetim_izi_birakiyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_indeksle)
    for olay in ("rag_index_start", "rag_index_done", "rag_index_failed"):
        assert olay in kaynak, f"{olay} audit olayi eksik"


# ── Saglik raporu birimi ─────────────────────────────────────────────────────

class _TekSatirDb:
    """health() icin: tek fetchone sonucu donen sahte baglanti."""

    def __init__(self, satir):
        self.satir = satir
        self.sql = None

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchone(self):
        return self.satir

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_saglik_web_kaynakli_dosya_sayiyor(vasi_module, monkeypatch):
    """/indeksle dosya sayiyor; /saglik da dosya saymali.

    Eskiden parca sayiyordu ve "4 dosya, 19 parca (5 web kaynakli)"
    yaziyordu -- dort dosyanin besinin web kaynakli oldugu gibi
    okunan, imkansiz gorunen bir cumle.
    """
    r = vasi_module.rag
    db = _TekSatirDb((19, 4, 1))
    monkeypatch.setattr(r, "db_yapilandirildi", lambda: True)
    monkeypatch.setattr(r, "_db_baglan", lambda: db)

    durum, detay = r.health()

    assert "count(DISTINCT path) FILTER" in db.sql
    assert durum == "ok"
    assert detay == "4 dosya (1 web kaynaklı), 19 parça"


def test_saglik_web_yoksa_etiket_yok(vasi_module, monkeypatch):
    r = vasi_module.rag
    monkeypatch.setattr(r, "db_yapilandirildi", lambda: True)
    monkeypatch.setattr(r, "_db_baglan", lambda: _TekSatirDb((10, 3, 0)))
    assert r.health() == ("ok", "3 dosya, 10 parça")


def test_saglik_web_sayisi_dosya_sayisini_asamaz(vasi_module, monkeypatch):
    """Web kaynakli dosya sayisi toplam dosyadan buyuk gorunmemeli."""
    import re
    r = vasi_module.rag
    monkeypatch.setattr(r, "db_yapilandirildi", lambda: True)
    monkeypatch.setattr(r, "_db_baglan", lambda: _TekSatirDb((19, 4, 1)))

    _, detay = r.health()
    toplam = int(re.search(r"(\d+) dosya", detay).group(1))
    web = int(re.search(r"\((\d+) web", detay).group(1))
    assert web <= toplam


# ── Arama ────────────────────────────────────────────────────────────────────

class _AramaDb:
    """search() icin: fetchall ile sabit satirlar donen sahte baglanti."""

    def __init__(self, satirlar):
        self.satirlar = satirlar

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.satirlar

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _arama_kur(r, monkeypatch, satirlar, sorgu_vektoru=(1.0, 0.0)):
    monkeypatch.setattr(r, "_db_baglan", lambda: _AramaDb(satirlar))
    monkeypatch.setattr(r, "embed", lambda m: [list(sorgu_vektoru)])


def test_bos_sorgu_bos_sonuc(vasi_module, monkeypatch):
    r = vasi_module.rag
    cagrildi = []
    monkeypatch.setattr(r, "embed", lambda m: cagrildi.append(m) or [[1.0]])
    assert r.search("") == []
    assert r.search("   ") == []
    assert cagrildi == [], "bos sorgu icin embedding cagrilmis"


def test_sonuclar_benzerlige_gore_siralaniyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, [
        ("youtube/uzak.md",  0, "uzak",  [0.0, 1.0], "yerel"),
        ("youtube/yakin.md", 0, "yakin", [1.0, 0.0], "yerel"),
        ("youtube/orta.md",  0, "orta",  [0.7, 0.7], "yerel"),
    ])
    yollar = [s["path"] for s in r.search("sorgu")]
    assert yollar == ["youtube/yakin.md", "youtube/orta.md", "youtube/uzak.md"]


def test_sonuc_sayisi_sinirlaniyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, [
        (f"youtube/d{i}.md", 0, "x", [1.0, 0.0], "yerel") for i in range(10)
    ])
    assert len(r.search("sorgu", k=3)) == 3


def test_koken_sonuca_tasiniyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, [
        ("youtube/senaryolar/ara_senaryo_1.md", 0, "x", [1.0, 0.0], "web_kaynakli"),
    ])
    assert r.search("sorgu")[0]["provenance"] == "web_kaynakli"


def test_arama_politikayi_tekrar_kontrol_ediyor(vasi_module, monkeypatch):
    """KRITIK: indekslemeden sonra SECRET'a gecen dosya aramada cikmamali.

    Indeks, indeksleme ANINDAKI politikayi yansitir. Politika degisip
    /indeksle tekrar calismazsa eski parcalar indekste kalir. Arama
    anindaki kontrol bu boslugu kapatir.
    """
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, [
        ("youtube/senaryo.md", 0, "normal icerik", [1.0, 0.0], "yerel"),
        ("projeler/.env", 0, "OPENAI_API_KEY=sk-...", [1.0, 0.0], "yerel"),
    ])
    yollar = {s["path"] for s in r.search("anahtar")}
    assert "projeler/.env" not in yollar, "politikanin reddettigi dosya aramada cikti"
    assert "youtube/senaryo.md" in yollar


def test_politika_her_yol_icin_bir_kez_soruluyor(vasi_module, monkeypatch):
    """Politika dosyasi diskten okunuyor; parca basina degil yol basina sor."""
    r = vasi_module.rag
    sorulan = []
    monkeypatch.setattr(r, "is_rag_allowed", lambda y: sorulan.append(y) or True)
    _arama_kur(r, monkeypatch, [
        ("youtube/a.md", i, "x", [1.0, 0.0], "yerel") for i in range(20)
    ])
    r.search("sorgu")
    assert sorulan == ["youtube/a.md"], f"{len(sorulan)} kez soruldu"


# ── /bul komutu ──────────────────────────────────────────────────────────────

def test_bul_modeli_cagirmiyor(vasi_module):
    """KRITIK: /bul yalnizca arar. Getirilen metin modele gitmez.

    Bu yuzden bu komutta enjeksiyon riski yoktur -- metin bir modelin
    degil, insanin onune gelir.
    """
    kaynak = inspect.getsource(vasi_module.cmd_bul)
    for yasak in ("run_model_with_tools", "pick_model", "model_for_role", "_chat("):
        assert yasak not in kaynak, f"/bul model cagiriyor: {yasak}"


def test_bul_botu_dondurmuyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_bul)
    assert "asyncio.to_thread(rag.search" in kaynak


def test_bul_denetim_izi_birakiyor(vasi_module):
    assert "rag_search" in inspect.getsource(vasi_module.cmd_bul)


def test_bul_komutu_kayitli(vasi_module):
    assert inspect.iscoroutinefunction(vasi_module.cmd_bul)
    assert "/bul" in vasi_module.HELP_TEXT


def test_sonuc_metni_web_etiketini_gosteriyor(vasi_module):
    """Karar 4'un kullanici tarafi: web kaynakli icerik gorunur olmali."""
    metin = vasi_module._bul_sonucu("sorgu", [
        {"path": "youtube/senaryolar/ara_senaryo_1.md", "chunk_index": 0,
         "content": "web icerigi", "provenance": "web_kaynakli", "score": 0.81},
        {"path": "youtube/senaryolar/senaryo_1.md", "chunk_index": 0,
         "content": "yerel icerik", "provenance": "yerel", "score": 0.74},
    ])
    satirlar = metin.split("\n")
    web_satiri = next(s for s in satirlar if "ara_senaryo_1" in s)
    yerel_satiri = next(s for s in satirlar if "senaryo_1.md" in s and "ara_" not in s)
    assert "web kaynaklı" in web_satiri
    assert "web kaynaklı" not in yerel_satiri


def test_sonuc_metni_modelin_kullanilmadigini_soyluyor(vasi_module):
    metin = vasi_module._bul_sonucu("q", [
        {"path": "a.md", "chunk_index": 0, "content": "x",
         "provenance": "yerel", "score": 0.5},
    ])
    assert "Model kullanılmadı" in metin


def test_sonuc_yoksa_indeksleme_oneriliyor(vasi_module):
    assert "/indeksle" in vasi_module._bul_sonucu("q", [])


# ── Dosya basina tek sonuc ───────────────────────────────────────────────────

_TEKRARLI = [
    ("youtube/a.md", 0, "a0", [1.0, 0.0], "yerel"),
    ("youtube/a.md", 1, "a1", [0.95, 0.31], "yerel"),
    ("youtube/b.md", 0, "b0", [0.9, 0.44], "yerel"),
    ("youtube/b.md", 1, "b1", [0.85, 0.53], "yerel"),
    ("youtube/c.md", 0, "c0", [0.8, 0.6], "yerel"),
]


def test_varsayilan_ayni_dosyadan_birden_fazla_parca(vasi_module, monkeypatch):
    """/sor icin: ayni dosyanin farkli bolumleri daha fazla baglam demek."""
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, _TEKRARLI)
    yollar = [s["path"] for s in r.search("q", k=4)]
    assert yollar == ["youtube/a.md", "youtube/a.md", "youtube/b.md", "youtube/b.md"]


def test_tekillestirme_her_dosyadan_en_iyisini_tutuyor(vasi_module, monkeypatch):
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, _TEKRARLI)
    sonuclar = r.search("q", k=5, dosya_basina_tek=True)
    assert [s["path"] for s in sonuclar] == ["youtube/a.md", "youtube/b.md", "youtube/c.md"]
    assert [s["content"] for s in sonuclar] == ["a0", "b0", "c0"], "en iyi parca secilmemis"


def test_tekillestirme_kesmeden_once_yapiliyor(vasi_module, monkeypatch):
    """Once kesip sonra tekillestirmek k'dan az dosya dondururdu.

    k=3 ile once kesilseydi [a0, a1, b0] kalir, tekillestirince
    yalnizca 2 dosya donerdi -- c.md hic gorunmezdi.
    """
    r = vasi_module.rag
    _arama_kur(r, monkeypatch, _TEKRARLI)
    sonuclar = r.search("q", k=3, dosya_basina_tek=True)
    assert len(sonuclar) == 3
    assert "youtube/c.md" in {s["path"] for s in sonuclar}


def test_bul_dosya_basina_tek_kullaniyor(vasi_module):
    kaynak = inspect.getsource(vasi_module.cmd_bul)
    assert "dosya_basina_tek=True" in kaynak