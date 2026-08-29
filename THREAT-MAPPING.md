# Tehdit → Kontrol Eşleştirmesi

Bu depodaki her güvenlik kontrolü, belirli bir tehdit sınıfının
analizinden çıkan somut bir karara dayanır. Bu belge, sekiz tehdit
sınıfını sekiz mimari ilkeye ve o ilkelerin koddaki karşılığına
bağlar.

> Bu belge kod **kopyalamaz**, kodu **işaret eder**. Fonksiyon adları
> satır numaralarından daha kararlıdır; refactor sonrası bozulmaz.

---

## Özet Tablo

| # | Tehdit | İlke | Uygulama | Test |
|---|---|---|---|---|
| 1 | Virüsler | Kalıcı işlem onay istesin, onay süreli olsun | `set_pending()`, `is_pending_expired()` | ✅ |
| 2 | Solucanlar | Her bileşen izole, en az yetkiyle | Docker sertleştirme | ⚙️ |
| 3 | Truva Atları | İzinlileri say, yasakları değil | `ALLOWED_TOOL_NAMES` | ✅ |
| 4 | Fidye Yazılımları | Erişim yüzeyi en küçük olsun | `safe_path()`, uzantı sınırı | ✅ |
| 5 | Botnetler | Dış temas doğrulansın, iz bıraksın | `is_safe_url()`, `audit_event()` | ◐ |
| 6 | Tedarik Zinciri | İsimle değil, parmak iziyle sabitle | Digest pinning, hash locking | ⚙️ |
| 7 | Sosyal Mühendislik | Kimlik çok katmanlı doğrulansın | `is_authorized()` | ✅ |
| 8 | Zehirli Üçgen | Emin değilsen "hayır" | Veri sınıflandırma | ✅ |

**Test durumu:** ✅ birim testi var · ◐ kısmen · ⚙️ yapılandırma (birim
testi uygun değil) · ❌ test yok

---

## Mimari: DACE Katmanları

Kontroller dört katmana ayrılmıştır. İzin verilen bağımlılık yönü tek
taraflıdır; `tests/test_architecture.py` bunu doğrular.

```
decision.py    Ne yapılmalı?          (bağımsız)
access.py      İzin var mı?           (bağımsız)
context.py     Model neyi bilmeli?    (bağımsız)
execution.py   Şimdi yap              (yalnızca access'e bağımlı)
vasi.py        Telegram + orkestrasyon
```

Hiçbir katman `vasi.py`'yi import etmez. Her dosya işlemi Access
katmanından geçer — bu da bir iddia değil, test edilen bir garantidir.

---

## 1. Virüsler → Onay Kapısı

**İlke:** Kalıcı etkisi olan hiçbir işlem, açık insan onayı olmadan
çalışmamalı. Ve o onay penceresi süresiz açık kalmamalı.

**Neden:** Bir virüs, harekete geçmek için bir insanın "evet" demesine
ihtiyaç duyar. Onayı zorunlu ve süreli yapmak, o "evet"i bilinçli bir
karar hâline getirir.

**Uygulama**
- `vasi.py` → `set_pending()` — onay butonu ve zaman damgası oluşturur
- `vasi.py` → `is_pending_expired()` — TTL kontrolü
- `docker-compose.yml` → `PENDING_ACTION_TTL_SECONDS` (varsayılan 600 sn)

**Tasarım notu:** `is_pending_expired()` içinde üç ayrı yol da
*expired* döner — kayıt eksikse, zaman damgası yoksa, ya da
ayrıştırılamıyorsa. Şüpheli bir onay geçerli sayılmaz.

**Test**
- `tests/test_security_core.py` → `test_pending_expired_true`
- `tests/test_security_core.py` → `test_pending_expired_false`

---

## 2. Solucanlar → İzolasyon

**İlke:** Her bileşen kendi izole alanında, işini yapması için gereken
en az yetkiyle çalışmalı.

**Neden:** Solucanın tehlikesi bulaşmasında değil, yanındakine
sıçrayabilmesinde. Sıçrayacak yer bırakmamak, en etkili savunmadır.

**Uygulama**
- `docker-compose.yml` → `read_only: true` — salt okunur dosya sistemi
- `docker-compose.yml` → `cap_drop: ALL` — tüm Linux yetenekleri düşürülmüş
- `docker-compose.yml` → `no-new-privileges:true` — ayrıcalık yükseltme kapalı
- `docker-compose.yml` → `tmpfs: /tmp` — yazılabilir tek geçici alan
- `Dockerfile` → `useradd -m -u 1000 vasi` + `USER vasi` — root değil

**Test:** ⚙️ Bunlar çalışma zamanı yapılandırması; birim testi uygun
değil. Doğrulama:
```bash
docker compose config | grep -A2 "cap_drop\|read_only\|no-new-privileges"
docker compose exec vasi-core whoami   # → vasi
```

---

## 3. Truva Atları → İzin Listesi

**İlke:** Bir bileşenin ne yapabileceğini önceden listele. "Yasak
olanları engelle" değil — "izinli olanları say."

**Neden:** Yasakları listelerseniz, aklınıza gelmeyen her şey serbest
kalır. İzinlileri listelerseniz, aklınıza gelmeyen her şey kapalı kalır.

**Uygulama**
- `access.py` → `ALLOWED_TOOL_NAMES` — izinli araç kümesi (2 girdi)
- `vasi.py` → `run_model_with_tools()` içindeki whitelist kontrolü

**Tasarım notu:** Liste dışı bir çağrı reddedilir ama **sessizce
yutulmaz** — modele "yasak" cevabı döner ve olay loglanır. Böylece
"model hiç denemedi" ile "model denedi, engellendi" ayırt edilebilir.

**Test**
- `tests/test_degisiklikler.py` → `test_whitelist_disi_tool_reddediliyor`

---

## 4. Fidye Yazılımları → Küçük Yüzey

**İlke:** Erişilebilir alan mümkün olan en küçük olmalı. Geri dönüşü
olmayan işlemler ayrıca sınırlanmalı.

**Neden:** Fidye yazılımı erişebildiği her şeyi kilitler. Erişim
alanını küçültmek, hasarı küçültmektir.

**Uygulama — üç katman**
1. `access.py` → `safe_path()` — `resolve()` sonra `is_relative_to()`
   ile workspace dışına çıkış engeli
2. `access.py` → `ALLOWED_WRITE_EXTENSIONS` + `is_allowed_write_file()` —
   yazılabilir dosya türü sınırı
3. `execution.py` → `delete_file()` — klasör ve gizli dosya silme yasağı

**Tasarım notu:** Sıralama önemli. Doğrulamadan **önce** çözümleme
yapılır; tersi durumda sembolik bağlantılar ve göreli yollar kontrolü
atlatabilir.

**Test**
- `test_security_core.py` → `test_safe_path_allows_workspace_file`
- `test_security_core.py` → `test_safe_path_blocks_traversal`
- `test_degisiklikler.py` → `test_izinli_uzantilar_yazilabilir`
- `test_degisiklikler.py` → `test_tehlikeli_uzantilar_yazilamaz`
- `test_degisiklikler.py` → `test_uzantisiz_dosya_yazilamaz`
- `test_degisiklikler.py` → `test_uzanti_buyuk_harf_duyarsiz`

---

## 5. Botnetler → Doğrulanmış Temas ve İz

**İlke:** Dışarıyla her temas doğrulanmalı. Ve her eylem iz bırakmalı.

**Neden:** Botnetin gücü sessizce çalışabilmesinde. Kayıt tutan bir
sistem sessiz kalamaz.

**Uygulama**
- `access.py` → `is_public_hostname()` — SSRF koruması, iç ağ adresleri
  reddedilir
- `access.py` → `is_safe_url()` — protokol ve allowlist kontrolü
- `execution.py` → `skill_web_radar()` içinde `allow_redirects=False`
- `vasi.py` → `audit_event()` — güvenlik olayları kaydı
- `observability.py` → `mask_user_id()` — kayıtlarda kimlik maskeleme

**Tasarım notu:** `allow_redirects=False` kritik — izinli bir adres,
yönlendirme yoluyla izinsiz bir adrese götüremiyor. Ayrıca kayıtlarda
kullanıcı kimliği tam tutulmuyor (son üç hane); korelasyon için yeterli,
kaydın kendisini risk hâline getirecek kadar değil.

**Test:** ◐ Kısmi
- `test_security_core.py` → `test_is_safe_url_blocks_localhost` ✅
- `test_security_core.py` → `test_is_safe_url_blocks_non_http` ✅
- `test_security_core.py` → `test_web_allowlist_blocks_unknown_domain` ✅
- `test_observability.py` → `test_audit_summary_masks_user_and_lists_recent_events` ✅
- `audit_event()` fonksiyonunun **doğrudan testi yok** ⚠️

---

## 6. Tedarik Zinciri → Parmak İzi

**İlke:** Bağımlılıkları isimle değil, kriptografik parmak iziyle
sabitle.

**Neden:** Bir isim, bir etiket, bir sürüm numarası değiştirilebilir.
Bir özet değiştirilemez. XZ Utils'te sorun, dağıtılan paketin kaynak
kodla karşılaştırılmamasıydı.

**Uygulama**
- `Dockerfile` → `FROM python:3.11-slim@sha256:...` — digest ile sabitleme
- `docker-compose.yml` → `image: ollama/ollama:...@sha256:...`
- `Dockerfile` → `pip install --require-hashes -r requirements.txt`
- `requirements.txt` → her paket için SHA256 hash'leri
- `requirements.in` → düzenlenebilir kaynak liste

**Tasarım notu:** `--require-hashes` sadece mevcut paketleri doğrulamaz;
gelecekteki bir hatanın davranışını değiştirir. Hash'siz bir satır
eklenirse kurulum sessizce devam etmez, **durur**.

**Bağımlılık güncelleme akışı**
```bash
# requirements.in dosyasını düzenle, sonra:
docker run --rm -v "$(pwd)":/work -w /work python:3.11-slim \
  bash -c "pip install --quiet pip-tools && \
           pip-compile --generate-hashes --output-file=requirements.txt requirements.in"
```

**Test:** ⚙️ Derleme zamanı özelliği. Doğrulama: `docker compose build`
hash uyuşmazlığında başarısız olur.

---

## 7. Sosyal Mühendislik → Çok Katmanlı Kimlik

**İlke:** Kimlik doğrulaması tek katmanlı olmamalı. "Kim" kadar
"nereden" ve "ne zaman" da sorulmalı.

**Neden:** Tek bir sinyali taklit etmek kolaydır. Dördünü birden
taklit etmek çok daha zordur.

**Uygulama** — `access.py` → `is_authorized()`, dört kontrol:
1. **Kim** — `MY_TELEGRAM_ID` eşleşmesi
2. **Nereden** — sadece özel sohbet (`chat.type != "private"` reddedilir)
3. **Nasıl** — yönlendirilmiş mesaj reddedilir (`forward_origin`)
4. **Ne zaman** — 60 saniyeden eski mesaj reddedilir

**Tasarım notu:** Dördüncü kontrol tekrar saldırısına (replay attack)
karşıdır. Meşru, doğru imzalanmış bir komut yakalanıp sonradan tekrar
gönderilse bile çalışmaz.

**Test:** `tests/test_authorization.py` — 17 test

Dört kontrolün her biri için hem kabul hem ret senaryosu test edilir:
- Kimlik: `test_farkli_kullanici_reddedilir`
- Sohbet türü: `test_ozel_olmayan_sohbetler_reddedilir` (group/supergroup/channel)
- Yönlendirme: `test_yonlendirilmis_mesaj_reddedilir`
- Zaman: `test_sinir_altindaki_mesaj_kabul_edilir` (59 sn),
  `test_sinir_ustundeki_mesaj_reddedilir` (61 sn)

Ayrıca iki kenar durum: mesajsız güncellemeler (callback query) ve
boş `MY_TELEGRAM_ID` davranışı.

> Bu kontrol uzun süre test edilmemişti. DACE refactor'üne başlamadan
> önce testleri yazıldı — çünkü test edilmemiş bir kontrol bozuk
> değildir, **korumasızdır**: bir refactor davranışını sessizce
> değiştirebilir.

---

## 8. Zehirli Üçgen → Varsayılan Hayır

**İlke:** Özel veri, güvenilmeyen içerik ve dışarıyla iletişim —
bu üçünün kesiştiği noktada açık bir politika olmalı, ve varsayılanı
"hayır" olmalı.

**Neden:** Üçü aynı anda mevcut olduğunda, dolaylı bir talimat ajanı
özel veriyi dışarı sızdırmaya ikna edebilir. Bir kenarı koparmak,
üçgeni kırar.

**Uygulama**
- `policies/data_classification.yaml` — dört sınıf: PUBLIC, PRIVATE,
  PROJECT, SECRET
- `access.py` → `classify_file()` — desen tabanlı sınıflandırma
- `access.py` → `is_gemini_allowed()` — dış aktarım izni sorgusu
- `access.py` → `classification_report_line()` — okunabilir rapor satırı
- `vasi.py` → `cmd_siniflandir()` — `/siniflandir <dosya>` komutu

**Tasarım notu — dikkat:** `PUBLIC` sınıfında bile
`gemini_allowed: false`. Bu bir hata değil, bilinçli tercihtir. Dosyanın
hassas olup olmaması ayrı bir konudur; otomatik dış aktarım
kabiliyetinin kendisi, dolaylı bir talimatın ihtiyaç duyduğu şeydir.
Üçgenin üçüncü kenarı koşullu değil, koşulsuz kapatılmıştır.

`is_gemini_allowed()` fonksiyonunun varsayılan dönüş değeri `False` —
politika dosyası okunamazsa ya da sınıf tanımsızsa cevap "hayır" olur.

**Test**
- `test_security_core.py` → `test_classify_file_defaults_to_private`
- `test_security_core.py` → `test_classify_file_secret`
- `test_security_core.py` → `test_classify_file_private_notes`
- `test_security_core.py` → `test_classify_file_project`
- `test_security_core.py` → `test_classify_file_public_but_gemini_file_export_closed`
- `test_security_core.py` → `test_classify_absolute_workspace_file`
- `test_security_core.py` → `test_classification_report_line`
- `test_degisiklikler.py` → `test_kok_dizindeki_env_secret_olarak_siniflanir`

---

## Testleri Çalıştırma

```bash
docker compose run --rm vasi-core python -m pytest
```

Beklenen: 78 test geçer.

---

## Bilinen Eksikler

Bu belge, kontrollerin **iddia edildiği gibi çalıştığını** göstermeyi
amaçlar. Aşağıdakiler bilinen boşluklardır:

1. `audit_event()` — doğrudan birim testi yok (Kontrol 5)
2. `run_model_with_tools()` henüz `vasi.py`'de; Execution katmanına
   taşınması `OBSERVABILITY` singleton'ının yeniden konumlandırılmasını
   gerektiriyor
3. Kırmızı takım değerlendirmesi yapılmadı — testler kontrollerin
   yazıldığı gibi çalıştığını doğrular, kararlı bir saldırgana karşı
   yeterli olduğunu değil
4. Tehdit modeli tek operatörlü kişisel sistemdir; çok kullanıcılı
   senaryolar kapsam dışıdır

---

## İlgili Kaynaklar

Bu eşleştirmenin dayandığı tehdit analizleri:

- Video serisi: (https://www.youtube.com/playlist?list=PLBBE0OPKw-qys4AjXB-Wn-mEw4uxS-MzK) (SİBER GÜVENLİK LABORATUVARI)
  https://www.youtube.com/playlist?list=PLBBE0OPKw-qyTjMn4rRN0JEoeGcwf733j (DİJİTAL VASİ)
- Yazılı analiz: (https://www.thecoremethodhowto.com/ai-mastery-blog)

Referans çerçeveler:
- [MITRE ATT&CK](https://attack.mitre.org)
- [MITRE ATLAS](https://atlas.mitre.org)
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)