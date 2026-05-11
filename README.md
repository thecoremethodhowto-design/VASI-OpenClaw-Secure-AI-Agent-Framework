# VASI OpenClaw Secure AI Agent Framework

VASI, Telegram uzerinden kontrol edilen, yerel Ollama modelleriyle calisan ve guvenlik sinirlari onceden tanimlanmis kisisel bir AI ajan iskeletidir. Fikir yakalama, not tutma, YouTube senaryosu uretme, kod yardimi ve istege bagli Gemini + Google Search destekli internet arastirmasi icin tasarlanmistir.

> Not: Bu repo resmi OpenClaw paketini kullanmaz. OpenClaw tarzinda; tool whitelist, workspace sandbox, onayli dosya islemleri ve guvenlik raporu mantigiyla kurulmus bagimsiz bir VASI ajan mimarisidir.

## Ozellikler

- Telegram bot arayuzu
- Yerel Ollama model baglantisi
- Workspace icinde bolmeli sandbox (`youtube`, `projeler`, `notlar`, `skills`)
- Yazma/silme icin Telegram onay butonu + TTL
- Tarih-saat damgali not ekleme
- YouTube kanal tarzi kaydetme
- Baslik, aciklama, kapak fikri ve senaryo uretme
- Proje dosyalarini dikkate alan kod yardimi
- Deterministik `/guvenlik` raporu
- Gemini API ile kaynakli internet arastirmasi
- Docker hardening: read-only filesystem, tmpfs, no-new-privileges, cap_drop

## Guvenlik Modeli

VASI'nin temel guvenlik prensibi: model onerir, kritik islemler kullanici onayi olmadan yapilmaz.

- Sadece `.env` icindeki `MY_TELEGRAM_ID` sahibi kullanici erisebilir.
- Grup ve yonlendirilmis mesajlar reddedilir.
- Dosya islemleri yalnizca `workspace/` icinde calisir.
- Path traversal `resolve()` + `is_relative_to(WORKSPACE)` ile engellenir.
- Yazma, ekleme ve silme sadece `.md`, `.txt`, `.json`, `.yaml`, `.yml`, `.csv` dosyalarinda calisir.
- Silme islemleri klasorleri ve gizli dosyalari kapsamaz.
- Onay bekleyen islemler TTL suresi dolunca otomatik iptal olur.
- Scope izolasyonu:
`YouTube` komutlari sadece `youtube/`, `notlar/`, `skills/youtube_icerik.md` alaninda.
`Arastirma` skill dosyasi `skills/arastirma.md` icinde tutulur; Gemini'ye otomatik workspace icerigi gonderilmez.
`Kod` komutlari sadece `projeler/`, `skills/kod_yardimcisi.md` alaninda.
- Gemini arastirmasi sadece belirli komutlarda calisir ve workspace dosyalarini otomatik gondermez.
- `.env` Git ve Docker build baglamindan dislanir.

## Kurulum

```bash
cd /Users/thecoremethodhowto/Desktop/CORE_AGENT
cp .env.example .env
chmod 600 .env
```

`.env` ornegi:

```env
TELEGRAM_BOT_TOKEN=BotFather_tokeniniz
MY_TELEGRAM_ID=Telegram_kullanici_id
WORKSPACE_DIR=/app/workspace
OLLAMA_HOST=http://host.docker.internal:11434
VASI_NOTES_FILE=notlar/NOTES.md
VASI_CHANNEL_STYLE_FILE=skills/youtube_icerik.md
VASI_CODE_STYLE_FILE=skills/kod_yardimcisi.md
VASI_MODEL_GATEKEEPER=qwen3:30b
VASI_MODEL_STRATEJI=qwen3:30b
VASI_MODEL_TEKNIK=qwen3:30b
VASI_MODEL_KOD=qwen3-coder:30b
VASI_MODEL_GORSEL=qwen3:30b
GEMINI_API_KEY=Gemini_API_keyiniz
GEMINI_MODEL=gemini-2.5-flash
PENDING_ACTION_TTL_SECONDS=600
GEMINI_DAILY_LIMIT_REQUESTS=60
# WEB_RADAR_ALLOWLIST=github.com,openai.com,ai.google.dev
```

Baslatma:

```bash
docker compose up -d --build
docker compose logs -f vasi-core
```

## Telegram Komutlari

```text
/start
/yardim
/liste
/oku notlar/NOTES.md
/yaz notlar/test.md | Yeni icerik
/ekle notlar/NOTES.md | Bugunku notum
/sil notlar/test.md
/fikir konu
/ara konu
/ara_not konu
/ara_ozet konu
/ara_senaryo konu
/tarzim Kanal dili...
/senaryo video konusu
/kod teknik soru
/kod_patch degisiklik istegi
/guvenlik
/rapor konu
```

## Test

Container ici testler:

```bash
docker compose run --rm vasi-core pytest
```

## Test Checklist (Video Icin)

1. `/start` ile komut menusu geliyor mu?
2. `/guvenlik` ile deterministik rapor donuyor mu?
3. `/ekle notlar/NOTES.md | ttl test` ac, TTL suresi gecince onayla.
4. `/ara_ozet <konu>` kaynakli kisa arastirma uretiyor mu?
5. `/ara_senaryo <konu>` onayli senaryo dosyasi olusturuyor mu?
6. `/kod_patch <istek>` dosya yazmadan patch taslagi uretiyor mu?

## 3 Komutluk Demo (Durdur / Kaldir / Tekrar Kur)

```bash
docker compose stop
docker compose down --rmi local --volumes --remove-orphans
docker compose up -d --build
```

Not: `down --volumes` compose volume verilerini de siler.

## Proje Yapisi

```text
.
├── vasi.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── pytest.ini
├── tests/
│   ├── conftest.py
│   └── test_security_core.py
└── workspace/
    ├── youtube/
    │   ├── fikirler/
    │   ├── senaryolar/
    │   └── arastirma/
    ├── projeler/
    │   └── oyunlar/
    ├── notlar/
    │   └── NOTES.md
    └── skills/
        ├── arastirma.md
        ├── youtube_icerik.md
        └── kod_yardimcisi.md
```
