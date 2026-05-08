VASI OpenClaw Secure AI Agent Framework
VASI, Telegram uzerinden kontrol edilen, yerel Ollama modelleriyle calisan ve guvenlik sinirlari onceden tanimlanmis kisisel bir AI ajan iskeletidir. Fikir yakalama, not tutma, YouTube senaryosu uretme, kod yardimi ve istege bagli Gemini + Google Search destekli internet arastirmasi icin tasarlanmistir.

Not: Bu repo resmi OpenClaw paketini kullanmaz. OpenClaw tarzinda; tool whitelist, workspace sandbox, onayli dosya islemleri ve guvenlik raporu mantigiyla kurulmus bagimsiz bir VASI ajan mimarisidir.

Ozellikler
Telegram bot arayuzu
Yerel Ollama model baglantisi
Workspace icinde dosya okuma, yazma, ekleme ve silme
Yazma/silme icin Telegram onay butonu
Tarih-saat damgali not ekleme
YouTube kanal tarzi kaydetme
Baslik, aciklama, kapak fikri ve senaryo uretme
Proje dosyalarini dikkate alan kod yardimi
Deterministik /guvenlik raporu
Gemini API ile kaynakli internet arastirmasi
Docker hardening: read-only filesystem, tmpfs, no-new-privileges, cap_drop
Guvenlik Modeli
VASI'nin temel guvenlik prensibi: model onerir, kritik islemler kullanici onayi olmadan yapilmaz.

Sadece .env icindeki MY_TELEGRAM_ID sahibi kullanici erisebilir.
Grup ve yonlendirilmis mesajlar reddedilir.
Dosya islemleri yalnizca workspace/ icinde calisir.
Path traversal resolve() + is_relative_to(WORKSPACE) ile engellenir.
Yazma, ekleme ve silme sadece .md, .txt, .json, .yaml, .yml, .csv dosyalarinda calisir.
Silme islemleri klasorleri ve gizli dosyalari kapsamaz.
Model sadece izinli araclari kullanabilir.
Gemini arastirmasi sadece /ara ve /ara_not komutlariyla calisir; workspace dosyalari Gemini'ye otomatik gonderilmez.
.env Git ve Docker build baglamindan dislanir.
Kurulum
Repoyu klonlayin veya klasore girin:
cd /Users/thecoremethodhowto/Desktop/CORE_AGENT
.env dosyasini olusturun:
cp .env.example .env
chmod 600 .env
.env icindeki degerleri doldurun:
TELEGRAM_BOT_TOKEN=BotFather_tokeniniz
MY_TELEGRAM_ID=Telegram_kullanici_id
WORKSPACE_DIR=/app/workspace
OLLAMA_HOST=http://host.docker.internal:11434
VASI_MODEL_GATEKEEPER=qwen3:30b
VASI_MODEL_STRATEJI=qwen3:30b
VASI_MODEL_TEKNIK=qwen3:30b
VASI_MODEL_KOD=qwen3-coder:30b
VASI_MODEL_GORSEL=qwen3:30b
GEMINI_API_KEY=Gemini_API_keyiniz
GEMINI_MODEL=gemini-2.5-flash
Gemini zorunlu degildir. GEMINI_API_KEY bos kalirsa /ara ve /ara_not hata mesaji verir, diger ozellikler calismaya devam eder.

Ollama modellerini hazirlayin:
ollama pull qwen3:30b
ollama pull qwen3-coder:30b
Docker ile baslatin:
docker compose up -d --build
Loglari izleyin:
docker compose logs -f vasi-core
Telegram Komutlari
/start
/yardim
/liste
/oku NOTES.md
/ekle NOTES.md | Bugunku fikrim...
/yaz dosya.md | Yeni icerik
/sil dosya.md
/fikir Telegram uzerinden fikir yakalama sistemi
/ara Gemini API ile guncel AI agent trendleri
/ara_not Gemini API ile guncel AI agent trendleri
/tarzim Kanalimin dili stratejik, sade ve uygulamali...
/senaryo Yerel AI ajani nasil kurulur?
/kod Bu projede siradaki teknik iyilestirme ne olmali?
/guvenlik
/rapor konu basligi
Gemini Arastirmasi
Gemini entegrasyonu Google GenAI SDK ile calisir. Google'in resmi dokumantasyonunda onerilen google-genai kutuphanesi kullanilir ve API key GEMINI_API_KEY ortam degiskeninden okunur.

Kaynakli arastirma icin Gemini Grounding with Google Search kullanilir. Bu ozellik modeli guncel web icerigiyle temellendirir ve kaynak metadata'si dondurebilir.

Guvenlik sinirlari:

Gemini sadece acik /ara ve /ara_not komutlarinda kullanilir.
Workspace dosyalari Gemini'ye otomatik gonderilmez.
/ara_not sonucu dogrudan yazmaz; once Telegram onayi ister.
Gemini icin ayrica rate limit vardir.
API key loglanmaz ve repo disinda tutulur.
Resmi dokumanlar:

Gemini API libraries
Gemini API keys
Grounding with Google Search
Proje Yapisi
.
├── vasi.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── .gitignore
├── .dockerignore
└── workspace/
    ├── NOTES.md
    └── channel_style.md
Gelistirme Notlari
Bu proje kisisel kullanim ve deneysel ajan mimarisi icin hazirlanmistir. Uretim ortaminda kullanmadan once otomatik testler, log rotasyonu, onay sure asimi ve daha ayrintili audit kayitlari eklenmelidir.
