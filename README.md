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
- LiteLLM proxy uzerinden coklu saglayici (yerel Ollama, Gemini, Claude)
- Model gizlilik profili: `yerel-` / `dis-` takma adlari verinin nereye gittigini soyler
- Workspace icinde bolmeli sandbox (`youtube`, `projeler`, `notlar`, `skills`)
- Yazma/silme icin Telegram onay butonu + TTL
- Tarih-saat damgali not ekleme
- YouTube kanal tarzi kaydetme
- Baslik, aciklama, kapak fikri ve senaryo uretme
- Proje dosyalarini dikkate alan kod yardimi
- Veri siniflandirma politikasi (`PUBLIC`, `PRIVATE`, `PROJECT`, `SECRET`)
- Konusma gecmisi (son 10 tur) ve `/temizle`
- PostgreSQL kalici hafiza: `/hatirla`, `/hatirlananlar`, `/unut`
- Belge arama (RAG): `/indeksle`, `/bul`, `/sor` -- yerel embedding, aracsiz cevaplama
- Deterministik `/guvenlik` raporu
- Sapma denetcisi: `/denetle` -- kod, politika ve yapilandirma uyumu; sapma bulunca ilgili yetenegi kapatir
- Muhurlu denetim izi: her satir bir oncekinin ozetini tasir; ikinci tanik (PostgreSQL) silinen satirin ne oldugunu soyler -- `/iz_dogrula`, `/iz_onayla`
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
- Model gizlilik profili: takma adlar `yerel-` (veri cikmaz) veya `dis-` (veri saglayiciya gider) onekiyle ayrilir. Kurala uymayan bir ad **yerel sayilmaz**.
- Model politika kapisi: dis modele dosya gonderimi siniflandirmaya karsi denetlenir.
- Yonlendirme dogrulamasi: redirect'ler otomatik izlenmez; her adim yeniden dogrulanir (en fazla 3 adim).
- Arama motoru engeli: Google/Bing gibi sorgu sayfalari okunamaz.
- Zaman farkindaligi: sistem promptuna guncel tarih enjekte edilir.
- Hafiza butunlugu: model kendi basina hatirlayamaz; kayit icin acik komut ve onay gerekir. Kaynak etiketini KOD atar -- `remember()` imzasinda `source` parametresi yoktur.
- Hafiza filtresi: yalnizca `source='user'` kayitlari sistem promptuna girer.
- Silme yerine pasiflestirme: `/unut` kaydi silmez, `active=false` yapar; denetim izi korunur.
- RAG aracsiz calisir: `/sor` sirasinda model arac CAGIRAMAZ. Getirilen bir belgedeki gizli talimat cevabi etkileyebilir ama dis dunyaya ulasamaz.
- RAG yerel kalir: `/sor` yalnizca yerel modelle calisir; embedding yalnizca yerel host'ta yapilir.
- Siniflandirmada en kisitlayici sinif kazanir: `projeler/.env` PROJECT degil SECRET'tir, indekslenmez.
- Taninmayan komutlar modele dusmez; `/hatırla` gibi Turkce karakterli yazimlar yakalanir ve dogru komut onerilir.
- Sapma denetcisi: `/denetle` on bir kontrolu calistirir. Deterministik ve kritik bir bulgu ilgili yetenegi kapatir; sezgisel bir bulgu yalnizca raporlar.
- Yetenek kapatma dar kapsamlidir: sapma hangi yetenegi etkiliyorsa yalnizca o kapanir (`rag`, `hafiza_prompt`, `araclar`).
- Kapatma geri alinabilir ama SURELIDIR: `/gecersiz_kil` onay ister, denetim gunlugune yazilir ve varsayilan 30 dakika sonra kendiliginden kalkar.
- `sovereign.py` hicbir yerel modulu import etmez; denetledigi sabitler ona parametre olarak gider. Bozulan bir modul denetciyi susturamaz.
- Denetim izi kalicidir ve workspace disindadir (`./denetim`): ajanin dosya araclari oraya yazamaz. Kalicilik varsayilmaz, olculur; olculemezse `/saglik` uyarir.
- Denetim izi zincirlidir: her satir bir oncekinin SHA-256 ozetini tasir. Bot calisirken yapilan bir degisiklik, ozetler bastan hesaplansa bile yazicinin bir sonraki satirinda ele verilir; dosyanin yerine yenisinin konmasi da.
- Ikinci tanik: her halka PostgreSQL'de ayrica saklanir. Tablo guncellemeyi, silmeyi ve bosaltmayi tetikleyiciyle reddeder. Bot tanikta yalnizca ekleme yetkili; tablonun ve kuralin sahibi giris yapamayan ayri bir hesap. Dosyadan silinen bir satirin ne oldugunu ve ne zaman yazildigini tanik soyler; tanigin kendisi silinirse dosyadaki dogum kaydi bunu alarm olarak ize yazar.
- Bulgu silinmez, onaylanir: `/iz_onayla` once neyin onaylanacagini gosterir, bulgulari kimlikleriyle tek tek onaylar ve onayin kendisini de zincire yazar. Onaydan sonraki her mudahale, eski satirlara bile olsa, yeniden uyarir.
- Iz kirildiginda bot DURMAZ: bulgu kritiktir ama hicbir yetenegi kapatmaz. Botu durdurmak, kanitin yazicisini da susturur.
- Dogrulayici sisteme guvenmez: `audit_chain.py` hicbir yerel modulu import etmez ve konteyner olmadan calisir. Dogrulayacak halka bulamazsa "tamam" demez.
- Kimlik maskeleme: denetim izinde kullanicinin kimligi maskelenir. Yetkisiz bir erisim denemesinin kimligi ise botun genel kaydina acik yazilir; kim denedigi bilinsin diye.
- `.env` Git ve Docker build baglamindan dislanir.
- Denetim izi (`denetim/`) Git'e girmez: bazi satirlari kullanici girdisinin ilk 120 karakterini tasir.

VASI, DACE mimarisiyle dort katmana ayrilmistir: `decision.py` (ne
yapilmali), `access.py` (izin var mi), `context.py` (model neyi
bilmeli), `execution.py` (simdi yap). Katmanlar arasi bagimlilik yonu
tek taraflidir ve `tests/test_architecture.py` tarafindan dogrulanir —
hicbir katman `vasi.py`'yi import edemez, her dosya islemi Access
katmanindan gecer.

> Her kontrolun koddaki tam karsiligi, testleri ve **bilinen eksikleri** icin: [THREAT-MAPPING.md](THREAT-MAPPING.md)

## Model Yonlendirme

Hangi istegin hangi modele gittigini takma adlar belirler:

| Girdi | Model | Neden |
|---|---|---|
| Duz metin (sohbet) | `yerel-genel` | Ucretsiz, veri cikmiyor |
| `/kod`, `/kod_patch` | `yerel-kod` | Proje dosyalari makineden cikmamali |
| `/senaryo`, `/fikir`, `/rapor` | `yerel-genel` | Yerel yeterli |
| `/ara*` | `dis-arastirma` (Gemini) | Guncel web bilgisi gerekiyor |

## Hafiza

Iki ayri katman var ve karistirilmamalari onemli:

| | Ne | Nerede | Omru |
|---|---|---|---|
| **Konusma gecmisi** | Son 10 tur | Bellekte | Oturum boyunca |
| **Kalici hafiza** | Acikca kaydedilen bilgiler | PostgreSQL | Kalici |

Konusma gecmisine yalnizca kullanici mesaji ve modelin nihai cevabi
girer. **Arac sonuclari (web icerigi, dosya icerigi) GIRMEZ** -- bir web
sayfasindaki gizli talimat gecmise girerse, sonraki her turda modele
tekrar gonderilir; tek seferlik bir enjeksiyon kalici hale gelir.

Kalici hafizaya yazmak icin acik komut ve onay gerekir:

```text
/hatirla Bana Patron diye hitap et
/hatirlananlar
/unut 1
/temizle
```

`POSTGRES_PASSWORD` bos birakilirsa hafiza kapali kalir ve sistem
normal calismaya devam eder. Denetim izinin ikinci tanigi da olmaz:
iz yalnizca dosyaya yazilir ve `/saglik` bunu bilgi olarak gosterir.

**Dis modeller asla otomatik secilmez.** Yalnizca acik kullanici
komutuyla devreye girerler. Bu hem maliyeti hem veri cikisini kontrol
eder.

Yeni bir model eklerken `litellm/config.yaml` icinde onek kuralina
uyun; uymayan bir takma ad mimari testte yakalanir.

## Belge Arama (RAG)

Uc komut var ve ucu de acik kullanici eylemi gerektirir. Duz sohbette
otomatik arama YOKTUR.

```text
/indeksle          Politikanin izin verdigi belgeleri indeksler
/bul <sorgu>       Anlamsal arama -- MODEL KULLANMAZ
/sor <soru>        Belgelere dayali cevap -- YEREL model, ARACSIZ
```

Hangi dosyalarin indekslenecegini `policies/data_classification.yaml`
belirler. Su an `youtube/`, `arastirma/`, `projeler/` ve `README*`
indekslenir; `notlar/`, gizli dosyalar ve siniflandirilmamis her sey
disarida kalir.

**Neden `/sor` aracsiz calisir:** Getirilen belgeler guvenilmeyen icerik
tasiyabilir -- ornegin `/ara_senaryo` ile uretilmis bir dosya, web'den
derlenmis metin icerir. O metinde gizli bir talimat varsa cevabi
etkileyebilir. Ama `/sor`'un kod yolunda arac yurutme bulunmadigi icin
dis dunyaya ulasamaz.

Web kaynakli icerik dislanmaz, ETIKETLENIR: `/bul` ve `/sor`
sonuclarinda 🌐 isaretiyle gorunur.

Siniflandirma politikasi ile kod arasindaki uyum `/denetle` ile
sinanir. Politikada tanimli olup kodun oncelik listesinde bulunmayan
bir sinif, ya da daha kisitlayici bir sinifin daha fazla izne sahip
olmasi, RAG yetenegini kapatir.

**Embedding modeli:** `bge-m3` (yerel, Ollama uzerinden). Turkce erisim
karsilastirmalarinda en yuksek skoru veren cok dilli model. Kurulum:

```bash
ollama pull bge-m3
```

## Kurulum

```bash
cp .env.example .env
cp postgres.env.example postgres.env
chmod 600 .env postgres.env
```

Iki dosya, iki hesap. `.env` botun dosyasidir; orada botun KENDI
veritabani hesabi durur (`POSTGRES_USER=vasi_bot`). Veritabaninin super
kullanici parolasi yalnizca `postgres.env`'de durur ve bota hic
verilmez. Iki parolayi ayri uret (`openssl rand -hex 24`); ayni olurlarsa
kurulum durur: bot o parolayla super kullanici olarak da baglanabilirdi.

Bot, denetim izinin ikinci taniginda yalnizca satir ekleyip okuyabilir;
tabloyu silemez, kurali kapatamaz. Hesaplari ilk kurulumda veritabani
kendisi kurar (`scripts/postgres/kurulum.sh`). Bundan onceki bir surumden
geciyorsan (bot super kullanici olarak baglaniyorsa) bir kez elle:

```bash
docker compose exec postgres sh /docker-entrypoint-initdb.d/10-vasi-tanik.sh
```

`/saglik` botun yetkisini olcer: kurulum yapilmamissa Denetim izi satiri
"bot süper kullanıcı: tanığı silebilir" diye uyarir. Botun tablolari kendi
semasindadir (adi hesabin adi); `public`te nesne kuramaz.

### Makine disi capa

Iki tanik da ayni makinede. Zincirin ucu bu yuzden saatte bir (yeni halka
varsa), her `/iz_onayla`'da ve kapanista disaridaki bir zaman damgasi
otoritesine imzalatilir (RFC 3161, varsayilan [freeTSA](https://freetsa.org/);
ucretsiz, hesap gerekmez). Imzali makbuz `denetim/capa/` altinda durur ve bir
kopyasi Telegram'dan sana gelir: makine silinse bile kopya telefonunda kalir.

Makbuzlarin imzasini dogrulamak icin TSA sertifikasini bir kez depoya indir
(parmak izini freetsa.org'daki degerle karsilastirir) ve commit'le:

```bash
sh scripts/capa/sertifika_indir.sh
```

Indirmezsen capa yine atilir ama `/saglik` "imza dogrulanmadi" der.
Kapatmak icin `.env`'de `VASI_CAPA_TSA=` (bos). Bilgisayarinda, Telegram'dan
indirdigin kopyalarla birlikte dogrulamak icin (`pip install cryptography`):

```bash
python3 capa.py denetim/denetim.log --capa denetim/capa --capa ~/Downloads/capa-kopyalar
```

Cikis kodu: `0` capalar ve zincir tutuyor · `1` capalanmis bir halka yeniden
yazilmis ya da silinmis, zincirin sonu kesilmis, zincirin kendisi kirik ya da
makbuz gecersiz · `2` okunamadi · `3` bulgu yok ama uyari var (orn. capali bir
halka dosyalarda yok; rotasyon olabilir, kanitlanamaz).

`--sertifika` icin bu makinedeki degil, GitHub'daki depodan (ya da kendi
bilgisayarindaki kopyadan) sertifika klasorunu ver; ekrana yazilan parmak izini
freetsa.org'dakiyle karsilastir. Telegram'daki makbuzlari indir ya da Kayitli
Mesajlar'a ilet: bot kendi mesajini sonradan degistirebilir.

Ilk kurulumda betik basarisiz olursa (orn. iki parola ayni) veritabani
hesapsiz ayaga kalkar ve bot baglanamaz: hatayi duzeltip yukaridaki komutu
elle calistir. `.env`'de `POSTGRES_PASSWORD` bossa betik atlanir (hafiza
kapali).

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
SOVEREIGN_OVERRIDE_TTL_SECONDS=1800
USE_LITELLM=true
LITELLM_BASE_URL=http://litellm:4000
LITELLM_MASTER_KEY=openssl_rand_hex_32_ile_uretin
ANTHROPIC_API_KEY=
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
/denetle
/gecersiz_kil rag
/siniflandir notlar/NOTES.md
/saglik
/iz_dogrula
/iz_onayla
/istatistik
/audit_ozet
/rapor konu
```

## Test

Testleri dogru ortamda calistiran betik:

```bash
./test.sh                                # konteynerde; imaji once tazeler
./test.sh -q tests/test_audit_chain.py   # pytest'e dogrudan aktarilir
YEREL=1 ./test.sh                        # konteyner yerine yerel Python (3.10+)
```

Yesil sonuc test edilen imaj hakkindadir, Telegram'da konusan bot hakkinda
degil. `./test.sh` bu yuzden calisan bot eski imajla calisiyorsa uyarir.

Gercek veritabani isteyen testler `VASI_TEST_PG` verilmezse atlanir. Bu
degisken, adi `_test` ile biten AYRI bir veritabanini gostermelidir.

Denetim izinin testlerinin gercekten bir sey korudugunu sinamak icin:

```bash
./kanit.sh                 # denetim izinin korumalarini kodun bir KOPYASINDA tek tek bozar
./kanit.sh --sadece 7      # tek bir kanit
```

Her bozmada ilgili test kirmiziya donmeli. Depoya ve calisan bota dokunmaz.

Denetim izini konteyner olmadan, kendi bilgisayarinizda dogrulamak icin
(macOS'un sistem Python'i 3.9 yeter):

```bash
python3 audit_chain.py denetim/denetim.log
```

Cikis kodu: `0` zincir saglam · `1` kirik ya da dis mudahale · `2` dosya yok ·
`3` dogrulanacak halka yok (hicbir sey dogrulanmadi; "tamam" da denemez).

`commit_oncesi.sh`, commit oncesi depoya gidecek her dosyada (sahnelenmis
hallerinde de) `.env`'deki gizli degerleri ve Telegram kimligini arar;
degerleri ekrana yazmaz:

```bash
./commit_oncesi.sh
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

## Test Checklist 

1. `/start` ile komut menusu geliyor mu?
2. `/guvenlik` ile deterministik rapor donuyor mu?
3. `/siniflandir .env` ile `SECRET` siniflandirmasi donuyor mu?
4. `/ekle notlar/NOTES.md | ttl test` ac, TTL suresi gecince onayla.
5. `/ara_ozet <konu>` kaynakli kisa arastirma uretiyor mu?
6. `/ara_senaryo <konu>` onayli senaryo dosyasi olusturuyor mu?
7. `/kod_patch <istek>` dosya yazmadan patch taslagi uretiyor mu?
8. `/denetle` temiz rapor donuyor mu? (11 kontrol)
9. `policies/data_classification.yaml` dosyasina kodda tanimsiz bir sinif ekleyip
   yeniden kurun: `/denetle` sapmayi bulmali ve `/bul` reddetmeli. Sinifi silip
   tekrar `/denetle` calistirin -- yetenek kendiliginden acilmali.
10. `/saglik` raporundaki Denetim izi satiri `zincir saglam` ve (PostgreSQL aciksa) `tanik uyusuyor` diyor mu?
    Capa satiri (acilistan bir dakika sonra) `capali: sira ≤ N` ve `imza dogrulandi` diyor mu, makbuz Telegram'a geldi mi?
11. Bilgisayarda `python3 audit_chain.py denetim/denetim.log` cikis kodu `0` mi?

## 3 Komutluk Demo (Durdur / Kaldir / Tekrar Kur)

```bash
docker compose stop
docker compose down --rmi local --volumes --remove-orphans
docker compose up -d --build
```

Not: `down --volumes` compose volume verilerini de siler: PostgreSQL'deki
kalici hafizayi ve denetim izinin ikinci tanigini. Denetim izi dosyasi
`./denetim` klasorunde kalir; adlandirilmis birim degil klasor, bilerek:
iki tanik ayni komutla olmesin. Bir sonraki acilista sistem tanigin
sifirlandigini alarm olarak ize yazar; `/iz_onayla` ile onaylanir.

## Proje Yapisi

```text
.
├── vasi.py                  # Telegram + orkestrasyon
├── decision.py              # DACE: ne yapilmali?
├── memory.py                # kalici hafiza (PostgreSQL)
├── rag.py                   # belge arama (parcalama, embedding, arama)
├── sovereign.py             # sapma denetcisi (yerel import YOK)
├── sovereign_store.py       # sapma denetcisinin parmak izleri (PostgreSQL)
├── audit_chain.py           # denetim izi zinciri + bagimsiz dogrulayici (yerel import YOK)
├── audit_store.py           # denetim izinin ikinci tanigi (PostgreSQL, yalnizca ekleme)
├── capa.py                  # zincirin ucunu makine disina capalar (RFC 3161) + dogrulayici
├── kanit.py                 # korumalari bozup testlerin yakaladigini kanitlar
├── access.py                # DACE: izin var mi?
├── context.py               # DACE: model neyi bilmeli?
├── execution.py             # DACE: simdi yap
├── observability.py
├── test.sh                  # testleri dogru ortamda calistirir
├── kanit.sh                 # kanit.py'yi konteynerde calistirir
├── commit_oncesi.sh         # commit oncesi gizli deger taramasi
├── scripts/bes_kanit.sh    # Sovereign videosunun bes kaniti (yerini kanit.sh aldi)
├── Dockerfile
├── docker-compose.yml
├── requirements.in          # duzenlenebilir bagimlilik listesi
├── requirements.txt         # hash kilitli, uretilmis dosya
├── .env.example             # botun ortami (botun veritabani hesabi)
├── postgres.env.example     # veritabaninin super kullanicisi (bota verilmez)
├── scripts/postgres/        # ikinci tanigin hesap ve tablo kurulumu
├── scripts/capa/            # TSA sertifikalari ve indirme betigi
├── pytest.ini
├── THREAT-MAPPING.md        # tehdit → kontrol eslesmesi
├── SECURITY.md              # guvenlik politikasi
├── litellm/
│   └── config.yaml              # model takma adlari (yerel-/dis-)
├── policies/
│   └── data_classification.yaml
├── evaluation/
│   └── eval_runner.py
├── denetim/                 # denetim izi; calisirken olusur, Git'e girmez
├── tests/
│   ├── conftest.py
│   ├── test_architecture.py     # DACE katman sinirlari
│   ├── test_authorization.py    # is_authorized() dort katman
│   ├── test_litellm.py          # model yonlendirme + arac dongusu
│   ├── test_history.py          # konusma gecmisi
│   ├── test_memory.py           # kalici hafiza + kaynak etiketi
│   ├── test_unknown_command.py  # taninmayan komut yakalama
│   ├── test_rag.py              # indeksleme, arama, enjeksiyon korumasi
│   ├── test_sovereign.py        # sapma denetcisi, yetenek kapisi, parmak izi
│   ├── test_denetim_izi.py      # audit_event() gercekte ne yaziyor
│   ├── test_maskeleme_politikasi.py  # kimin kimligi maskelenir
│   ├── test_mesaj_akisi.py      # duz mesaj uctan uca
│   ├── test_audit_chain.py      # ozet zinciri ve dogrulayici
│   ├── test_ikinci_tanik.py     # zincirin veritabanindaki kopyasi
│   ├── test_iz_onayi.py         # onay, acilis kaydi, denetcinin izi denetlemesi
│   ├── test_inceleme_aciklari.py    # bagimsiz incelemenin buldugu dort acik
│   ├── test_inceleme_aciklari_2.py  # ikinci inceleme: duzeltmelerin aciklari
│   ├── test_audit_store_pg.py   # gercek PostgreSQL ile (VASI_TEST_PG)
│   ├── test_kanit.py            # kanitlayicinin kendi testleri
│   ├── test_teknik_borc.py      # log rotasyonu, audit ayrimi, tek onay mekanizmasi
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

- **Video serisi:** (https://www.youtube.com/playlist?list=PLBBE0OPKw-qys4AjXB-Wn-mEw4uxS-MzK) (SİBER GÜVENLİK LABORATUVARI)
https://www.youtube.com/playlist?list=PLBBE0OPKw-qyTjMn4rRN0JEoeGcwf733j (DİJİTAL VASİ)
- **Yazili analiz:** (https://www.thecoremethodhowto.com/ai-mastery-blog)

Referans cerceveler:
- [MITRE ATT&CK](https://attack.mitre.org)
- [MITRE ATLAS](https://atlas.mitre.org)
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)