"""Execution katmani: fiili islemleri gerceklestirir.

DACE mimarisinin Execution katmani. "Simdi yap" adimindaki tum
yan etkili islemler burada toplanir: dosya okuma/yazma/silme ve
dis dunyaya acilan araclar.

Bu katman access.py uzerinden gecmeden dosya sistemine dokunmaz.
Her yol scoped_path() ile dogrulanir, her yazma is_allowed_write_file()
ile kontrol edilir.
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from ollama import Client, ResponseError

from access import (
    ALLOWED_TOOL_NAMES,
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

def skill_web_radar(url: str) -> str:
    """Güvenli web scraping - SSRF ve XSS korumalı."""
    if not is_safe_url(url):
        logger.warning(f"🚫 Güvensiz URL reddedildi: {url}")
        return "Hata: Güvensiz veya geçersiz URL."
    
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Vasi-Bot/1.0)"}
        response = requests.get(
            url,
            headers=headers,
            timeout=MAX_WEB_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
        response.raise_for_status()

        if 300 <= response.status_code < 400:
            logger.warning(f"🚫 Redirect engellendi: {url} -> {response.headers.get('Location')}")
            return "Hata: Yonlendirme guvenlik nedeniyle engellendi."

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
            "description": "Bir web sitesinin (URL) metin icerigini okur. Arastirma yapmak icin zorunludur.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Tam web adresi (http://...)"}},
                "required": ["url"]
            }
        }
    }
]


async def run_model_with_tools(
    model: str,
    user_prompt: str,
    system_prompt: str | None = None,
    options: dict | None = None,
    on_tool_use: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """Ollama modelini guvenli tool whitelist'i ile calistirir.

    on_tool_use: Model bir arac cagirdiginda, arac calistirilmadan once
    beklenen async bildirim. Kullanici deneyimi icin opsiyoneldir.
    """
    started = time.perf_counter()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    try:
        response = ollama_client.chat(model=model, messages=messages, tools=OPENCLAW_TOOLS, options=options)
    except ResponseError as e:
        if getattr(e, "status_code", None) == 404:
            return (
                f"Model bulunamadı: {model}\n\n"
                f"Önce şu komutla modeli indir:\n"
                f"docker compose exec ollama ollama pull {model}"
            )
        logger.error(f"❌ Ollama model hatası: {e}", exc_info=True)
        OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=False, error=str(e))
        return f"Model hatası: {getattr(e, 'error', str(e))}"
    except Exception as e:
        logger.error(f"❌ Ollama çağrı hatası: {e}", exc_info=True)
        OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=False, error=str(e))
        return f"Model çalıştırma hatası: {e}"

    message_data = response["message"]

    if message_data.get("tool_calls"):
        if on_tool_use:
            await on_tool_use()
        messages.append(message_data)
        for tool in message_data["tool_calls"]:
            func_name = tool["function"]["name"]
            args = tool["function"].get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            if func_name not in ALLOWED_TOOL_NAMES:
                logger.warning(f"🚫 Yetkisiz tool çağrısı: {func_name}")
                tool_result = "Güvenlik: Bu araç kullanımı yasaktır."
            elif func_name == "skill_get_time":
                tool_result = skill_get_time()
            elif func_name == "skill_web_radar":
                tool_result = skill_web_radar(args.get("url", ""))
            else:
                tool_result = "Bilinmeyen arac."

            messages.append({"role": "tool", "content": tool_result, "name": func_name})

        try:
            final_response = ollama_client.chat(model=model, messages=messages, options=options)
        except ResponseError as e:
            if getattr(e, "status_code", None) == 404:
                return (
                    f"Model bulunamadı: {model}\n\n"
                    f"Önce şu komutla modeli indir:\n"
                    f"docker compose exec ollama ollama pull {model}"
                )
            logger.error(f"❌ Ollama final yanıt hatası: {e}", exc_info=True)
            OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=False, error=str(e))
            return f"Model hatası: {getattr(e, 'error', str(e))}"
        except Exception as e:
            logger.error(f"❌ Ollama final çağrı hatası: {e}", exc_info=True)
            OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=False, error=str(e))
            return f"Model çalıştırma hatası: {e}"

        result = final_response["message"].get("content", "")
        OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=True)
        return result

    result = message_data.get("content", "")
    OBSERVABILITY.record_model_call(model, int((time.perf_counter() - started) * 1000), ok=True)
    return result