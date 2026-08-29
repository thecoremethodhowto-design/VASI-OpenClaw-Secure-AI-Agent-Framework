"""Execution katmani: fiili islemleri gerceklestirir.

DACE mimarisinin Execution katmani. "Simdi yap" adimindaki tum
yan etkili islemler burada toplanir: dosya okuma/yazma/silme ve
dis dunyaya acilan araclar.

Bu katman access.py uzerinden gecmeden dosya sistemine dokunmaz.
Her yol scoped_path() ile dogrulanir, her yazma is_allowed_write_file()
ile kontrol edilir.
"""
import logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from access import (
    WORKSPACE,
    is_allowed_write_file,
    is_safe_url,
    scoped_path,
)

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