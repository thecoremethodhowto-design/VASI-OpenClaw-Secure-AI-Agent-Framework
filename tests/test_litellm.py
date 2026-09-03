"""LiteLLM backend'i ve iki API'nin normallestirilmesi.

Bu testler gercek HTTP cagrisi yapmaz; requests.post sahte bir
nesneyle degistirilir. Amac, OpenAI uyumlu yanit yapisinin dogru
ayristirildigini dogrulamak.
"""
import asyncio
import json

import pytest


# ── Arac cagri normallestirmesi ──────────────────────────────────────────────

def test_ollama_formati_normalize_ediliyor(vasi_module):
    """Ollama: arguments bir sozluk, id yok."""
    ex = vasi_module.execution
    mesaj = {
        "tool_calls": [
            {"function": {"name": "skill_get_time", "arguments": {"tz": "TR"}}}
        ]
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert sonuc == [{"id": None, "name": "skill_get_time", "arguments": {"tz": "TR"}}]


def test_openai_formati_normalize_ediliyor(vasi_module):
    """OpenAI: arguments JSON metni, id var."""
    ex = vasi_module.execution
    mesaj = {
        "tool_calls": [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "skill_web_radar",
                    "arguments": json.dumps({"url": "https://example.com"}),
                },
            }
        ]
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert sonuc == [
        {
            "id": "call_abc123",
            "name": "skill_web_radar",
            "arguments": {"url": "https://example.com"},
        }
    ]


def test_bozuk_json_argumani_bos_sozluge_duser(vasi_module):
    """Ayristirilamayan arguman, cagriyi patlatmamali."""
    ex = vasi_module.execution
    mesaj = {"tool_calls": [{"function": {"name": "x", "arguments": "{bozuk"}}]}
    assert ex._normalize_tool_calls(mesaj)[0]["arguments"] == {}


def test_arac_cagrisi_yoksa_bos_liste(vasi_module):
    ex = vasi_module.execution
    assert ex._normalize_tool_calls({"content": "sadece metin"}) == []
    assert ex._normalize_tool_calls({"tool_calls": None}) == []


# ── Arac sonucu paketleme ────────────────────────────────────────────────────

def test_tool_call_id_varsa_ekleniyor(vasi_module):
    """OpenAI uyumlu API tool_call_id bekler."""
    ex = vasi_module.execution
    cagri = {"id": "call_1", "name": "skill_get_time", "arguments": {}}
    mesaj = ex._tool_result_message(cagri, "12:00")
    assert mesaj["tool_call_id"] == "call_1"
    assert mesaj["name"] == "skill_get_time"
    assert mesaj["role"] == "tool"


def test_tool_call_id_yoksa_eklenmiyor(vasi_module):
    """Ollama id gondermez; alan hic olmamali."""
    ex = vasi_module.execution
    cagri = {"id": None, "name": "skill_get_time", "arguments": {}}
    mesaj = ex._tool_result_message(cagri, "12:00")
    assert "tool_call_id" not in mesaj
    assert mesaj["name"] == "skill_get_time"


# ── LiteLLM backend'i ────────────────────────────────────────────────────────

class SahteYanit:
    def __init__(self, durum=200, govde=None, metin=""):
        self.status_code = durum
        self._govde = govde or {}
        self.text = metin

    def json(self):
        return self._govde


def test_litellm_yanitindan_mesaj_cikariliyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    yakalanan = {}

    def sahte_post(url, **kw):
        yakalanan["url"] = url
        yakalanan["payload"] = kw.get("json")
        yakalanan["headers"] = kw.get("headers")
        return SahteYanit(
            govde={"choices": [{"message": {"content": "litellm cevabi"}}]}
        )

    monkeypatch.setattr(ex.requests, "post", sahte_post)
    mesaj = ex._chat_litellm("yerel-genel", [{"role": "user", "content": "selam"}])

    assert mesaj["content"] == "litellm cevabi"
    assert yakalanan["url"].endswith("/v1/chat/completions")
    assert yakalanan["payload"]["model"] == "yerel-genel"
    assert yakalanan["headers"]["Authorization"].startswith("Bearer ")


def test_litellm_hata_kodu_chatbackenderror_a_donusuyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(
        ex.requests, "post",
        lambda url, **kw: SahteYanit(durum=404, metin="model yok")
    )
    with pytest.raises(ex.ChatBackendError) as hata:
        ex._chat_litellm("olmayan", [{"role": "user", "content": "x"}])
    assert hata.value.status_code == 404


def test_litellm_baglanti_hatasi_yakalaniyor(vasi_module, monkeypatch):
    ex = vasi_module.execution

    def patlayan_post(url, **kw):
        raise ex.requests.RequestException("baglanti yok")

    monkeypatch.setattr(ex.requests, "post", patlayan_post)
    with pytest.raises(ex.ChatBackendError):
        ex._chat_litellm("yerel-genel", [{"role": "user", "content": "x"}])


# ── Bayrak davranisi ─────────────────────────────────────────────────────────

def test_varsayilan_backend_ollama(vasi_module):
    """USE_LITELLM ayarlanmadiysa davranis degismemeli."""
    assert vasi_module.execution.USE_LITELLM is False


def test_bayrak_acikken_litellm_secilir(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(ex, "USE_LITELLM", True)
    monkeypatch.setattr(
        ex.requests, "post",
        lambda url, **kw: SahteYanit(
            govde={"choices": [{"message": {"content": "proxy uzerinden"}}]}
        ),
    )
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "selam"))
    assert sonuc == "proxy uzerinden"


def test_bayrak_kapaliyken_ollama_secilir(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(
        ex.ollama_client, "chat",
        lambda **kw: {"message": {"content": "ollama uzerinden"}},
    )
    sonuc = asyncio.run(ex.run_model_with_tools("qwen3:30b", "selam"))
    assert sonuc == "ollama uzerinden"


# ── Rol → model eslesmesi ────────────────────────────────────────────────────

def test_bayrak_kapaliyken_ollama_adi_dondurulur(vasi_module):
    d = vasi_module.decision
    assert d.model_for_role("kod") == d.MODELS["kod"]
    assert not d.model_for_role("kod").startswith("yerel-")


def test_bayrak_acikken_takma_ad_dondurulur(vasi_module, monkeypatch):
    d = vasi_module.decision
    monkeypatch.setattr(d, "_USE_LITELLM", True)
    assert d.model_for_role("kod") == "yerel-kod"
    assert d.model_for_role("gatekeeper") == "yerel-genel"


def test_takma_adlar_gizlilik_kuralina_uyuyor(vasi_module):
    """LITELLM_ALIASES icindeki her ad onek kuralina uymali."""
    d = vasi_module.decision
    for rol, ad in d.LITELLM_ALIASES.items():
        assert d.privacy_profile(ad) != "bilinmiyor", (
            f"'{rol}' rolu icin '{ad}' onek kuralina uymuyor"
        )


def test_bilinmeyen_rol_yerel_genele_duser(vasi_module, monkeypatch):
    """Guvenli varsayilan: tanimsiz rol dis modele gitmemeli."""
    d = vasi_module.decision
    monkeypatch.setattr(d, "_USE_LITELLM", True)
    assert d.model_for_role("tanimsiz_rol") == "yerel-genel"
    assert d.is_local(d.model_for_role("tanimsiz_rol"))


def test_testler_env_dosyasindan_bagimsiz(vasi_module):
    """conftest USE_LITELLM'i acikca kapatmali.

    Aksi halde .env'de bayrak acikken calistirilan testler gercek
    proxy'ye istek atar ve sonuc ortama gore degisir. Bir test
    paketi, calistirildigi makineye gore farkli sonuc vermemeli.
    """
    import os
    assert os.environ.get("USE_LITELLM") == "false", (
        "conftest USE_LITELLM'i ayarlamiyor; testler .env'e bagimli hale gelir"
    )


# ── Takma ad esleme butunlugu ────────────────────────────────────────────────

def test_hicbir_komut_MODELS_i_dogrudan_kullanmiyor():
    """Model secimi her zaman model_for_role() uzerinden yapilmali.

    MODELS'i dogrudan kullanan bir komut, LiteLLM acikken takma ad
    eslemesini atlar ve proxy'ye ham Ollama model adi gonderir.
    Sonuc: "gecersiz model adi" hatasi. Bu tam olarak bir kez
    yasandi -- dokuz komut sessizce bozuldu, hicbir test yakalamadi.
    """
    from pathlib import Path
    import re

    kaynak = (Path(__file__).resolve().parents[1] / "vasi.py").read_text(encoding="utf-8")
    ihlaller = re.findall(r'MODELS\[["\'](\w+)["\']\]', kaynak)
    assert not ihlaller, (
        f"vasi.py MODELS'i dogrudan kullaniyor: {set(ihlaller)}. "
        f"model_for_role() kullanin."
    )


# ── Politika kapisi ──────────────────────────────────────────────────────────

def test_yerel_model_her_dosyaya_izinli(vasi_module):
    """Yerel modelde veri makineden cikmaz; kontrol gereksiz."""
    a = vasi_module.access
    assert a.assert_model_allowed("yerel-genel", ["notlar/NOTES.md"]) is None
    assert a.assert_model_allowed("yerel-kod", [".env"]) is None


def test_dis_model_private_dosyayi_reddediyor(vasi_module):
    a = vasi_module.access
    hata = a.assert_model_allowed("dis-analiz", ["notlar/NOTES.md"])
    assert hata is not None
    assert "PRIVATE" in hata


def test_dis_model_secret_dosyayi_reddediyor(vasi_module):
    a = vasi_module.access
    hata = a.assert_model_allowed("dis-arastirma", [".env"])
    assert hata is not None
    assert "SECRET" in hata


def test_dis_model_dosyasiz_istege_izinli(vasi_module):
    """Sadece konu metni gonderiliyorsa dosya kontrolu devreye girmez."""
    a = vasi_module.access
    assert a.assert_model_allowed("dis-arastirma", []) is None
    assert a.assert_model_allowed("dis-arastirma", None) is None


def test_tanimsiz_takma_ad_reddediliyor(vasi_module):
    """Onek kuralina uymayan ad, dosya olmasa bile engellenmeli."""
    a = vasi_module.access
    hata = a.assert_model_allowed("claude-analiz", [])
    assert hata is not None
    assert "tanımlı bir model değil" in hata


# ── Arac dongusu ─────────────────────────────────────────────────────────────

def test_tools_her_turda_gonderiliyor(vasi_module, monkeypatch):
    """Arac sonucu geri gonderilirken de tools gitmeli.

    Gonderilmezse model gecmiste arac cagrisi sozdizimi gorur ama
    elinde arac tanimi olmaz; deseni metin olarak taklit eder ve
    <tool_call>...</tool_call> seklinde ham cikti uretir.
    Bu tam olarak bir kez yasandi.
    """
    ex = vasi_module.execution
    cagrilar = []

    yanitlar = [
        {"tool_calls": [{"id": "c1", "function": {"name": "skill_get_time", "arguments": "{}"}}]},
        {"content": "saat soylendi"},
    ]

    def sahte_chat(model, messages, tools=None, options=None):
        cagrilar.append({"tur": len(cagrilar), "tools_var": tools is not None})
        return yanitlar.pop(0)

    monkeypatch.setattr(ex, "_chat", sahte_chat)
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "saat kac"))

    assert sonuc == "saat soylendi"
    assert len(cagrilar) == 2
    assert all(c["tools_var"] for c in cagrilar), (
        f"tools bazi turlarda gonderilmemis: {cagrilar}"
    )


def test_cok_turlu_arac_kullanimi(vasi_module, monkeypatch):
    """Model art arda birden fazla arac cagirabilmeli."""
    ex = vasi_module.execution
    yanitlar = [
        {"tool_calls": [{"id": "c1", "function": {"name": "skill_get_time", "arguments": "{}"}}]},
        {"tool_calls": [{"id": "c2", "function": {"name": "skill_get_time", "arguments": "{}"}}]},
        {"content": "iki kez baktim"},
    ]
    monkeypatch.setattr(ex, "_chat", lambda *a, **k: yanitlar.pop(0))
    assert asyncio.run(ex.run_model_with_tools("yerel-genel", "x")) == "iki kez baktim"


def test_tur_siniri_sonsuz_donguyu_engelliyor(vasi_module, monkeypatch):
    """Model surekli arac cagirirsa sistem takilmamali."""
    ex = vasi_module.execution
    sayac = {"n": 0}

    def hep_arac_cagir(model, messages, tools=None, options=None):
        sayac["n"] += 1
        if tools is None:
            return {"content": "son cevap"}
        return {"tool_calls": [{"id": f"c{sayac['n']}",
                                "function": {"name": "skill_get_time", "arguments": "{}"}}]}

    monkeypatch.setattr(ex, "_chat", hep_arac_cagir)
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "x"))

    assert sonuc == "son cevap"
    assert sayac["n"] == ex.MAX_TOOL_ROUNDS + 1, "tur siniri uygulanmadi"


def test_bildirim_sadece_bir_kez(vasi_module, monkeypatch):
    """Cok turlu kullanimda bildirim tekrarlanmamali."""
    ex = vasi_module.execution
    sayac = {"n": 0}

    async def bildir():
        sayac["n"] += 1

    yanitlar = [
        {"tool_calls": [{"id": "c1", "function": {"name": "skill_get_time", "arguments": "{}"}}]},
        {"tool_calls": [{"id": "c2", "function": {"name": "skill_get_time", "arguments": "{}"}}]},
        {"content": "bitti"},
    ]
    monkeypatch.setattr(ex, "_chat", lambda *a, **k: yanitlar.pop(0))
    asyncio.run(ex.run_model_with_tools("yerel-genel", "x", on_tool_use=bildir))
    assert sayac["n"] == 1


# ── Metin icindeki arac cagrilari ────────────────────────────────────────────

def test_metindeki_tool_call_ayristiriliyor(vasi_module):
    """Model arac cagrisini metin olarak uretirse de yakalanmali.

    Qwen ailesi bunu <tool_call>{...}</tool_call> seklinde uretebilir;
    proxy uzerinden gecerken mesaj gecmisi tam korunamadiginda olusur.
    """
    ex = vasi_module.execution
    mesaj = {
        "content": '<tool_call>\n{"name": "skill_web_radar", '
                   '"arguments": {"url":"https://example.com"}}\n</tool_call>'
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert len(sonuc) == 1
    assert sonuc[0]["name"] == "skill_web_radar"
    assert sonuc[0]["arguments"] == {"url": "https://example.com"}


def test_yapisal_alan_varsa_metne_bakilmiyor(vasi_module):
    """Yapisal tool_calls oncelikli olmali."""
    ex = vasi_module.execution
    mesaj = {
        "content": '<tool_call>{"name": "yanlis", "arguments": {}}</tool_call>',
        "tool_calls": [{"id": "c1", "function": {"name": "dogru", "arguments": "{}"}}],
    }
    sonuc = ex._normalize_tool_calls(mesaj)
    assert len(sonuc) == 1
    assert sonuc[0]["name"] == "dogru"


def test_bozuk_tool_call_etiketi_yok_sayiliyor(vasi_module):
    ex = vasi_module.execution
    assert ex._normalize_tool_calls({"content": "<tool_call>{bozuk}</tool_call>"}) == []
    assert ex._normalize_tool_calls({"content": "sadece duz metin"}) == []


def test_etiketler_kullaniciya_gosterilmiyor(vasi_module, monkeypatch):
    """Nihai cevapta <tool_call> etiketi kalmamali."""
    ex = vasi_module.execution
    monkeypatch.setattr(
        ex, "_chat",
        lambda *a, **k: {"content": 'Sonuc: 42\n<tool_call>{"name":"x","arguments":{}}</tool_call>'}
    )
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "x"))
    assert "<tool_call>" not in sonuc


def test_metin_tabanli_cagri_araci_calistiriyor(vasi_module, monkeypatch):
    """Uctan uca: metin cagrisi tespit edilip arac gercekten kosmali."""
    ex = vasi_module.execution
    yanitlar = [
        {"content": '<tool_call>{"name": "skill_get_time", "arguments": {}}</tool_call>'},
        {"content": "saat soylendi"},
    ]
    yakalanan = {}

    def sahte_chat(model, messages, tools=None, options=None):
        if len(yanitlar) == 1:
            yakalanan["messages"] = messages
        return yanitlar.pop(0)

    monkeypatch.setattr(ex, "_chat", sahte_chat)
    sonuc = asyncio.run(ex.run_model_with_tools("yerel-genel", "saat kac"))

    assert sonuc == "saat soylendi"
    arac_mesajlari = [m for m in yakalanan["messages"] if m.get("role") == "tool"]
    assert len(arac_mesajlari) == 1, "arac calistirilmadi"


# ── skill_web_radar uctan uca ────────────────────────────────────────────────

class SahteWebYanit:
    def __init__(self, govde: bytes, tur="text/html; charset=utf-8", durum=200):
        self.status_code = durum
        self.headers = {"Content-Type": tur}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self._govde = govde

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        yield self._govde


def test_web_radar_sayfayi_isliyor(vasi_module, monkeypatch):
    """Fonksiyonun TAMAMI kosulmali.

    Bu test olmadan bir NameError fark edilmeden kalabilir: fonksiyon
    ic hata yakalayicisina duser ve "Radar Hatasi" doner. Model de
    bunu gorup egitim verisine dayanan cevap uretir. Tam olarak bu
    yasandi -- eksik bir 'import html' Faz 3'ten beri sessizce
    duruyordu ve 111 test yakalamadi.
    """
    ex = vasi_module.execution
    monkeypatch.setattr(ex, "is_safe_url", lambda u: True)
    monkeypatch.setattr(
        ex.requests, "get",
        lambda *a, **k: SahteWebYanit(
            b"<html><body><h1>Baslik</h1><p>Icerik metni</p>"
            b"<script>kotu()</script></body></html>"
        ),
    )
    sonuc = ex.skill_web_radar("https://example.com/")

    assert "Radar Hatasi" not in sonuc, f"fonksiyon ic hataya dustu: {sonuc}"
    assert "Icerik metni" in sonuc
    assert "kotu()" not in sonuc, "script icerigi temizlenmemis"


def test_web_radar_html_kacisi_yapiyor(vasi_module, monkeypatch):
    """XSS korumasi: sayfadaki HTML karakterleri kacirilmali."""
    ex = vasi_module.execution
    monkeypatch.setattr(ex, "is_safe_url", lambda u: True)
    monkeypatch.setattr(
        ex.requests, "get",
        lambda *a, **k: SahteWebYanit(b"<html><body><p>a &lt;b&gt; c</p></body></html>"),
    )
    sonuc = ex.skill_web_radar("https://example.com/")
    assert "Radar Hatasi" not in sonuc
    assert "&lt;" in sonuc or "&amp;" in sonuc, "html.escape uygulanmamis"


def test_web_radar_guvensiz_url_reddediyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    monkeypatch.setattr(ex, "is_safe_url", lambda u: False)
    assert "Güvensiz" in ex.skill_web_radar("http://192.168.1.1/")


# ── Dogrulanmis yonlendirme takibi ───────────────────────────────────────────

class SahteYonlendirme:
    def __init__(self, hedef, durum=301):
        self.status_code = durum
        self.headers = {"Location": hedef}

    def raise_for_status(self):
        pass


def _radar_kur(monkeypatch, ex, yanitlar, guvenli=lambda u: True):
    """requests.get'i sirali yanitlarla degistirir, cagrilan URL'leri kaydeder."""
    cagrilan = []

    def sahte_get(u, **kw):
        cagrilan.append(u)
        return yanitlar.pop(0)

    monkeypatch.setattr(ex, "is_safe_url", guvenli)
    monkeypatch.setattr(ex.requests, "get", sahte_get)
    return cagrilan


def test_yonlendirme_takip_ediliyor(vasi_module, monkeypatch):
    """www. dusuren bir yonlendirme artik engellenmemeli."""
    ex = vasi_module.execution
    cagrilan = _radar_kur(monkeypatch, ex, [
        SahteYonlendirme("https://cybersecurityventures.com/yazi/"),
        SahteWebYanit(b"<html><body><p>Gercek icerik</p></body></html>"),
    ])
    sonuc = ex.skill_web_radar("https://www.cybersecurityventures.com/yazi/")

    assert "Gercek icerik" in sonuc
    assert cagrilan == [
        "https://www.cybersecurityventures.com/yazi/",
        "https://cybersecurityventures.com/yazi/",
    ]


def test_goreli_yonlendirme_mutlaklastiriliyor(vasi_module, monkeypatch):
    """Location: /artificial-intelligence gibi goreli yollar cozulmeli."""
    ex = vasi_module.execution
    cagrilan = _radar_kur(monkeypatch, ex, [
        SahteYonlendirme("/artificial-intelligence"),
        SahteWebYanit(b"<html><body><p>NIST sayfasi</p></body></html>"),
    ])
    sonuc = ex.skill_web_radar("https://www.nist.gov/ai")

    assert "NIST sayfasi" in sonuc
    assert cagrilan[1] == "https://www.nist.gov/artificial-intelligence"


def test_guvensiz_hedefe_yonlendirme_engelleniyor(vasi_module, monkeypatch):
    """KRITIK: izinli bir adres, ic aga yonlendirme yapamamali.

    requests'in allow_redirects=True ayari bu kontrolu YAPMAZ --
    yalnizca ilk URL dogrulanir. Elle takip bunu kapatir.
    """
    ex = vasi_module.execution
    cagrilan = _radar_kur(
        monkeypatch, ex,
        [SahteYonlendirme("http://192.168.1.1/admin")],
        guvenli=lambda u: "192.168" not in u,
    )
    sonuc = ex.skill_web_radar("https://iyi-gorunen-site.com/")

    assert "guvenli olmayan" in sonuc.lower()
    assert len(cagrilan) == 1, "guvensiz adrese istek atilmis!"


def test_yonlendirme_zinciri_sinirli(vasi_module, monkeypatch):
    """Sonsuz yonlendirme dongusu sistemi kilitlememeli."""
    ex = vasi_module.execution
    yanitlar = [SahteYonlendirme(f"https://site.com/{i}") for i in range(10)]
    cagrilan = _radar_kur(monkeypatch, ex, yanitlar)
    sonuc = ex.skill_web_radar("https://site.com/basla")

    assert "Cok fazla yonlendirme" in sonuc
    assert len(cagrilan) == ex.MAX_REDIRECT_HOPS + 1


def test_locationsiz_yonlendirme_reddediliyor(vasi_module, monkeypatch):
    ex = vasi_module.execution
    bozuk = SahteYonlendirme("x")
    bozuk.headers = {}
    _radar_kur(monkeypatch, ex, [bozuk])
    assert "Gecersiz yonlendirme" in ex.skill_web_radar("https://site.com/")


# ── Arama motoru engeli ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://www.google.com/search?q=yapay+zeka",
    "https://google.com/search?q=x",
    "https://www.google.com.tr/search?q=x",
    "https://google.de/search?q=x",
    "https://www.bing.com/search?q=x",
    "https://duckduckgo.com/?q=x",
    "https://yandex.com.tr/search/?text=x",
])
def test_arama_motorlari_engelleniyor(vasi_module, url):
    """Arama sonuc sayfalari kazinamaz; model bos icerikten iddia uretir."""
    assert vasi_module.access.is_search_engine(url), f"{url} tespit edilmedi"


@pytest.mark.parametrize("url", [
    "https://www.nist.gov/artificial-intelligence",
    "https://arxiv.org/abs/2109.01610",
    "https://www.cisa.gov/news-events/alerts",
    "https://blog.google/technology/ai/",
])
def test_normal_sayfalar_engellenmiyor(vasi_module, url):
    """blog.google gibi adresler arama motoru DEGILDIR."""
    assert not vasi_module.access.is_search_engine(url), f"{url} yanlislikla engellendi"


def test_radar_arama_motorunu_reddediyor(vasi_module, monkeypatch):
    """Uctan uca: arama URL'sine hic istek atilmamali."""
    ex = vasi_module.execution
    cagrilan = []
    monkeypatch.setattr(ex, "is_safe_url", lambda u: True)
    monkeypatch.setattr(ex.requests, "get", lambda u, **kw: cagrilan.append(u))

    sonuc = ex.skill_web_radar("https://www.google.com/search?q=test")

    assert "Arama motoru" in sonuc
    assert "/ara" in sonuc, "kullaniciya alternatif onerilmiyor"
    assert cagrilan == [], "arama motoruna istek atilmis"


def test_arac_aciklamasi_arama_motoru_olmadigini_soyluyor(vasi_module):
    """Model, aracin ne ICIN olmadigini da bilmeli.

    Onceki aciklama 'Arastirma yapmak icin zorunludur' diyordu;
    model bunu okuyup elinde adres olmadan Google'a gitti ve
    bos sayfadan kaynaksiz iddialar uretti.
    """
    ex = vasi_module.execution
    radar = next(
        t for t in ex.OPENCLAW_TOOLS
        if t["function"]["name"] == "skill_web_radar"
    )
    aciklama = radar["function"]["description"].lower()
    assert "arama motoru" in aciklama
    assert "zorunludur" not in aciklama


def test_sistem_promptu_ara_komutuna_yonlendiriyor(vasi_module):
    """Model /ara komutunun varligini bilmeli."""
    prompt = vasi_module.build_system_prompt("test-model")
    assert "/ara" in prompt
    assert "uydurma" in prompt.lower()


# ── Zaman farkindaligi ───────────────────────────────────────────────────────

def test_sistem_promptu_bugunun_tarihini_iceriyor(vasi_module):
    """Model kendini gecmiste sanmamali.

    Tarih verilmezse model egitim verisinin oldugu yili "bugun"
    sanar ve eskimis bilgiyi guncel gibi sunar. Bu uydurma degil,
    zaman korlugudur -- ama sonucu ayni: yanlis bilgi.
    """
    from datetime import datetime
    bugun = datetime.now().strftime("%d.%m.%Y")
    prompt = vasi_module.build_system_prompt("test-model")
    assert bugun in prompt, f"'{bugun}' promptta yok"


def test_kod_promptu_da_tarih_iceriyor(vasi_module):
    """Kutuphane surumleri de eskiyor."""
    from datetime import datetime
    bugun = datetime.now().strftime("%d.%m.%Y")
    assert bugun in vasi_module.build_code_system_prompt("test-model")


def test_promptlar_bilinmiyorsa_soylemeyi_istiyor(vasi_module):
    """Tahmin etmek yerine bilmedigini soylemesi istenmeli."""
    prompt = vasi_module.build_system_prompt("test-model").lower()
    assert "tahmin etme" in prompt or "uydurma" in prompt