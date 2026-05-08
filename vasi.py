import os
import json
import glob
import ipaddress
import socket
import requests
import logging
import html
from functools import wraps
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from ollama import Client
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes, CallbackQueryHandler
)

load_dotenv()

# ── ENVIRONMENT VALIDATION ────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_TELEGRAM_ID = os.getenv("MY_TELEGRAM_ID")
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/app/workspace")).resolve()
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")  # Optional güvenlik
LOG_FILE = Path(os.getenv("VASI_LOG_FILE", "/tmp/vasi_audit.log"))

if not TOKEN:
    raise ValueError("❌ TELEGRAM_BOT_TOKEN env variable zorunludur!")
if not MY_TELEGRAM_ID:
    raise ValueError("❌ MY_TELEGRAM_ID env variable zorunludur!")
if not WORKSPACE.exists():
    raise ValueError(f"❌ WORKSPACE_DIR mevcut değil: {WORKSPACE}")

# ── OLLAMA CLIENT SETUP (API KEY SECURITY) ────────────────────────────────────
# Ollama bağlantısını API key ile güvenli hale getir
ollama_headers = {}
if OLLAMA_API_KEY:
    ollama_headers["X-API-Key"] = OLLAMA_API_KEY
    logger_setup_msg = f"✅ Ollama API Key ile güvenli bağlantı"
else:
    logger_setup_msg = f"⚠️ Ollama API Key ayarlanmamış (localhost ortamında güvenli)"

ollama_client = Client(host=OLLAMA_HOST, headers=ollama_headers if ollama_headers else None)

# ── LOGGING SETUP ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('vasi')

# Log Ollama setup durumunu başta
logger.debug(logger_setup_msg)

# ── CONSTANTS ────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_WEB_TIMEOUT = 10  # saniye
MAX_WEB_BYTES = 2 * 1024 * 1024  # 2MB
RATE_LIMIT_WINDOW = 60  # saniye
RATE_LIMIT_REQUESTS = 20  # İstek sayısı

# ── RATE LIMITING ───────────────────────────────────────────────────────────
USER_RATE_LIMITS = {}

# ── MODEL KADROSU ──────────────────────────────────────────────────────────────
MODELS = {
    "gatekeeper": "qwen3:30b",
    "strateji":   "command-r",
    "teknik":     "gemma3:27b",
    "kod":        "qwen3-coder:30b",
    "gorsel":     "qwen3-vl:30b",
}

# ── ALLOWED TOOLS WHITELIST ────────────────────────────────────────────────────
ALLOWED_TOOL_NAMES = {"skill_get_time", "skill_web_radar"}

# ══════════════════════════════════════════════════════════════════════════════
# 1. GÜVENLİK KATMANI
# ══════════════════════════════════════════════════════════════════════════════

def check_rate_limit(user_id: str) -> bool:
    """Rate limiting kontrolü - hızlı spam'a karşı."""
    now = datetime.now()
    if user_id not in USER_RATE_LIMITS:
        USER_RATE_LIMITS[user_id] = []
    
    # Pencereyi temizle (eski talepleri kaldır)
    USER_RATE_LIMITS[user_id] = [
        t for t in USER_RATE_LIMITS[user_id]
        if (now - t).total_seconds() < RATE_LIMIT_WINDOW
    ]
    
    # Limit kontrolü
    if len(USER_RATE_LIMITS[user_id]) >= RATE_LIMIT_REQUESTS:
        logger.warning(f"⚠️ Rate limit aşımı: {user_id}")
        return False
    
    USER_RATE_LIMITS[user_id].append(now)
    return True

def is_authorized(update: Update) -> bool:
    user_id = str(update.effective_user.id)
    if MY_TELEGRAM_ID and user_id != MY_TELEGRAM_ID:
        logger.warning(f"🚫 Yetkisiz erişim denemesi: {user_id}")
        return False
    if update.effective_chat.type != "private":
        logger.warning(f"🚫 Grup mesajı reddedildi: {update.effective_chat.id}")
        return False
    if update.message and update.message.forward_origin:
        logger.warning(f"🚫 Yönlendirilen mesaj reddedildi: {user_id}")
        return False
    if update.message:
        age = (datetime.now(timezone.utc) - update.message.date).total_seconds()
        if age > 60:
            logger.warning(f"🚫 Eski mesaj reddedildi (yaş: {age}s): {user_id}")
            return False
    return True

def safe_path(filename: str) -> Path | None:
    """Path traversal saldırılarına karşı korunan güvenli path çözümü."""
    try:
        target = (WORKSPACE / filename).resolve()
        if not target.is_relative_to(WORKSPACE):
            logger.warning(f"🚫 Path traversal denemesi: {filename}")
            return None
        return target
    except Exception as e:
        logger.error(f"Path çözümleme hatası: {e}")
        return None

def is_public_hostname(hostname: str) -> bool:
    """Hostname'in yalnizca public IP adreslerine cozuldugunu dogrular."""
    if hostname.lower() in {"localhost"}:
        logger.warning(f"🚫 Localhost erişim engellendi: {hostname}")
        return False

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as e:
        logger.warning(f"🚫 Hostname çözümlenemedi: {hostname} ({e})")
        return False

    if not addresses:
        return False

    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            logger.warning(f"🚫 Geçersiz IP çözümlemesi: {hostname} -> {address}")
            return False

        if not ip.is_global:
            logger.warning(f"🚫 Public olmayan IP engellendi: {hostname} -> {ip}")
            return False

    return True

def is_safe_url(url: str) -> bool:
    """SSRF ve kötü niyetli URL'lere karşı koruyan URL doğrulayıcı."""
    try:
        # Temel format kontrolü
        if not url or len(url) > 2048:
            return False
        
        parsed = urlparse(url)
        
        # Protokol kontrolü
        if parsed.scheme not in ["http", "https"]:
            logger.warning(f"🚫 Geçersiz protokol: {parsed.scheme}")
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False

        if parsed.username or parsed.password:
            logger.warning("🚫 URL kullanıcı bilgisi içeriyor")
            return False

        return is_public_hostname(hostname)
    except Exception as e:
        logger.error(f"URL doğrulama hatası: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
# 2. OPENCLAW YETENEKLERİ (READ-ONLY TOOLS)
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# 3. DOSYA İŞLEMLERİ (KAPALI DEVRE)
# ══════════════════════════════════════════════════════════════════════════════

def list_workspace_files() -> str:
    files = list(WORKSPACE.rglob("*"))
    if not files: return "Workspace bos."
    return "Workspace icerigi:\n" + "\n".join([f"  {f.relative_to(WORKSPACE)}" for f in sorted(files) if f.is_file()])

def read_file(filename: str) -> tuple[str, str]:
    """Güvenli dosya okuma."""
    path = safe_path(filename)
    if path is None:
        return "", "Güvenlik: Workspace dışına çıkış engellendi."
    if not path.exists():
        matches = list(WORKSPACE.rglob(filename))
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

def save_file(filename: str, content: str) -> str:
    """Güvenli dosya yazma - boyut sınırı ile."""
    path = safe_path(filename)
    if path is None:
        logger.warning(f"🚫 Dosya yazma engellendi: {filename}")
        return "Güvenlik: Engellendi."
    
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

# ══════════════════════════════════════════════════════════════════════════════
# 4. YÖNLENDİRME (ROUTING) VE BOT KOMUTLARI
# ══════════════════════════════════════════════════════════════════════════════

def pick_model(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["kod", "script", "python"]): return MODELS["kod"]
    if any(k in t for k in ["analiz", "gorsel", "tablo"]): return MODELS["gorsel"]
    if any(k in t for k in ["arastir", "neden", "web", "site", "okut"]): return MODELS["teknik"]
    if any(k in t for k in ["e-posta", "rapor", "taslak"]): return MODELS["strateji"]
    return MODELS["gatekeeper"]

def build_system_prompt(model: str) -> str:
    return (
        f"Sen Vasi. {model} motoruyla calisiyorsun. Turkce yanit ver. "
        "Yüksek sinyalli, net, profesyonel ve muhendislik olcutlerine uygun konus. "
        "Eger internetten veya gercek zamanli bir bilgi alman gerekirse yeteneklerini (tools) kullan."
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiz. Lütfen bekleyiniz.")
        return
    logger.info(f"👤 Başlangıç komutu: {update.effective_user.id}")
    await update.message.reply_text("Vasi aktif. OpenClaw modulleri devrede. /liste ile workspace'i gorebilirsiniz.")

async def cmd_liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiniz. Lütfen bekleyiniz.")
        return
    logger.info(f"📋 Liste komutu: {update.effective_user.id}")
    await update.message.reply_text(list_workspace_files())

async def cmd_rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı istek gönderdiz. Lütfen bekleyiniz.")
        return
    
    konu = " ".join(context.args)
    if not konu:
        await update.message.reply_text("❌ Kullanım: /rapor <konu>")
        return
    
    logger.info(f"📊 Rapor komutu: {update.effective_user.id} - Konu: {konu[:50]}")
    
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        response = ollama_client.chat(
            model=MODELS["strateji"],
            messages=[{"role": "user", "content": f"Detayli rapor yaz: {konu}"}]
        )
        sonuc = response["message"]["content"]
        out_name = f"rapor_{datetime.now().strftime('%H%M')}.md"
        context.user_data["pending_save"] = {"filename": out_name, "content": sonuc}
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Kaydet", callback_data="save_pending:evet"),
            InlineKeyboardButton("İptal", callback_data="save_pending:iptal")
        ]])
        await update.message.reply_text(f"Rapor hazir. Kaydedilsin mi?\n\n{sonuc[:300]}...", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"❌ Rapor üretme hatası: {e}", exc_info=True)
        await update.message.reply_text("❌ Rapor oluşturulamadı. Lütfen daha sonra deneyin.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not is_authorized(update):
        await query.edit_message_text("🚫 Yetkisiz erişim.")
        return
    
    logger.info(f"🔘 Callback: {query.data} - {update.effective_user.id}")
    
    if query.data == "save_pending:iptal":
        await query.edit_message_text("❌ İptal edildi.")
    elif query.data == "save_pending:evet":
        pending = context.user_data.get("pending_save")
        if pending:
            result = save_file(pending["filename"], pending["content"])
            await query.edit_message_text(result)
        else:
            await query.edit_message_text("❌ Kaydetme verisi bulunamadı.")

# ══════════════════════════════════════════════════════════════════════════════
# 5. AJAN AKIŞI (AGENTIC WORKFLOW + TOOL CALLING)
# ══════════════════════════════════════════════════════════════════════════════

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update): return
    if not check_rate_limit(str(update.effective_user.id)):
        await update.message.reply_text("⚠️ Çok hızlı mesaj gönderdiniz. Lütfen bekleyiniz.")
        return
    
    metin = update.message.text
    user_id = update.effective_user.id
    logger.info(f"💬 Mesaj alındı: {user_id} - {metin[:50]}...")
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    model = pick_model(metin)
    messages = [
        {"role": "system", "content": build_system_prompt(model)},
        {"role": "user", "content": metin}
    ]

    try:
        # AŞAMA 1: Modeli Yeteneklerle Birlikte Çağır
        response = ollama_client.chat(model=model, messages=messages, tools=OPENCLAW_TOOLS)
        message_data = response["message"]
        
        # AŞAMA 2: Model Bir Yetenek Kullanmak İstedi Mi?
        if message_data.get("tool_calls"):
            await update.message.reply_text("⚡ [OpenClaw] Ajan dis dunyadan veri cekiyor...")
            
            messages.append(message_data) # Modelin isteğini geçmişe ekle
            
            for tool in message_data["tool_calls"]:
                func_name = tool["function"]["name"]
                args = tool["function"]["arguments"]
                
                # ✅ TOOL CALL VALIDATION: Whitelist kontrolü
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
            
            # AŞAMA 3: Aracı Kullandıktan Sonra Final Yorumunu Al
            final_response = ollama_client.chat(model=model, messages=messages)
            yanit = final_response["message"]["content"]
        else:
            yanit = message_data.get("content", "")

        logger.info(f"✅ Yanıt hazırlandı: {user_id} (Model: {model})")
        for i in range(0, len(yanit), 4000):
            await update.message.reply_text(f"[{model.upper()}]\n" + yanit[i:i+4000])

    except requests.ConnectTimeout:
        logger.error(f"⏱️ Ollama bağlantı timeout: {user_id}")
        await update.message.reply_text("❌ Model bağlantı zaman aşımı. Lütfen daha sonra deneyin.")
    except requests.RequestException as e:
        logger.error(f"🌐 Ollama iletişim hatası: {e}")
        await update.message.reply_text("❌ Model servisi ulaşılamıyor.")
    except Exception as e:
        logger.error(f"❌ Mesaj işleme kritik hatası: {e}", exc_info=True)
        await update.message.reply_text("❌ İçsel hata oluştu. Sistem yöneticisine başvurunuz.")

if __name__ == "__main__":
    try:
        logger.info("="*60)
        logger.info("🚀 Vasi başlatılıyor...")
        logger.info(f"📂 Workspace: {WORKSPACE}")
        logger.info(f"🤖 Ollama Host: {OLLAMA_HOST}")
        logger.info(logger_setup_msg)
        logger.info("="*60)
        
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("liste", cmd_liste))
        app.add_handler(CommandHandler("rapor", cmd_rapor))
        app.add_handler(CallbackQueryHandler(callback_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
        
        logger.info("✅ Vasi aktif. OpenClaw yetenekleri devrede.")
        logger.info("📡 Polling başlatılıyor...")
        app.run_polling()
    except KeyboardInterrupt:
        logger.info("⏹️  Bot durduruldu (Keyboard Interrupt)")
    except Exception as e:
        logger.critical(f"💥 KRITIK HATA: {e}", exc_info=True)
        raise
