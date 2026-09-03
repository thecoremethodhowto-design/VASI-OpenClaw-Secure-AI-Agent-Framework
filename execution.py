"""Execution katmani: fiili islemleri gerceklestirir.

DACE mimarisinin Execution katmani. "Simdi yap" adimindaki tum
yan etkili islemler burada toplanir: dosya okuma/yazma/silme ve
dis dunyaya acilan araclar.

Bu katman access.py uzerinden gecmeden dosya sistemine dokunmaz.
Her yol scoped_path() ile dogrulanir, her yazma is_allowed_write_file()
ile kontrol edilir.
"""
import html
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ollama import Client, ResponseError

from access import (
    ALLOWED_TOOL_NAMES,
    is_search_engine,
    WORKSPACE,
    is_allowed_write_file,
    is_safe_url,
    scoped_path,
)
from observability import OBSERVABILITY

logger = logging.getLogger("vasi")

# ── SABITLER ─────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_WEB_TIMEOUT = 10  # saniye
MAX_WEB_BYTES = 2 * 1024 * 1024  # 2MB


# ── OPENCLAW ARACLARI (READ-ONLY TOOLS) ───────────────────────

def skill_get_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Yonlendirme takibi kac adim surebilir.
# requests'in otomatik takibini KULLANMIYORUZ: o, ara adimlari
# dogrulamadan izler ve izinli bir adresten ic aga yonlendirme
# yapilmasina acik kalir. Burada her adim yeniden dogrulanir.
MAX_REDIRECT_HOPS = 3


def _fetch_with_verified_redirects(url: str, headers: dict):
    """Yonlendirmeleri ELLE takip eder, her adimda SSRF kontrolu yapar.

    Donen deger: (response, son_url) veya (None, hata_mesaji)

    Bu, allow_redirects=True'dan daha guvenlidir: requests otomatik
    takip ederken yalnizca ilk URL dogrulanmis olur; ara adimlar
    kontrol disi kalir. Burada her adres, izlenmeden once
    is_safe_url()'den gecer.
    """
    mevcut = url
    for adim in range(MAX_REDIRECT_HOPS + 1):
        response = requests.get(
            mevcut,
            headers=headers,
            timeout=MAX_WEB_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )

        if not (300 <= response.status_code < 400):
            response.raise_for_status()
            return response, mevcut

        hedef = response.headers.get("Location")
        if not hedef:
            logger.warning(f"🚫 Location basligi olmayan yonlendirme: {mevcut}")
            return None, "Hata: Gecersiz yonlendirme."

        # Goreli yolu mutlak hale getir (ornek: /artificial-intelligence)
        yeni_url = urljoin(mevcut, hedef)

        # KRITIK: her adim yeniden dogrulanir.
        if not is_safe_url(yeni_url):
            logger.warning(f"🚫 Guvensiz yonlendirme engellendi: {mevcut} -> {yeni_url}")
            return None, "Hata: Yonlendirme guvenli olmayan bir adrese gidiyor."

        logger.info(f"↪️ Yonlendirme takip edildi ({adim + 1}): {mevcut} -> {yeni_url}")
        mevcut = yeni_url

    logger.warning(f"🚫 Yonlendirme siniri asildi: {url}")
    return None, "Hata: Cok fazla yonlendirme."


def skill_web_radar(url: str) -> str:
    """Güvenli web scraping - SSRF ve XSS korumalı."""
    if not is_safe_url(url):
        logger.warning(f"🚫 Güvensiz URL reddedildi: {url}")
        return "Hata: Güvensiz veya geçersiz URL."

    if is_search_engine(url):
        logger.warning(f"🚫 Arama motoru reddedildi: {url}")
        return (
            "Hata: Arama motoru sonuc sayfalari okunamaz. "
            "Bu arac belirli bir makale veya belge adresi icindir. "
            "Guncel arastirma icin kullaniciya /ara komutunu oner."
        )

    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Vasi-Bot/1.0)"}
        response, sonuc = _fetch_with_verified_redirects(url, headers)
        if response is None:
            return sonuc

        content_type = response.headers.get("Content-Type", "")
        if content_type and "text/html" not in content_type and "text/plain" not in content_type:
            logger.warning(f"🚫 Desteklenmeyen içerik türü: {content_type}")
            return "Hata: Desteklenmeyen icerik turu."

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_WEB_BYTES:
                logger.warning(f"🚫 Web yanıtı çok büyük: {url}")
                return "Hata: Web yaniti cok buyuk."
            chunks.append(chunk)
        
        # Charset kontrol et
        if response.encoding is None:
            response.encoding = 'utf-8'

        response_text = b"".join(chunks).decode(response.encoding, errors="replace")
        
        soup = BeautifulSoup(response_text, 'html.parser')
        
        # Tehlikeli elementleri kaldır
        for element in soup(["script", "style", "iframe", "object"]):
            element.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        
        # HTML entities'i escape et (XSS koruması)
        text = html.escape(text)
        
        logger.info(f"✅ Web radar: {url[:50]}...")
        return text[:8000] if len(text) > 8000 else text
    except requests.Timeout:
        logger.error(f"⏱️ Web radar timeout: {url}")
        return "Hata: Istek zaman asımı (timeout)."
    except requests.RequestException as e:
        logger.error(f"🌐 Web radar hatasI: {e}")
        return f"Radar Hatasi: Sayfa yüklenemedi."
    except Exception as e:
        logger.error(f"❌ Web radar kritik hata: {e}", exc_info=True)
        return "Radar Hatasi: İçsel hata."


# ── DOSYA ISLEMLERI (KAPALI DEVRE) ────────────────────────────

def list_workspace_files(scope: str = "general") -> str:
    files = list(WORKSPACE.rglob("*"))
    if not files: return "Workspace bos."
    visible = []
    for f in sorted(files):
        if f.is_file() and is_scope_allowed(f, scope):
            visible.append(f"  {f.relative_to(WORKSPACE)}")
    if not visible:
        return f"Scope '{scope}' icin görünür dosya yok."
    return "Workspace icerigi:\n" + "\n".join(visible)

def read_file(filename: str, scope: str = "general") -> tuple[str, str]:
    """Güvenli dosya okuma."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        return "", "Güvenlik: Bu scope için dosya erişimi engellendi."
    if not path.exists():
        matches = [m for m in WORKSPACE.rglob(filename) if m.is_file() and is_scope_allowed(m, scope)]
        if not matches:
            logger.warning(f"📄 Dosya bulunamadı: {filename}")
            return "", f"'{filename}' bulunamadi."
        path = matches[0]
    try:
        if not path.is_file():
            return "", "Hata: Sadece dosya okunabilir."
        if path.stat().st_size > MAX_FILE_SIZE:
            logger.warning(f"📦 Okuma engellendi, dosya çok büyük: {filename}")
            return "", f"Hata: Dosya çok büyük (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."
        content = path.read_text(encoding="utf-8", errors="replace")
        logger.info(f"📖 Dosya okundu: {path.relative_to(WORKSPACE)}")
        return content[:12000], ""
    except PermissionError:
        logger.error(f"🚫 İzin hatası: {filename}")
        return "", f"Hata: Dosya erişim izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya okuma hatası: {e}")
        return "", "Hata: Dosya okunamadı."

def save_file(filename: str, content: str, scope: str = "general") -> str:
    """Güvenli dosya yazma - boyut sınırı ile."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya yazma engellendi: {filename}")
        return "Güvenlik: Bu scope için yazma engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı: {filename}")
        return "Güvenlik: Sadece .md, .txt, .json, .yaml, .yml ve .csv dosyaları yazılabilir."
    
    # File size kontrolü
    if len(content) > MAX_FILE_SIZE:
        logger.warning(f"📦 Dosya çok büyük: {filename} ({len(content)} bytes)")
        return f"Hata: Dosya çok büyük (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info(f"💾 Dosya kaydedildi: {path.relative_to(WORKSPACE)} ({len(content)} bytes)")
        return f"'{filename}' kaydedildi."
    except PermissionError:
        logger.error(f"🚫 Yazma izni yok: {filename}")
        return "Hata: Dosya yazma izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya yazma hatası: {e}")
        return "Hata: Dosya kaydedilemedi."

def append_file(filename: str, content: str, scope: str = "general") -> str:
    """Güvenli dosya ekleme - tarih/saat damgası ile."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya ekleme engellendi: {filename}")
        return "Güvenlik: Bu scope için ekleme engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı: {filename}")
        return "Güvenlik: Sadece .md, .txt, .json, .yaml, .yml ve .csv dosyalarına ek yapılabilir."

    stamped_content = (
        f"\n\n---\n"
        f"### {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{content.strip()}\n"
    )

    current_size = path.stat().st_size if path.exists() and path.is_file() else 0
    if current_size + len(stamped_content.encode("utf-8")) > MAX_FILE_SIZE:
        logger.warning(f"📦 Dosya ekleme limiti aşıldı: {filename}")
        return f"Hata: Dosya çok büyük olur (max {MAX_FILE_SIZE / 1024 / 1024:.0f}MB)."

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(stamped_content)
        logger.info(f"➕ Dosyaya eklendi: {path.relative_to(WORKSPACE)}")
        return f"'{filename}' dosyasına tarihli kayıt eklendi."
    except PermissionError:
        logger.error(f"🚫 Yazma izni yok: {filename}")
        return "Hata: Dosya yazma izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya ekleme hatası: {e}")
        return "Hata: Dosyaya eklenemedi."

def delete_file(filename: str, scope: str = "general") -> str:
    """Güvenli dosya silme - sadece workspace icindeki normal dosyalar."""
    path = scoped_path(filename, scope=scope)
    if path is None:
        logger.warning(f"🚫 Dosya silme engellendi: {filename}")
        return "Güvenlik: Bu scope için silme engellendi."
    if not is_allowed_write_file(path):
        logger.warning(f"🚫 Desteklenmeyen dosya uzantısı silme isteği: {filename}")
        return "Güvenlik: Sadece güvenli not/veri dosyaları silinebilir."

    if path.name.startswith("."):
        return "Güvenlik: Gizli/korumalı dosyalar silinemez."
    if not path.exists():
        return f"'{filename}' bulunamadi."
    if not path.is_file():
        return "Hata: Sadece dosya silinebilir."

    try:
        relative = path.relative_to(WORKSPACE)
        path.unlink()
        logger.warning(f"🗑️ Dosya silindi: {relative}")
        return f"'{relative}' silindi."
    except PermissionError:
        logger.error(f"🚫 Silme izni yok: {filename}")
        return "Hata: Dosya silme izni yok."
    except Exception as e:
        logger.error(f"❌ Dosya silme hatası: {e}")
        return "Hata: Dosya silinemedi."

def split_filename_and_content(text: str) -> tuple[str, str] | None:
    if "|" not in text:
        return None
    filename, content = text.split("|", 1)
    filename = filename.strip()
    content = content.strip()
    if not filename or not content:
        return None
    return filename, content

# ── MODEL CAGIRMA ─────────────────────────────────────────────

# Ollama istemcisi. LiteLLM proxy'sine gecis Faz 3b'de yapilacak.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# Uzak bir Ollama sunucusuna anahtarsiz baglanmayi engelle.
# Bu dogrulama istemcinin YANINDA durur: kontrol ile korudugu sey
# ayni yerde olsun ki biri digeri olmadan tasinamasin.
LOCAL_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"}
_ollama_hostname = urlparse(OLLAMA_HOST).hostname or ""
if not OLLAMA_API_KEY and _ollama_hostname not in LOCAL_OLLAMA_HOSTS:
    raise ValueError("❌ Uzak Ollama sunucusu için OLLAMA_API_KEY zorunludur!")

logger_setup_msg = (
    "✅ Ollama API Key ile güvenli bağlantı" if OLLAMA_API_KEY
    else "⚠️ Ollama API Key ayarlanmamış (localhost ortamında güvenli)"
)

_ollama_headers = {"X-API-Key": OLLAMA_API_KEY} if OLLAMA_API_KEY else None
ollama_client = Client(host=OLLAMA_HOST, headers=_ollama_headers)

# ── LITELLM PROXY ─────────────────────────────────────────────
# Gecis bayragi. Varsayilan KAPALI: bayrak acilmadikca davranis
# degismez. Canli ortamda sorun cikarsa .env'de false yapip
# eski yola donebilirsin.
USE_LITELLM = os.getenv("USE_LITELLM", "false").strip().lower() in ("1", "true", "yes")
LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://litellm:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
MODEL_TIMEOUT = int(os.getenv("MODEL_TIMEOUT_SECONDS", "180"))


class ChatBackendError(Exception):
    """Model cagirma hatasi. Iki backend'in hatalarini tek tipe indirger."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _chat_ollama(model: str, messages: list, tools=None, options=None) -> dict:
    """Ollama'ya dogrudan cagri. Mesaj sozlugunu dondurur."""
    try:
        resp = ollama_client.chat(
            model=model, messages=messages, tools=tools, options=options
        )
    except ResponseError as e:
        raise ChatBackendError(
            getattr(e, "error", str(e)), status_code=getattr(e, "status_code", None)
        ) from e
    except Exception as e:
        raise ChatBackendError(str(e)) from e
    return resp["message"]


def _chat_litellm(model: str, messages: list, tools=None, options=None) -> dict:
    """LiteLLM proxy'sine OpenAI uyumlu cagri. Mesaj sozlugunu dondurur."""
    payload: dict = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
    if options:
        payload.update(options)

    try:
        r = requests.post(
            f"{LITELLM_BASE_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
            json=payload,
            timeout=MODEL_TIMEOUT,
        )
    except requests.RequestException as e:
        raise ChatBackendError(f"LiteLLM'e ulasilamadi: {e}") from e

    if r.status_code >= 400:
        raise ChatBackendError(r.text[:300], status_code=r.status_code)

    try:
        return r.json()["choices"][0]["message"]
    except (KeyError, IndexError, ValueError) as e:
        raise ChatBackendError(f"Beklenmeyen yanit yapisi: {e}") from e


def _chat(model: str, messages: list, tools=None, options=None) -> dict:
    """Aktif backend'e gore sohbet cagrisi yapar."""
    backend = _chat_litellm if USE_LITELLM else _chat_ollama
    return backend(model, messages, tools=tools, options=options)


# Bazi modeller (ozellikle Qwen ailesi) arac cagrisini yapisal alan
# yerine metin icinde <tool_call>{...}</tool_call> olarak uretir.
# Bu, proxy uzerinden gecerken mesaj gecmisinin tam korunamadigi
# durumlarda olusur. Yapisal alan bossa metne de bakariz.
_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _tool_calls_from_text(content: str) -> list[dict]:
    """Metne gomulmus arac cagrilarini ayristirir."""
    bulunan = []
    for eslesme in _TOOL_CALL_TAG.finditer(content or ""):
        try:
            veri = json.loads(eslesme.group(1))
        except json.JSONDecodeError:
            continue
        ad = veri.get("name")
        if not ad:
            continue
        args = veri.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        bulunan.append({"id": None, "name": ad, "arguments": args})
    return bulunan


def _strip_tool_call_tags(content: str) -> str:
    """Kullaniciya gosterilecek metinden arac cagrisi etiketlerini temizler."""
    return _TOOL_CALL_TAG.sub("", content or "").strip()


def _normalize_tool_calls(message: dict) -> list[dict]:
    """Iki API'nin arac cagri formatini tek tipe indirger.

    Ollama: arguments bir sozluk.
    OpenAI: arguments bir JSON metni, ayrica tool_call_id tasir.
    """
    normalize = []
    for cagri in message.get("tool_calls") or []:
        fn = cagri.get("function", {}) or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        normalize.append(
            {"id": cagri.get("id"), "name": fn.get("name", ""), "arguments": args}
        )

    # Yapisal alan bossa metne bak.
    if not normalize:
        normalize = _tool_calls_from_text(message.get("content", ""))

    return normalize


def _tool_result_message(cagri: dict, sonuc: str) -> dict:
    """Arac sonucunu her iki API'nin de kabul ettigi bicimde paketler."""
    mesaj = {"role": "tool", "content": sonuc, "name": cagri["name"]}
    if cagri.get("id"):
        mesaj["tool_call_id"] = cagri["id"]
    return mesaj


OPENCLAW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "skill_get_time",
            "description": "Sistemin guncel tarih ve saatini verir.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_web_radar",
            "description": ("BELIRLI bir web sayfasinin metin icerigini okur. "
                               "Arama motoru DEGILDIR: google/bing gibi sorgu adresleri reddedilir. "
                               "Yalnizca kullanicinin verdigi ya da onceki bir kaynakta gecen "
                               "tam bir sayfa adresi ile kullan. Adres yoksa bu araci CAGIRMA."),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Tam web adresi (http://...)"}},
                "required": ["url"]
            }
        }
    }
]


# Model araclari cagirdiktan sonra kac tur daha devam edebilir.
# Sinir olmadan model kendini tekrar edebilir; cok dusuk olursa
# birden fazla arac gerektiren istekler yarim kalir.
MAX_TOOL_ROUNDS = 3


async def run_model_with_tools(
    model: str,
    user_prompt: str,
    system_prompt: str | None = None,
    options: dict | None = None,
    on_tool_use: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """Modeli guvenli tool whitelist'i ile calistirir.

    Aktif backend USE_LITELLM bayragina gore secilir; bu fonksiyon
    ikisini de ayni sekilde gorur (bkz. _chat ve _normalize_tool_calls).

    ONEMLI: tools parametresi HER turda gonderilir. Gonderilmezse model
    gecmiste arac cagrisi sozdizimi gorur ama elinde arac tanimi olmaz;
    bu durumda deseni metin olarak taklit eder ve <tool_call>...</tool_call>
    seklinde ham cikti uretir.

    on_tool_use: Model ilk kez arac cagirdiginda beklenen async bildirim.
    """
    started = time.perf_counter()
    bildirildi = False

    def _gecen_ms() -> int:
        return int((time.perf_counter() - started) * 1000)

    def _hata_metni(e: ChatBackendError) -> str:
        if e.status_code == 404:
            return (
                f"Model bulunamadı: {model}\n\n"
                f"LiteLLM kullaniyorsan litellm/config.yaml'da tanimli mi kontrol et.\n"
                f"Dogrudan Ollama kullaniyorsan once indir:\n"
                f"docker compose exec ollama ollama pull {model}"
            )
        return f"Model hatası: {e}"

    def _basarili(icerik: str) -> str:
        OBSERVABILITY.record_model_call(model, _gecen_ms(), ok=True)
        return _strip_tool_call_tags(icerik)

    def _basarisiz(e: ChatBackendError) -> str:
        logger.error(f"❌ Model çağrı hatası: {e}", exc_info=True)
        OBSERVABILITY.record_model_call(model, _gecen_ms(), ok=False, error=str(e))
        return _hata_metni(e)

    messages: list = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    for tur in range(MAX_TOOL_ROUNDS):
        try:
            message_data = _chat(model, messages, tools=OPENCLAW_TOOLS, options=options)
        except ChatBackendError as e:
            return _basarisiz(e)

        tool_calls = _normalize_tool_calls(message_data)
        if not tool_calls:
            return _basarili(message_data.get("content", ""))

        if on_tool_use and not bildirildi:
            await on_tool_use()
            bildirildi = True

        messages.append(message_data)

        for cagri in tool_calls:
            ad = cagri["name"]
            args = cagri["arguments"]

            if ad not in ALLOWED_TOOL_NAMES:
                logger.warning(f"🚫 Yetkisiz tool çağrısı: {ad}")
                sonuc = "Güvenlik: Bu araç kullanımı yasaktır."
            elif ad == "skill_get_time":
                sonuc = skill_get_time()
            elif ad == "skill_web_radar":
                sonuc = skill_web_radar(args.get("url", ""))
            else:
                sonuc = "Bilinmeyen arac."

            messages.append(_tool_result_message(cagri, sonuc))

    # Tur siniri asildi: araclarsiz son bir cagri ile metin cevap iste.
    logger.warning(f"⚠️ Arac turu siniri asildi ({MAX_TOOL_ROUNDS}): {model}")
    try:
        son = _chat(model, messages, options=options)
    except ChatBackendError as e:
        return _basarisiz(e)
    return _basarili(son.get("content", ""))