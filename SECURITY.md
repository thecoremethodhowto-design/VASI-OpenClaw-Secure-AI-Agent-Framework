# Güvenlik Politikası

## Güvenlik Açığı Bildirimi

Bu projede bir güvenlik açığı keşfederseniz, lütfen **herkese açık bir
issue açmayın.**

Bunun yerine doğrudan iletişime geçin:

- **E-posta:** the.core.method.how.to@gmail.com

Bildiriminizde şunları paylaşmanız değerlendirmeyi hızlandırır:

- Açığın kısa açıklaması
- Yeniden üretme adımları
- Olası etki değerlendirmeniz
- Varsa önerdiğiniz düzeltme

Sorumlu açıklama ilkesine uygun olarak, açığı kamuya duyurmadan önce
inceleyip düzeltmek için makul bir süre tanımanızı rica ederiz.

---

## Kapsam ve Tehdit Modeli

VASİ, **tek operatörlü kişisel bir sistemdir.** Güvenlik kontrolleri bu
varsayıma göre tasarlanmıştır.

**Kapsam içinde:**
- Yetkisiz erişim (kimlik doğrulama atlatma)
- Dosya sistemi sınırlarının aşılması (path traversal)
- Model üzerinden yetkisiz araç çalıştırma
- Sunucu taraflı istek sahteciliği (SSRF)
- Dolaylı talimat enjeksiyonu (prompt injection)
- Bağımlılık / tedarik zinciri bütünlüğü
- Hassas verinin dış servislere sızması
- Model yönlendirme: hangi verinin hangi sağlayıcıya gittiği
- Hafıza bütünlüğü: bir hatıranın kaynağı ve prompta girip girmediği
- Dolaylı enjeksiyon: indekslenmiş bir belgedeki gizli talimatın etkisi
- Denetim izinin bütünlüğü: bir kaydın değiştirilmesi, silinmesi ya da
  izin eski bir hâline döndürülmesi

**Kapsam dışında:**
- Çok kullanıcılı erişim kontrolü
- İçeriden tehdit (insider threat) senaryoları
- Operatörün kendi hesabının ele geçirilmesi
- Kullanılan üçüncü parti servislerin (Telegram, Ollama, Gemini) kendi
  güvenliği

---

## Tasarım İlkeleri

VASİ'nin temel prensibi: **model önerir, kritik işlemler kullanıcı onayı
olmadan yapılmaz.**

Bu prensip, tehdit sınıflarının analizinden çıkan on üç somut ilkeye
dayanır. İlk sekizi video serisindeki sekiz tehdit sınıfından gelir;
kalanlar sistem büyüdükçe eklendi:

1. **Onay kapısı** — Kalıcı etkisi olan hiçbir işlem, açık ve süreli bir
   insan onayı olmadan çalışmaz.
2. **İzolasyon** — Her bileşen kendi izole alanında, en az yetkiyle
   çalışır.
3. **İzin listesi** — Ne yapılabileceği önceden listelenir; yasaklar
   değil, izinliler sayılır.
4. **Küçük yüzey** — Erişilebilir alan mümkün olan en küçüktür; geri
   dönüşü olmayan işlemler ayrıca sınırlıdır.
5. **Doğrulanmış temas ve iz** — Dışarıyla her temas doğrulanır, her
   eylem kayıt bırakır.
6. **Parmak izi** — Bağımlılıklar isimle değil, kriptografik özetle
   sabitlenir.
7. **Çok katmanlı kimlik** — Kimlik tek katmanla doğrulanmaz; "kim"
   kadar "nereden" ve "ne zaman" da sorulur.
8. **Varsayılan hayır** — Emin olunmayan durumda cevap "hayır"dır.
9. **Görünür yönlendirme** — Bir modele veri gönderilirken, o verinin
   makineden çıkıp çıkmadığı koddan anlaşılabilir olmalıdır.
10. **Kaynak etiketi koddan gelir** — Bir hatıranın nereden geldiğini
    kod belirler, model değil. Hafızaya yazma, dosya yazma kadar ciddi
    bir işlemdir ve aynı onay mekanizmasından geçer.
11. **Yeteneği yasaklamak yerine hiç yazmamak** — Güvenilmeyen içeriğin
    modele ulaştığı yerlerde (RAG), araç çağrısı "yasak" değildir;
    çalıştıracak kod yolu yoktur. Bir kısıtlamayı unutmak mümkündür,
    var olmayan bir kod yolunu çağırmak değildir.
12. **Sistem kendini denetler** — Kod, politika ve yapılandırmanın hâlâ
    birbiriyle uyumlu olduğu çalışırken doğrulanır. Deterministik ve
    kritik bir bulgu ilgili yeteneği kapatır; sezgisel bir bulgu
    yalnızca raporlar. Kapatmanın geçersiz kılma yolu vardır, çünkü
    geçersiz kılınamayan bir kontrol tamamen sökülür — ama o geçersiz
    kılma onaylıdır, izlidir ve **sürelidir**.
13. **Kanıtın ikinci tanığı** — Bir kanıtın tek tanığı olmaz. Denetim izi
    zincirlenir ve ayrı bir tanıkta da tutulur; bir bulgu silinmez,
    onaylanır. Hiçbir şeye bakmamış bir doğrulayıcı "tamam" demez,
    "bilmiyorum" der.

Her ilkenin koddaki tam karşılığı, ilgili testleri ve bilinen eksikleri
için: **[THREAT-MAPPING.md](THREAT-MAPPING.md)**

---

## Doğrulama

Güvenlik kontrolleri otomatik testlerle doğrulanır:

```bash
./test.sh
```

Testlerin kendisi de sınanır: `./kanit.sh` denetim izinin korumalarını
kodun bir kopyasında tek tek bozar ve onu bekleyen testin kırmızıya
döndüğünü doğrular. Depoya ve çalışan bota dokunmaz.

Sistemin kendi güvenlik durumunu raporlaması için Telegram üzerinden:

```
/guvenlik
```

Bu rapor model tarafından üretilmez; mevcut kod sabitlerinden ve
yapılandırma değerlerinden okunur.

Kod ile politikanın hâlâ uyumlu olduğunu çalışırken sınamak için:

```
/denetle
```

On bir kontrol çalışır. Deterministik ve kritik bir bulgu ilgili yeteneği
kapatır — `/saglik` raporunda hangi yeteneğin kapalı olduğu görünür.
Denetim başlangıçta da çalışır, ama taban çizgisi yalnızca `/denetle`
ile ilerler: bir insan raporu görmeden yeni hâl "normal" sayılmaz.

On birinci kontrol denetim izinin kendisine bakar: iz kalıcı mı, zincir
sağlam mı, iki tanık uyuşuyor mu? Kırık bir iz kritik bir bulgudur ama
**hiçbir yeteneği kapatmaz**: botu durdurmak, kanıtın yazıcısını da
susturur. Raporlanır.

Denetim izini veritabanındaki kopyasıyla halka halka karşılaştırmak
için:

```
/iz_dogrula
```

Sistemden bağımsız doğrulama için (konteyner gerekmez; doğrulayıcı
hiçbir yerel modülü import etmez):

```bash
python3 audit_chain.py denetim/denetim.log
```

---

## Bilinen Eksikler

Şeffaflık adına, bilinen boşluklar açıkça listelenir:

- Kapsamlı bir kırmızı takım (red team) değerlendirmesi yapılmamıştır.
  Denetim izi beş kez, işi görmemiş bağımsız bir yapay zekâ incelemesinden
  geçti ve her seferinde açık bulundu; bu, bir sızma testinin yerini
  tutmaz. Testler kontrollerin yazıldığı gibi çalıştığını doğrular,
  kararlı bir saldırgana karşı yeterli olduğunu değil
- Denetim izinin iki tanığı da aynı makinededir. Bot tanığı silemez
  (ayrı, yalnızca ekleme yetkili hesap); ama makineye ve veritabanının
  süper kullanıcısına erişen biri yakalanmaz: dosyayı ve tanığı birlikte
  yeniden yazabilir, birlikte eski bir hâline döndürebilir ya da ikisine
  birden sahte bir onay ekleyebilir. Ekim 2026'dan beri zincirin ucu
  saatte bir ve her onayda makine dışına çapalanır (RFC 3161 zaman
  damgası, `capa.py`): çapalanmış halkaların yeniden yazılması ve
  zincirin sonunun kesilmesi yakalanır. Son çapadan sonra yazılan
  halkalar korunmaz (pencere: en çok bir saat)
- Makinedeki çapa makbuzları silinebilir; sahtesi üretilemez ama "hiç
  yoktu" denebilir. Buna karşı duran, her makbuzun Telegram'dan sahibine
  giden kopyasıdır: kopyalar `capa.py`'ye verilince silinen çapa yeniden
  ortaya çıkar. Bot anahtarını ele geçiren biri botun gönderdiği mesajları
  48 saat içinde silebilir (Telegram kuralı) ve kendi mesajını
  düzenleyebilir ("düzenlendi" etiketi görünür); dosyayı telefona indirmek
  ya da Kayıtlı Mesajlar'a iletmek bunu kapatır. Doğrularken TSA
  sertifikasını makinedeki kopyadan değil GitHub'daki depodan ver
- Çapanın güveni tek bir dış kuruma (varsayılan freeTSA) dayanır.
  İmza, depodaki TSA sertifikasıyla doğrulanır; sertifika depoda yoksa
  makbuz saklanır ama imzası "doğrulanmadı" olarak raporlanır
- Tanık kapalıyken bot da durdurulursa, aradaki satırları tanık hiç
  görmemiş olur; tanık ancak gördüğüne tanıklık eder
- Zincir, bir satırın yazıldıktan sonra değiştirilmediğini gösterir;
  doğru yazıldığını değil. Ele geçirilmiş bir bot, mühürlü zincire yanlış
  bir satır da yazabilir
- Zincirden ve tanıktan önce yazılan satırları doğrulayan yoktur; sistem
  bunu her doğrulamada söyler
- Yetkisiz erişim denemeleri mühürlü ize değil, botun genel kaydına
  yazılır
- Tanık tablosunun sahibi giriş yapamayan ayrı bir hesap, botun yetkisi
  yalnızca ekleme ve okuma (Ekim 2026). Süper kullanıcı için güncelleme,
  silme ve boşaltma yasağı yine yalnızca kazalara karşıdır: süper kullanıcı
  kuralı kapatabilir, tabloyu silebilir. Silinmesi algılanır (dosyadaki
  doğum kaydı), önlenmez. Zincirin ucu artık makinenin dışına
  çapalanıyor (yukarıda)
- Hafıza türleri ayrıştırılmıyor; tüm kayıtlar `preference` olarak saklanıyor
- RAG çerçevelemesi modelin davranışını etkiler ama garanti etmez;
  asıl koruma `/sor` kod yolunda araç yürütme bulunmamasıdır
- Benzerlik eşiği (`RAG_MIN_SCORE`) tek bir veri kümesinde gözlemlenen
  skorlara göre seçildi; farklı içerikte ayarlanması gerekebilir
- `/unut` bir hatırayı pasifleştirir, ancak o hatıra son turlarda
  konuşulduysa model onu hâlâ konuşma geçmişinde görebilir
- LiteLLM proxy'si ayrı bir bağımlılıktır; Mart 2026'da tedarik zinciri
  saldırısına uğradığı için sürüm sabitlenmiş ve güncellemeler elle
  gözden geçirilerek yapılmaktadır
- Sapma denetçisi **çalışan sistemi** denetler, diskteki dosyayı değil.
  Politika konteyner imajına gömülü olduğu için normalde ikisi aynıdır;
  `policies/` dışarıdan bağlanırsa ayrışabilirler ve denetçi bunu
  içeriden göremez — karşılaştıracağı ikinci bir kopya yoktur
- Sapma denetçisinin sezgisel kontrolü (hata oranı) asla durdurmaz;
  bedeli, gerçek bir saldırı örüntüsünün yalnızca raporlanmasıdır
- Zaman içinde sapma tespiti kasıtlı değişiklik ile kötü niyetli
  değişikliği ayırt etmez; ayırt edenler kural tabanlı kontrollerdir
- Yetenek geçersiz kılma süresi dolunca yeniden kapanır, ancak operatör
  komutu tekrar çalıştırabilir; engellenmedi çünkü engellenseydi kodu
  değiştirmek tek yol kalırdı

Güncel liste için `/guvenlik` raporunun "Gerçekçi Sıradaki
İyileştirmeler" bölümüne bakınız.

---

## Operatör Sorumlulukları

Bu sistem, çalıştıran kişinin şu önlemleri almasını varsayar:

- `.env` dosyası `chmod 600` ile korunmalı ve asla versiyon kontrolüne
  eklenmemelidir
- `MY_TELEGRAM_ID` doğru ayarlanmalıdır; boş bırakılırsa yetkilendirme
  kontrolü etkisiz kalır
- Ollama sunucusu uzak bir hosttaysa API anahtarı ile korunmalıdır
- Bağımlılıklar güncellenirken hash'ler yeniden üretilmelidir
- `LITELLM_MASTER_KEY` rastgele üretilmelidir (`openssl rand -hex 32`)
- `POSTGRES_PASSWORD` rastgele üretilmelidir (`openssl rand -hex 24`);
  boş bırakılırsa kalıcı hafıza kapalı kalır. İki ayrı parola vardır:
  `.env`'deki botun hesabının, `postgres.env`'deki süper kullanıcınınki.
  Süper kullanıcı parolası `.env`'e yazılmamalıdır: `.env`'in tamamı botun
  ortamına girer
- `postgres.env` git'e ve imaja girmez; `commit_oncesi.sh` onu da tarar
- `/indeksle` çalıştırmadan önce `policies/data_classification.yaml`
  gözden geçirilmelidir; indekslenen her dosya `/bul` ile aranabilir olur
- LiteLLM ve PostgreSQL sürümleri yükseltilmeden önce güvenlik
  duyuruları kontrol edilmelidir; yeni yayınlanmış sürümler hemen
  alınmamalıdır
  (bkz. THREAT-MAPPING.md → Kontrol 6)
- `policies/data_classification.yaml` düzenlendikten sonra
  `/denetle` çalıştırılmalıdır. YAML'da girinti kayması sessiz bir
  hatadır: aynı sözlükte tekrar eden anahtar üstündekini uyarısız ezer
- `SOVEREIGN_OVERRIDE_TTL_SECONDS` uzun bir değere çekilmemelidir;
  süresiz geçersiz kılma, kontrolü silmekle aynı şeydir
- `/gecersiz_kil` sonrası asıl sapma düzeltilmelidir; geçersiz kılma
  sapmayı ortadan kaldırmaz, yalnızca geçici olarak yok sayar
- `denetim/` klasörü versiyon kontrolüne eklenmemeli ve paylaşılmadan
  önce gözden geçirilmelidir: bazı denetim satırları kullanıcı girdisinin
  ilk 120 karakterini taşır
- `/iz_onayla` bulguları silmez, "görüldü" yapar. Onaydan önce
  önizlemedeki her bulgu okunmalıdır; onay incelemenin yerine geçmez
- `docker compose down --volumes` ikinci tanığı (PostgreSQL verisini) da
  siler; bir sonraki açılışta sistem bunu alarm olarak ize yazar
- `VASI_TEST_PG` ayrı bir test veritabanını göstermelidir; adı `_test`
  ile bitmeyen bir veritabanında bu testler çalışmaz
- Depo herkese açıksa her push'tan önce `./commit_oncesi.sh`
  çalıştırılmalıdır: `.env`'deki gizli değerleri ve Telegram kimliğini
  depoya gidecek her dosyada, sahnelenmiş hâlleri dahil arar