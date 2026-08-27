# VASI OpenClaw Secure AI Agent Framework

VASI, Telegram uzerinden kontrol edilen, yerel Ollama modelleriyle calisan ve guvenlik sinirlari onceden tanimlanmis kisisel bir AI ajan iskeletidir. Fikir yakalama, not tutma, YouTube senaryosu uretme, kod yardimi ve istege bagli Gemini + Google Search destekli internet arastirmasi icin tasarlanmistir.

> Not: Bu repo resmi OpenClaw paketini kullanmaz. OpenClaw tarzinda; tool whitelist, workspace sandbox, onayli dosya islemleri ve guvenlik raporu mantigiyla kurulmus bagimsiz bir VASI ajan mimarisidir.

---

## Nereden Baslamali?

| Amaciniz | Baslangic noktasi |
|---|---|
| **Sistemi kurmak istiyorum** | [Kurulum](#kurulum) bolumu |
| **Guvenlik kontrollerini incelemek istiyorum** | [THREAT-MAPPING.md](THREAT-MAPPING.md) |
| **Bu neden boyle tasarlandi?** | [Video serisi](#ilgili-kaynaklar) / [Yazili analiz](#ilgili-kaynaklar) |
| **Bir guvenlik acigi buldum** | [SECURITY.md](SECURITY.md) |

Bu depodaki her guvenlik kontrolu, belirli bir tehdit sinifinin analizinden cikan somut bir karara dayanir. Sekiz tehdit sinifinin sekiz mimari ilkeye ve o ilkelerin koddaki karsiligina nasil baglandigini gormek icin **[THREAT-MAPPING.md](THREAT-MAPPING.md)** dosyasina bakin.

---

## Ozellikler

- Telegram bot arayuzu
- Yerel Ollama model baglantisi
- Workspace icinde bolmeli sandbox (`youtube`, `projeler`, `notlar`, `skills`)
- Yazma/silme icin Telegram onay butonu + TTL
- Tarih-saat damgali not ekleme
- YouTube kanal tarzi kaydetme
- Baslik, aciklama, kapak fikri ve senaryo uretme
- Proje dosyalarini dikkate alan kod yardimi
- Veri siniflandirma politikasi (`PUBLIC`, `PRIVATE`, `PROJECT`, `SECRET`)
- Deterministik `/guvenlik` raporu
- Gozlemlenebilirlik: `/saglik`, `/istatistik`, `/audit_ozet`
- Gemini API ile kaynakli internet arastirmasi
- Docker hardening: read-only filesystem, tmpfs, no-new-privileges, cap_drop
- Bagimlilik butunlugu: digest pinning + hash locking

## Guvenlik Modeli

VASI'nin temel guvenlik prensibi: model onerir, kritik islemler kullanici onayi olmadan yapilmaz.

- Sadece `.env` icindeki `MY_TELEGRAM_ID` sahibi kullanici erisebilir.
- Grup ve yonlendirilmis mesajlar reddedilir.
- 60 saniyeden eski mesajlar reddedilir (replay korumasi).
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
- Veri siniflandirmasi: dis aktarim tum siniflar icin varsayilan olarak kapalidir.
- `.env` Git ve Docker build baglamindan dislanir.

> Her kontrolun koddaki tam karsiligi, testleri ve **bilinen eksikleri** icin: [THREAT-MAPPING.md](THREAT-MAPPING.md)

## Kurulum

```bash
cp .env.example .env
chmod 600 .env
```

`.env` ornegi:

```env
TELEGRAM_BOT_TOKEN=BotFather_tokeniniz
MY_TELEGRAM_ID=Telegram_kullanici_id
WORKSPACE_DIR=/app/workspace
OLLAMA_HOST=http://host.docker.internal:11434
TZ=Europe/Istanbul
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

> Kod degistirdikten sonra `docker compose up -d --force-recreate --build` kullanin. Yalnizca `build` calistirmak, ayakta duran konteyneri eski imajda birakir.

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
/siniflandir notlar/NOTES.md
/saglik
/istatistik
/audit_ozet
/rapor konu
```

## Test

Container ici testler:

```bash
docker compose run --rm vasi-core python -m pytest
```

Evaluation seti:

```bash
docker compose run --rm vasi-core python evaluation/eval_runner.py
```

## Bagimlilik Guncelleme

Bagimliliklar hash ile kilitlidir. Yeni bir paket eklemek veya surum yukseltmek icin `requirements.in` dosyasini duzenleyin, sonra:

```bash
docker run --rm -v "$(pwd)":/work -w /work python:3.11-slim \
  bash -c "pip install --quiet pip-tools && \
           pip-compile --generate-hashes --output-file=requirements.txt requirements.in"
```

`requirements.txt` dosyasini elle duzenlemeyin; uretilmis bir kilit dosyasidir.

## Test Checklist (Video Icin)

1. `/start` ile komut menusu geliyor mu?
2. `/guvenlik` ile deterministik rapor donuyor mu?
3. `/siniflandir .env` ile `SECRET` siniflandirmasi donuyor mu?
4. `/ekle notlar/NOTES.md | ttl test` ac, TTL suresi gecince onayla.
5. `/ara_ozet <konu>` kaynakli kisa arastirma uretiyor mu?
6. `/ara_senaryo <konu>` onayli senaryo dosyasi olusturuyor mu?
7. `/kod_patch <istek>` dosya yazmadan patch taslagi uretiyor mu?

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
├── observability.py
├── Dockerfile
├── docker-compose.yml
├── requirements.in          # duzenlenebilir bagimlilik listesi
├── requirements.txt         # hash kilitli, uretilmis dosya
├── .env.example
├── pytest.ini
├── THREAT-MAPPING.md        # tehdit → kontrol eslesmesi
├── SECURITY.md              # guvenlik politikasi
├── policies/
│   └── data_classification.yaml
├── evaluation/
│   └── eval_runner.py
├── tests/
│   ├── conftest.py
│   ├── test_security_core.py
│   ├── test_observability.py
│   └── test_degisiklikler.py
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

## Ilgili Kaynaklar

Bu sistemin tasarim kararlarinin dayandigi tehdit analizleri:

- **Video serisi:** [link]
- **Yazili analiz:** [blog linki]

Referans cerceveler:
- [MITRE ATT&CK](https://attack.mitre.org)
- [MITRE ATLAS](https://atlas.mitre.org)
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
```
