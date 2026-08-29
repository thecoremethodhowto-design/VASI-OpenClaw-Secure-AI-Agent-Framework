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

Bu prensip, sekiz tehdit sınıfının analizinden çıkan sekiz somut ilkeye
dayanır:

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

Her ilkenin koddaki tam karşılığı, ilgili testleri ve bilinen eksikleri
için: **[THREAT-MAPPING.md](THREAT-MAPPING.md)**

---

## Doğrulama

Güvenlik kontrolleri otomatik testlerle doğrulanır:

```bash
docker compose run --rm vasi-core python -m pytest
```

Sistemin kendi güvenlik durumunu raporlaması için Telegram üzerinden:

```
/guvenlik
```

Bu rapor model tarafından üretilmez; mevcut kod sabitlerinden ve
yapılandırma değerlerinden okunur.

---

## Bilinen Eksikler

Şeffaflık adına, bilinen boşluklar açıkça listelenir:

- `audit_event()` fonksiyonunun doğrudan birim testi yoktur
- Kırmızı takım (red team) değerlendirmesi yapılmamıştır; testler
  kontrollerin yazıldığı gibi çalıştığını doğrular, kararlı bir
  saldırgana karşı yeterli olduğunu değil
- Log rotasyonu uygulanmamıştır

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
  (bkz. THREAT-MAPPING.md → Kontrol 6)