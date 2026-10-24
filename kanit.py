"""Kanit: korumalari tek tek bozar; her seferinde ilgili test KIRMIZIYA donmeli.

Yesil bir test, bir sey kanitlamaz -- ta ki kod bozuldugunda kirmiziya
dondugu gorulene kadar. Bu betik her korumayi kaynak kodun bir KOPYASINDA
bozar, o korumayi bekleyen testi calistirir ve testin bozulmayi
yakaladigini gosterir. Depoya ve calisan bota dokunmaz.

    ./kanit.sh                       konteynerde (onerilen)
    python kanit.py --sadece 7       tek bir kanit

Desen listesi kodla birlikte yasar: bir desen artik kodda bulunmazsa
(kod degistiyse) betik bunu SOYLER; tests/test_kanit.py da ayni seyi her
test calistirmasinda kontrol eder. Kanit listesi sessizce eskiyemez.

Gercek veritabani isteyen kanitlar, VASI_TEST_PG verilmemisse atlanir ve
atlandiklari soylenir (bkz. tests/test_audit_store_pg.py).

Sonuc, pytest'in ekrana bastigi metinden degil, makine okunur raporundan
(JUnit XML) okunur. 4 Ekim: pytest.ini'deki `-q`, buradaki `-q` ile
birlesince (-qq) pytest "1 failed in 0.3s" satirini hic yazmadi; son
satira bakan eski surum, yakalanan 36 bozmanin hepsini "calismadi" saydi.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KOK = Path(__file__).resolve().parent
ZC = "tests/test_audit_chain.py::"
IT = "tests/test_ikinci_tanik.py::"
PG = "tests/test_audit_store_pg.py::"
ON = "tests/test_iz_onayi.py::"
IN = "tests/test_inceleme_aciklari.py::"
IN2 = "tests/test_inceleme_aciklari_2.py::"
TH = "tests/test_tanik_hesabi.py::"
CP = "tests/test_capa.py::"

# (faz, ne bozuluyor, dosya, aranan, yerine, [testler])
KANITLAR = [
    # ── Faz 3b: yazici ──────────────────────────────────────────────────────
    ("3b", "hayalet dosya: değişen dosya yeniden açılmıyor", "audit_chain.py",
     "        if disk_kimligi == (akis.st_dev, akis.st_ino):\n            return None",
     "        return None",
     [ZC + "test_dosya_calisirken_degistirilirse_iz_susmuyor"]),
    ("3b", "yeniden açınca zincirin ucu diskten okunuyor (aklama)", "audit_chain.py",
     "        self.stream = yeni\n        self._satir_sonu_garanti()\n        return sebep",
     "        self.stream = yeni\n        self.son_sira, self.son_ozet = son_halka(self.baseFilename)\n"
     "        self._satir_sonu_garanti()\n        return sebep",
     [ZC + "test_sondan_silmek_calisirken_ele_veriliyor[yerine_yenisi]"]),
    ("3b", "yazıcının uyarısı zincire düşüyor", "audit_chain.py",
     "        if self._uyari_veriliyor:\n            return\n", "",
     [ZC + "test_mudahale_genel_loga_uyari_olarak_dusuyor_zincire_degil"]),
    ("3b", "yeni dosyada satır sonu garantisi yok", "audit_chain.py",
     "        self.stream = yeni\n        self._satir_sonu_garanti()",
     "        self.stream = yeni",
     [ZC + "test_satir_sonu_olmadan_birakilan_dosyada_satirlar_karismiyor"]),
    ("3b", "önce kapatıp sonra açıyor (açılamazsa susar)", "audit_chain.py",
     "        yeni = self._open()\n        self.stream.close()\n        self.stream = yeni",
     "        self.stream.close()\n        self.stream = self._open()\n        yeni = self.stream",
     [ZC + "test_yeniden_acilamazsa_sonraki_yazimda_yine_deniyor"]),
    ("3b", "doğrulayıcı müdahale kaydını görmüyor", "audit_chain.py",
     "        m = _MUDAHALE.search(govde)", "        m = None",
     [ZC + "test_icerik_ayni_kalsa_da_dokunulmasi_kaydediliyor"]),
    ("3b", "sağlık 'temiz' yerine 'sağlam'a bakıyor", "vasi.py",
     "temiz = zincir is not None and zincir.temiz",
     "temiz = zincir is not None and zincir.saglam",
     [ZC + "test_saglik_dis_mudahaleyi_gizlemiyor"]),
    ("3b", "komut satırı müdahaleye rağmen 0 dönüyor", "audit_chain.py",
     "    if not r.temiz:\n        return 1", "    if not r.saglam:\n        return 1",
     [ZC + "test_icerik_ayni_kalsa_da_dokunulmasi_kaydediliyor"]),
    ("3b", "bildirim kendi saatini taşıyor", "audit_chain.py",
     "dururdu.\n        ek.created, ek.msecs = record.created, record.msecs\n", "dururdu.\n",
     [ZC + "test_mudahale_satiri_tetikleyen_yazimin_zamanini_tasiyor"]),
    ("3b", "silme, rotasyon gibi anlatılıyor", "audit_chain.py",
     "        if r.mudahaleler and r.mudahaleler[0].sira == b + 1:", "        if False:",
     [ZC + "test_dosya_calisirken_silinirse_yeni_dosya_olayla_basliyor"]),
    ("3b", "hiçbir şey doğrulamadan 0 dönüyor", "audit_chain.py",
     "    return 0 if r.halka else 3", "    return 0",
     [ZC + "test_hicbir_sey_dogrulamayan_dogrulayici_tamam_demiyor"]),

    # ── Faz 4: ikinci tanik ─────────────────────────────────────────────────
    ("4", "yazıcı tanığın ucundan sürdürmüyor", "audit_chain.py",
     "        self.son_sira, self.son_ozet = t_sira, t_ozet    # tanigin ucundan surdur\n", "",
     [IT + "test_3_ekim_bot_dururken_geri_konan_yedek_yakalaniyor"]),
    ("4", "aynı sıra, farklı özet görmezden geliniyor", "audit_chain.py",
     "        elif t_sira == self.son_sira and t_ozet != self.son_ozet:", "        elif False:",
     [IT + "test_bot_dururken_bastan_hesaplanan_zincir_yakalaniyor"]),
    ("4", "tanık bildirimi ize yazılmıyor", "audit_chain.py",
     "                self._bildirim_yaz(record, TANIK_OLAYI, sebep_t, sonra)",
     "                pass",
     [IT + "test_3_ekim_bot_dururken_geri_konan_yedek_yakalaniyor"]),
    ("4", "tanık hatası botu durduruyor", "audit_chain.py",
     "        except Exception as e:\n            self._tanik_erisilemedi(f\"tanığa yazılamadı (sıra {sira})\", e)",
     "        except ZeroDivisionError as e:\n            self._tanik_erisilemedi(f\"tanığa yazılamadı (sıra {sira})\", e)",
     [IT + "test_tanik_kapaliyken_iz_yazilmaya_devam_ediyor"]),
    ("4", "ilk yazımda yeniden hizalanmıyor", "audit_chain.py",
     "            if self.tanik is not None and not self._hizalandi:\n                self._tanikla_hizala()\n",
     "",
     [IT + "test_tanik_baslangicta_hazir_degilse_ilk_yazimda_hizalaniyor"]),
    ("4", "kesinti uyarısı her yazımda tekrarlanıyor", "audit_chain.py",
     "        if not self._tanik_kesik:\n            _log.warning(f\"⚠️ Denetim izi: {ne}",
     "        if True:\n            _log.warning(f\"⚠️ Denetim izi: {ne}",
     [IT + "test_tanik_kapaliyken_iz_yazilmaya_devam_ediyor"]),
    ("4", "karşılaştırma içeriğe bakmıyor", "audit_chain.py",
     "            if d[sira] == t[sira]:", "            if d[sira][0] == t[sira][0]:",
     [IT + "test_ozeti_ayni_icerigi_farkli_satir_da_yakalaniyor"]),
    ("4", "sağlık tanığa bakmıyor", "vasi.py",
     "\"ok\" if durum == \"kalici\" and temiz and tanik_tamam else \"warn\"",
     "\"ok\" if durum == \"kalici\" and temiz else \"warn\"",
     [IT + "test_saglik_dosya_tanigin_gerisindeyse_uyarir"]),
    ("4", "okunamayan tanık bilgi sayılıyor", "vasi.py",
     "\", False\n    if dosya_raporu is None:", "\", True\n    if dosya_raporu is None:",
     [IT + "test_saglik_okunamayan_tanigi_gizlemiyor"]),
    ("4", "/iz_dogrula önce kendini yazıyor", "vasi.py",
     "    metin, durum = iz_dogrulama_raporu()\n    for i in range(0, len(metin), 3900):\n"
     "        await update.message.reply_text(metin[i:i + 3900])\n"
     "    audit_event(\"iz_dogrulama\", str(update.effective_user.id), durum)",
     "    audit_event(\"iz_dogrulama\", str(update.effective_user.id), \"once\")\n"
     "    metin, durum = iz_dogrulama_raporu()\n    for i in range(0, len(metin), 3900):\n"
     "        await update.message.reply_text(metin[i:i + 3900])",
     [IT + "test_iz_dogrula_once_raporluyor_sonra_kendini_yaziyor"]),
    ("4", "rapor iddiası davranıştan gelmiyor", "vasi.py",
     "    if AUDIT_AYRI_DOSYADA and getattr(_audit_yazici, \"tanik\", None) is not None:",
     "    if True:",
     [IT + "test_guvenlik_raporu_tanik_iddiasi_davranistan_geliyor"]),
    ("4", "bot açılışta tanığın yetkisini ölçmüyor", "vasi.py",
     "                _y_durum, _y_aciklama = audit_store.yetki_durumu()\n",
     "                _y_durum, _y_aciklama = audit_store.YALNIZCA_EKLEME, \"\"\n",
     [IT + "test_bot_tanik_semasini_kurmuyor_yalnizca_yetkisini_olcuyor"]),
    ("4", "çatallanma 'yazıldı' sayılıyor", "audit_store.py",
     "        return \"ayni\" if mevcut and tuple(mevcut) == (ozet, govde) else \"catal\"",
     "        return \"yazildi\"",
     [PG + "test_kayit_durumlari"]),
    ("4", "tanık silmeyi reddetmiyor", "scripts/postgres/tanik.sql",
     "    BEFORE UPDATE OR DELETE ON public.denetim_zinciri", "    BEFORE UPDATE ON public.denetim_zinciri",
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor",
      PG + "test_kural_super_kullaniciya_da_satir_sildirmiyor"]),
    ("4", "çok satırlı hata sağlık satırını bölüyor", "audit_chain.py",
     "        metin = \" \".join(str(hata).split())[:160]", "        metin = str(hata)",
     [IT + "test_cok_satirli_veritabani_hatasi_saglik_satirini_bolmuyor"]),

    # ── Faz 5: onay ve acilis ───────────────────────────────────────────────
    ("5", "geçersiz bir halka da onay sayılıyor", "audit_chain.py",
     "        if o and gecerli and int(o.group(\"kapsam\")) < sira:",
     "        if o and int(o.group(\"kapsam\")) < sira:",
     [ON + "test_araya_sokulmus_sahte_onay_hicbir_seyi_onaylamiyor"]),
    ("5", "onay kendinden sonrasını kapsayabiliyor", "audit_chain.py",
     "        if o and gecerli and int(o.group(\"kapsam\")) < sira:",
     "        if o and gecerli:",
     [ON + "test_kendini_ya_da_gelecegi_kapsayan_onay_gecersiz"]),
    ("5", "onaydan sonra eklenmiş satır da onaylı", "audit_chain.py",
     "    return (x.sonra or 0) < kapsam", "    return (x.sonra or 0) <= kapsam",
     [ON + "test_sirasiz_bulgu_kapsamin_hemen_ardindaysa_onaylanmiyor"]),
    ("5", "karşılaştırma onayı tanımıyor", "audit_chain.py",
     "    if onaylar:\n        k.onay_kapsami = max(",
     "    if False:\n        k.onay_kapsami = max(",
     [ON + "test_karsilastirma_onaydaki_listeyi_gecmise_tasiyor"]),
    ("5", "onay isteği bekleyen bildirimi yazdırmıyor", "vasi.py",
     "    audit_event(\"iz_onay_istegi\", user_id, \"-\")\n", "",
     [ON + "test_onay_bekleyen_yazici_bildirimini_de_kapsiyor"]),
    ("5", "/iz_onayla onay kapısında değil", "vasi.py",
     "    \"iz_onayla\",\n})", "})",
     [ON + "test_iz_onayla_onay_kapisinda"]),
    ("5", "denetçi kırık iz yüzünden yetenek kapatıyor", "sovereign.py",
     "            \"iz_butunlugu\", DETERMINISTIK, KRITIK, YETENEK_YOK,",
     "            \"iz_butunlugu\", DETERMINISTIK, KRITIK, YETENEK_RAG,",
     [ON + "test_denetci_izi_denetliyor_ama_hicbir_seyi_kapatmiyor"]),
    ("5", "'sistem' kimlik gibi maskeleniyor", "observability.py",
     "    if metin == SISTEM_KIMLIGI:\n        return metin\n", "",
     [ON + "test_sistem_kimligi_maskelenmiyor"]),
    ("5", "açılış denetimi çalışmazsa ize yazılmıyor", "vasi.py",
     "            audit_event(\"baslangic_denetimi\", SISTEM_KIMLIGI, f\"calismadi: {e}\")\n", "",
     [ON + "test_her_acilis_ize_yaziliyor_tanik_baglandiktan_sonra"]),
    ("5", "rapor onay butonunu koşulsuz iddia ediyor", "vasi.py",
     "        if \"iz_onayla\" in ONAY_GEREKEN_KOMUTLAR and \"iz_onayla\" in _onay_isteyen_komutlar()",
     "        if True",
     [ON + "test_guvenlik_raporu_onay_iddiasi_davranistan_geliyor"]),
    ("5", "iki maske 'sistem'de ayrışıyor", "access.py",
     "    if metin == \"sistem\":           # observability.SISTEM_KIMLIGI -- bir kimlik degil\n"
     "        return metin\n", "",
     ["tests/test_maskeleme_politikasi.py::test_iki_maske_ayni_sonucu_veriyor"]),

    # ── Faz 6: bagimsiz incelemenin buldugu acikler ─────────────────────────
    ("6", "bot dururken silinen tanık 'ilk kurulum' sanılıyor", "audit_chain.py",
     "            if bas is not None:\n                # Dosya tanigin dogdugunu hatirliyor",
     "            if False:\n                # Dosya tanigin dogdugunu hatirliyor",
     [IN + "test_tanik_bot_dururken_silinirse_acilista_alarm"]),
    ("6", "bot çalışırken silinen tanık sessizce geçiyor", "audit_chain.py",
     "        if bas is not None and sira > bas and not self._sifirlama_bildirildi:",
     "        if False:",
     [IN + "test_tanik_bot_calisirken_silinirse_alarm"]),
    ("6", "ilk kurulumda tablonun henüz olmaması alarm sayılıyor", "audit_chain.py",
     "        if bas is not None and sira > bas and not self._sifirlama_bildirildi:",
     "        if not self._sifirlama_bildirildi:",
     [IN + "test_ilk_kurulumda_tablo_yoksa_da_alarm_yok"]),
    ("6", "tanığın başı silinse de sessiz", "audit_chain.py",
     "        elif ilk is not None and ilk > bas:", "        elif False:",
     [IN + "test_tanigin_basi_silinirse_alarm"]),
    ("6", "tanığın doğum kaydı yazılmıyor", "audit_chain.py",
     "                self._bilgi_bekleyen.append((TANIK_BASLANGICI, None))",
     "                pass",
     [IN + "test_ilk_kurulumda_tanigin_dogumu_yaziliyor_alarm_yok"]),
    ("6", "karşılaştırma tanığın doğumunu yok sayıyor", "audit_chain.py",
     "    sinir = tanik_baslangici if tanik_baslangici is not None else t_ilk",
     "    sinir = t_ilk",
     [IN + "test_tanik_bot_dururken_silinirse_acilista_alarm"]),
    ("6", "denetçi sıfırlanan tanığı kritik saymıyor", "vasi.py",
     "k.farkli or k.sifirlanmis\n", "k.farkli\n",
     [IN + "test_sifirlanan_tanik_saglikta_ve_denetcide_kirmizi"]),
    ("6", "onay listeyi değil aralığı onaylıyor", "audit_chain.py",
     "    return any(x.kimlik in kimlikler and _kapsamda(x, kapsam)",
     "    return any(_kapsamda(x, kapsam)",
     [IN + "test_onaydan_sonra_eski_satir_degisirse_yeniden_uyariyor"]),
    ("6", "tanık farkları aralıkla onaylanıyor", "audit_chain.py",
     "            return any(kimlik in liste and sira <= kapsam for",
     "            return any(sira <= kapsam for",
     [IN + "test_onaydan_sonra_eski_satir_silinirse_yeniden_uyariyor"]),
    ("6", "bot onayı kimlik listesi olmadan yazıyor", "vasi.py",
     "            ayrinti = audit_chain.onay_ayrintisi(kapsam, pending.get(\"kimlikler\", []))",
     "            ayrinti = f\"kapsam={kapsam} bulgu={pending['bulgu']}\"",
     [IN + "test_bot_onayi_kimlik_listesiyle_yaziyor"]),
    ("6", "baştan silme rotasyon sayılıyor", "audit_chain.py",
     "                if not bas_serbest and (not rotasyon_olabilir or r.zincir_oncesi\n"
     "                                        or not donme_kaydi):",
     "                if False:",
     [IN + "test_dosyanin_basi_silinirse_rotasyon_sayilmiyor"]),
    ("6", "dönmüş dosya sayısı baş eksikliğini aklıyor", "audit_chain.py",
     "                                        or not donme_kaydi):",
     "                                        or False):",
     [IN + "test_donmus_dosya_sayisi_bas_eksigini_rotasyon_yapmiyor",
      IN2 + "test_bos_sahte_donmus_dosyalar_bastan_silmeyi_aklamiyor"]),
    ("6", "bot yedek sayısını tanığa vermiyor", "vasi.py",
     "                                                     yedek_sayisi=LOG_BACKUP_COUNT)",
     "                                                     )",
     [IN2 + "test_bot_tanik_karsilastirmasinda_yedek_sayisini_kullaniyor"]),
    ("6", "tanıkta baştan silinenler rotasyon sayılıyor", "audit_chain.py",
     "        if not bas_rotasyon or d_ilk is None or sira >= d_ilk:",
     "        if d_ilk is None or sira >= d_ilk:",
     [IN + "test_tanikta_bastan_silinenler_dosyada_yok_sayiliyor"]),
    ("6", "kesintide yazılanlar bellekte tutulmuyor", "audit_chain.py",
     "            self._tanik_erisilemedi(f\"tanığa yazılamadı (sıra {sira})\", e)\n"
     "            self._kuyruga_ekle(sira, oz, govde)\n",
     "            self._tanik_erisilemedi(f\"tanığa yazılamadı (sıra {sira})\", e)\n",
     [IN + "test_kesintide_yazilanlar_tanik_donunce_ona_yaziliyor"]),
    ("6", "kapanırken bekleyenler tanığa yazılmıyor", "audit_chain.py",
     "                    self._kuyrugu_bosalt()\n                except Exception:",
     "                    pass\n                except Exception:",
     [IN + "test_kesintide_yazilanlar_bot_kapanirken_de_taniga_yaziliyor"]),

    # ── Faz 7: ikinci bagimsiz inceleme -- duzeltmelerin kendisi kirildi ──
    ("7", "rotasyon iz bırakmıyor (dönme kaydı yazılmıyor)", "audit_chain.py",
     "            self._halka_yaz(self._sistem_satiri(record, logging.INFO, ROTASYON_OLAYI, ayrinti))",
     "            pass",
     [IN2 + "test_gercek_rotasyon_her_yeni_dosyayi_donme_kaydiyla_baslatiyor"]),
    ("7", "dönme kaydının özeti doğrulanmıyor", "audit_chain.py",
     "                               and ozet(d.group(\"ozet\"), govde) == oz)",
     "                               )",
     [IN2 + "test_ilk_satiri_donme_kaydina_cevirmek_ise_yaramiyor"]),
    ("7", "tanık dönme kayıtlarını saymıyor", "audit_chain.py",
     "        return yedek_sayisi is None or (beklenen_ilk is not None and sira < beklenen_ilk)",
     "        return True",
     [IN2 + "test_rotasyondan_sonra_en_eski_dosyanin_icerigi_giderse_tanik_yakaliyor"]),
    ("7", "dönme kaydı tanığın doğumunu taşımıyor", "audit_chain.py",
     "                ayrinti += f\" tanik_ilk_sira={self._tanik_baslangici}\"",
     "                pass",
     [IN2 + "test_dogum_kaydi_rotasyonla_gitse_de_tanigin_silinmesi_yakalaniyor"]),
    ("7", "sıfırlanan tanık yeniden doğmuyor (her açılış alarm)", "audit_chain.py",
     "        self._bilgi_bekleyen.append((TANIK_BASLANGICI, f\"ilk_sira={yeni_ilk}\"))",
     "        pass",
     [IN2 + "test_tanik_sifirlaninca_yeniden_dogar_sonraki_acilislar_sessiz"]),
    ("7", "hizalama tanığın en eski doğumuna bakıyor", "audit_chain.py",
     "                dosyalari_sirala(self.baseFilename)).son_tanik_dogumu",
     "                dosyalari_sirala(self.baseFilename)).tanik_baslangici",
     [IN2 + "test_tanik_sifirlaninca_yeniden_dogar_sonraki_acilislar_sessiz"]),
    ("7", "yazarken doğan kayıtlar bir sonraki olayı bekliyor", "audit_chain.py",
     "            # gelmeyebilir.\n            self._bekleyenleri_yaz(record)\n",
     "            # gelmeyebilir.\n",
     [IN2 + "test_kesinti_tamamlaninca_kaydi_hemen_yaziliyor",
      IN2 + "test_calisirken_silinen_tanik_hemen_bildiriliyor_ve_yeniden_doguyor"]),
    ("7", "kapanırken bekleyen kayıtlar yazılmıyor", "audit_chain.py",
     "                    self._bekleyenleri_yaz(kayit)\n", "",
     [IN2 + "test_kesinti_bot_kapanirken_tamamlanirsa_kaydi_yine_yaziliyor"]),
    ("7", "eski biçimli onay notu yeni onaydan sonra da uyarıyor", "audit_chain.py",
     "    if yeniler:\n        return (f\"ℹ️ Eski biçimli onay",
     "    if False:\n        return (f\"ℹ️ Eski biçimli onay",
     [IN2 + "test_eski_onay_yeni_onaydan_sonra_uyari_degil_bilgi"]),
    ("7", "yedekler silinince ana dosyanın dönme kaydı yetiyor", "audit_chain.py",
     "    return dogrula(akis(), rotasyon_olabilir=len(dosyalar) > 1)",
     "    return dogrula(akis(), rotasyon_olabilir=True)",
     [IN2 + "test_donmus_dosyalarin_hepsi_silinirse_ana_dosyanin_donme_kaydi_yetmiyor"]),
    ("7", "yedek sayısı sıfırken her yazımda dönme kaydı birikiyor", "audit_chain.py",
     "        if self.maxBytes <= 0 or self.backupCount <= 0:",
     "        if self.maxBytes <= 0:",
     [IN2 + "test_yedek_sayisi_sifirsa_donme_kaydi_yazilmiyor"]),

    # ── Faz 8: ayri hesap -- bot tanigi silemez, kurali kapatamaz ─────────
    ("8", "kurulum betiği bota silme yetkisi veriyor", "scripts/postgres/tanik.sql",
     "    EXECUTE pg_catalog.format('GRANT SELECT ON public.denetim_zinciri TO %I', bot);",
     "    EXECUTE pg_catalog.format('GRANT SELECT, DELETE ON public.denetim_zinciri TO %I', bot);",
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor",
      PG + "test_bot_tanigi_silemez_kurali_kapatamaz"]),
    ("8", "tanığın sahibi bot", "scripts/postgres/tanik.sql",
     "    EXECUTE pg_catalog.format('ALTER TABLE public.denetim_zinciri OWNER TO %I', sahip);",
     "    EXECUTE pg_catalog.format('ALTER TABLE public.denetim_zinciri OWNER TO %I', bot);",
     # Gercek veritabaninda bu bozma kurulumun son kontrolune takilir (bot
     # 'public'te bir tablonun sahibi olur) ve kurulum DURUR. Kanit, metinde.
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor"]),
    ("8", "bot süper kullanıcı kalıyor", "scripts/postgres/tanik.sql",
     "    EXECUTE pg_catalog.format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '",
     "    EXECUTE pg_catalog.format('ALTER ROLE %I LOGIN SUPERUSER NOCREATEDB NOCREATEROLE '",
     # Gercek veritabaninda bu bozma kurulumun kendi uyelik kontrolune
     # takilir (super kullanici her role uyedir) ve kurulum DURUR: test
     # kirmizi degil hata verir. Kanit, betigin metnini sinayan testte.
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor"]),
    ("8", "yetki ölçümü sahipliği görmüyor", "audit_store.py",
     "    if sahip:\n", "    if False:\n",
     [PG + "test_yetki_durumu_olcuyor_ve_kurulum_onariyor"]),
    ("8", "tablo yokken yazılan halka kayboluyor", "audit_chain.py",
     "        if sonuc == TABLO_YOK_SONUCU:\n            self._tablo_yok(sira)\n"
     "            self._kuyruga_ekle(sira, oz, govde)\n            return\n",
     "",
     [IN + "test_tanik_bot_calisirken_silinirse_alarm"]),
    ("8", "sağlık fazla yetkiyi göstermiyor", "vasi.py",
     "    elif yetki is not None:\n        satir += f\" · {yetki[1]}\"\n        tamam = False\n",
     "",
     [TH + "test_saglik_bot_tanigi_silebiliyorsa_uyarir"]),
    ("8", "denetçi fazla yetkiyi görmüyor", "vasi.py",
     "    if y is None or y[0] == audit_store.YALNIZCA_EKLEME:\n        return None",
     "    if True:\n        return None",
     [TH + "test_denetci_fazla_yetkiyi_bulgu_sayiyor_ama_yetenek_kapatmiyor"]),
    ("8", "rapor hesap iddiasını ölçmeden yapıyor", "vasi.py",
     "    elif _yetki[0] == audit_store.YALNIZCA_EKLEME:", "    elif True:",
     [TH + "test_guvenlik_raporu_hesap_iddiasi_olcumden_geliyor"]),
    ("8", "LiteLLM'e veritabanı parolası veriliyor", "docker-compose.yml",
     "      MAX_HISTORY_TURNS: ${MAX_HISTORY_TURNS:-10}\n",
     "      MAX_HISTORY_TURNS: ${MAX_HISTORY_TURNS:-10}\n      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-}\n",
     [TH + "test_litellm_veritabani_sirri_almiyor"]),
    ("8", "süper kullanıcı parolası .env'den okunuyor", "docker-compose.yml",
     "      VASI_BOT_USER: ${POSTGRES_USER:-vasi_bot}\n",
     "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}\n      VASI_BOT_USER: ${POSTGRES_USER:-vasi_bot}\n",
     [TH + "test_veritabani_super_kullaniciyi_env_den_degil_kendi_dosyasindan_aliyor"]),
    ("8", "kurulum botun 'public' fonksiyonlarını çağırıyor", "scripts/postgres/tanik.sql",
     "SET LOCAL search_path = pg_catalog, pg_temp;", "SET LOCAL search_path = public, pg_catalog;",
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor"]),
    ("8", "bot 'public'te nesne kurabiliyor", "scripts/postgres/tanik.sql",
     "    EXECUTE pg_catalog.format('REVOKE CREATE ON SCHEMA public FROM %I', bot);",
     "    EXECUTE pg_catalog.format('GRANT CREATE ON SCHEMA public TO %I', bot);",
     [PG + "test_kurulum_onceki_tablolari_botun_semasina_tasir",
      PG + "test_kurulum_botun_public_tuzagina_dusmuyor"]),
    ("8", "bot kayıt zamanını kendisi yazabiliyor", "scripts/postgres/tanik.sql",
     "        'GRANT INSERT (sira, ozet, govde) ON public.denetim_zinciri TO %I', bot);",
     "        'GRANT INSERT ON public.denetim_zinciri TO %I', bot);",
     [IT + "test_tanik_semasi_yalnizca_ekleme_kabul_ediyor",
      PG + "test_bot_kayit_zamanini_yazamaz"]),
    ("8", "kurulum dolaylı üyeliği onarmış sayıyor", "scripts/postgres/tanik.sql",
     "    IF pg_catalog.pg_has_role(bot, sahip, 'MEMBER') THEN",
     "    IF false THEN",
     [PG + "test_dolayli_uyelik_olculuyor_ve_kurulum_durduruyor"]),
    ("8", "yetki ölçümü dolaylı üyeliği görmüyor", "audit_store.py",
     "       coalesce(pg_catalog.pg_has_role(r.oid, c.relowner, 'MEMBER'), false),",
     "       coalesce(c.relowner = r.oid, false),",
     [PG + "test_dolayli_uyelik_olculuyor_ve_kurulum_durduruyor"]),
    ("8", "yetki ölçümü kapalı kuralı görmüyor", "audit_store.py",
     "    if acik_kural != len(TETIKLEYICILER):", "    if False:",
     [PG + "test_kural_kapatilirsa_olcum_soyluyor"]),

    # ── Faz 9: makine disi capa -- zincirin ucu RFC 3161 makbuzuyla disarida ─
    ("9", "imza doğrulanmıyor (sahte TSA kabul)", "capa.py",
     "            anahtar.verify(imza, imzali, ec.ECDSA(h))", "            pass",
     [CP + "test_damgala_baska_anahtarla_imzali_makbuzu_saklamiyor"]),
    ("9", "imza makbuzun içeriğini kapsamıyor", "capa.py",
     "    if mesaj_ozeti != hashlib.new(ozet_adi, m._tstinfo).digest():", "    if False:",
     [CP + "test_openssl_makbuzunda_tek_bayt_degisirse_imza_tutmuyor"]),
    ("9", "başka özeti damgalayan makbuz kabul", "capa.py",
     "    if m.imprint_alg != \"sha256\" or m.imprint != hashlib.sha256(metin).digest():", "    if False:",
     [CP + "test_damgala_yanlis_makbuzu_reddediyor"]),
    ("9", "nonce kontrol edilmiyor (eski makbuz tekrar)", "capa.py",
     "    if m.nonce != nonce:", "    if False:",
     [CP + "test_damgala_yanlis_makbuzu_reddediyor"]),
    ("9", "çapadan sonra yeniden yazılan halka görülmüyor", "capa.py",
     "            if alan != c.ozet or (hesap is not None and hesap != c.ozet):", "            if False:",
     [CP + "test_capalanmis_halka_yeniden_yazilirsa_yakalaniyor",
      CP + "test_dosya_capadan_sonra_yeniden_yazilirsa_saglik_ve_iz_dogrula_soyler"]),
    ("9", "zincirin kesilen sonu görülmüyor", "capa.py",
     "        elif c.sira > r.zincir_son_sira:", "        elif False:",
     [CP + "test_zincirin_sonu_kesilirse_yakalaniyor"]),
    ("9", "aynı sıraya iki çapa görülmüyor", "capa.py",
     "        if len(ozetler) > 1:", "        if False:",
     [CP + "test_yeniden_yazip_yeniden_capalamak_iki_farkli_capa_birakir"]),
    ("9", "çapaların zaman sırası kontrol edilmiyor", "capa.py",
     "        if onceki is not None and c.sira > onceki.sira and c.makbuz.zaman < onceki.makbuz.zaman:",
     "        if False:",
     [CP + "test_geriye_tarihli_zincir_capa_zamanindan_yakalaniyor"]),
    ("9", "makbuzun üstüne yazılabiliyor", "capa.py",
     "    if hedef.exists():", "    if False:",
     [CP + "test_kaydet_var_olan_makbuzun_ustune_yazmaz"]),
    ("9", "yeni halka yokken yeniden çapalıyor", "vasi.py",
     "        if any(c.sira == sira and c.ozet == oz for c in capa.makbuzlari_oku(CAPA_DIZINI)):",
     "        if False:",
     [CP + "test_capa_zincirin_ucunu_damgaliyor_yeni_halka_yoksa_tekrar_etmiyor"]),
    ("9", "başarılı çapa ize yazılıyor (saatlik sonsuz döngü)", "vasi.py",
     "    return yol, makbuz\n",
     "    audit_event(\"capa_atildi\", SISTEM_KIMLIGI, str(sira))\n    return yol, makbuz\n",
     [CP + "test_basarili_capa_ize_yazilmaz_bos_sistem_saatlik_mesaj_atmaz"]),
    ("9", "makbuzun kopyası Telegram'a gitmiyor", "vasi.py",
     "    if not CAPA_ACIK:\n        return 0\n    global _capa_gonderim_kilidi",
     "    if True:\n        return 0\n    global _capa_gonderim_kilidi",
     [CP + "test_kopya_telegrama_gidiyor_ve_saglik_yesil"]),
    ("9", "sağlık, tutmayan çapada yeşil", "vasi.py",
     "    tamam = (r.saglam and not r.uyarilar", "    tamam = (True or r.saglam and not r.uyarilar",
     [CP + "test_dosya_capadan_sonra_yeniden_yazilirsa_saglik_ve_iz_dogrula_soyler"]),
    ("9", "TSA'ya ulaşılamaması ize yazılmıyor", "vasi.py",
     "        audit_event(\"capa_atilamadi\", SISTEM_KIMLIGI, f\"{neden}: {hata}\")", "        pass",
     [CP + "test_tsa_ulasilamazsa_bot_durmaz_ve_olay_ize_yazilir"]),
    ("9", "onay anında çapa atılmıyor", "vasi.py",
     "            capa_arka_planda(context, \"onay\")\n", "",
     [CP + "test_onay_hemen_capa_atiyor"]),

    # Bagimsiz inceleme (Ekim 2026) capanin ilk surumunu kirdi; kapatilanlar:
    ("9", "çapa halkanın yalnızca özet alanına bakıyor", "capa.py",
     "            if alan != c.ozet or (hesap is not None and hesap != c.ozet):",
     "            if alan != c.ozet:",
     [CP + "test_capali_satirin_govdesi_degisip_ozeti_birakilirsa_yakalaniyor"]),
    ("9", "silinen çapalı halka görülmüyor", "capa.py",
     "        elif ilk_dosya is not None and c.sira >= ilk_dosya:", "        elif False:",
     [CP + "test_capali_satir_silinirse_yakalaniyor"]),
    ("9", "doğrulayıcı zincirin kendisine bakmıyor", "capa.py",
     "    if not dosya_r.saglam:\n        print(f\"🔴 Zincirin", "    if False:\n        print(f\"🔴 Zincirin",
     [CP + "test_cli_zincirin_kendisi_kiriksa_temiz_demiyor"]),
    ("9", "sahte rotasyon 'tutuyor' sayılıyor", "capa.py",
     "    return 3 if r.uyarilar else 0", "    return 0",
     [CP + "test_sahte_rotasyon_temiz_gecmiyor"]),
    ("9", "çapadan sonra verilen onay sorgulanmıyor", "capa.py",
     "        if kapsayan:", "        if False:",
     [CP + "test_capadan_sonra_verilen_sahte_onay_uyari_veriyor"]),
    ("9", "bozuk makbuz doğrulayıcıyı düşürüyor", "capa.py",
     "    except Exception as e:\n        raise CapaHatasi(f\"makbuz biçimi bozuk",
     "    except ZeroDivisionError as e:\n        raise CapaHatasi(f\"makbuz biçimi bozuk",
     [CP + "test_bozuk_makbuz_dogrulayiciyi_dusurmuyor_bulgu_oluyor"]),
    ("9", "geç damgalanmış çapa sorgulanmıyor", "capa.py",
     "                if fark > tolerans or fark < -timedelta(hours=15):", "                if False:",
     [CP + "test_halkasindan_cok_sonra_damgalanan_capa_uyari"]),
    ("9", "bozuk makbuz Telegram kopyalarını durduruyor", "vasi.py",
     "atlandı ({c.dosya}): {e}\")\n            continue", "atlandı ({c.dosya}): {e}\")\n            break",
     [CP + "test_bozuk_makbuz_telegram_kopyalarini_durdurmuyor"]),
    ("9", "ileri sıralı bir dosya çapalamayı durduruyor", "vasi.py",
     "        if any(c.sira == sira and c.ozet == oz for c in capa.makbuzlari_oku(CAPA_DIZINI)):",
     "        if any(c.sira >= sira for c in capa.makbuzlari_oku(CAPA_DIZINI)):",
     [CP + "test_klasordeki_ileri_sirali_dosya_capalamayi_durdurmuyor"]),
    # Ikinci inceleme: duzeltmenin kendisi her gercek onayda kalici uyari birakiyordu
    ("9", "meşru onay kalıcı uyarı bırakıyor", "capa.py",
     "        if getattr(x, \"tur\", None) not in _MUDAHALE_TURLERI:\n            continue",
     "        if False:\n            continue",
     [CP + "test_mesru_onay_kalici_uyari_birakmiyor"]),
    ("9", "yeniden hesaplanamayan çapa 'temiz' sayılıyor", "capa.py",
     "    if not r.sorunlar and not r.uyarilar and not r.hesaplanamayan and son is not None:",
     "    if not r.sorunlar and not r.uyarilar and son is not None:",
     [CP + "test_ilk_satir_capasi_yeniden_hesaplanamazsa_temiz_denmiyor"]),
]


def _pg_gerekli(test: str) -> bool:
    return test.startswith(PG)


def _kisalt(metin: str, n: int = 110) -> str:
    metin = " ".join(str(metin).split())
    return metin if len(metin) <= n else metin[:n - 1] + "…"


def _ciktinin_ozu(cikti: str) -> str:
    """pytest'in kendi hata satiri (ERROR: ...) varsa o, yoksa son dolu satir."""
    satirlar = [s for s in cikti.splitlines() if s.strip()]
    hatalar = [s for s in satirlar if s.startswith("ERROR")]
    return (hatalar or satirlar or ["(çıktı yok)"])[-1]


def _hata_metni(dugum) -> str:
    """Hatanin kendisi: izdeki son 'E   ...' satiri, yoksa raporun mesaji."""
    e_satirlari = [s[1:].strip() for s in (dugum.text or "").splitlines() if s.startswith("E ")]
    return e_satirlari[-1] if e_satirlari else (dugum.get("message") or dugum.tag)


def _sonucu_oku(kod: int, rapor: Path, cikti: str = "") -> tuple:
    """pytest'in JUnit raporundan sonucu cikarir: (sonuc, neden).

    sonuc: kirmizi | yesil | calismadi. Yalnizca gercekten KOSUP kirmiziya
    donen test sayilir. Hata veren, bulunamayan ya da atlanan bir test
    hicbir seyi kanitlamaz; nedeni ise soylenir.
    """
    try:
        kok = ET.parse(str(rapor)).getroot()
    except (OSError, ET.ParseError):
        return "calismadi", _kisalt(f"pytest raporu yok (çıkış kodu {kod}): {_ciktinin_ozu(cikti)}")
    durumlar = []                        # (durum, ayrinti) -- her testcase icin bir
    for tc in kok.iter("testcase"):
        alt = {c.tag: c for c in tc}
        if "error" in alt:
            durumlar.append(("hata", _hata_metni(alt["error"])))
        elif "failure" in alt:
            durumlar.append(("kirmizi", ""))
        elif "skipped" in alt:
            durumlar.append(("atlandi", alt["skipped"].get("message") or ""))
        else:
            durumlar.append(("yesil", ""))
    if not durumlar:
        return "calismadi", _kisalt(f"test bulunamadı: {_ciktinin_ozu(cikti)}")
    for durum, ayrinti in durumlar:
        if durum == "hata":
            return "calismadi", _kisalt(f"test hata verdi: {ayrinti}")
    for durum, ayrinti in durumlar:
        if durum == "atlandi":
            return "calismadi", _kisalt(f"test atlandı: {ayrinti}")
    kirmizi = any(d == "kirmizi" for d, _ in durumlar)
    if kod == 1 and kirmizi:
        return "kirmizi", ""
    if kod == 0 and not kirmizi:
        return "yesil", ""
    return "calismadi", f"çıkış kodu {kod} raporla çelişiyor"


def kanitla(no: int) -> list:
    """Bir kaniti calistirir: [(test, sonuc, neden)].

    sonuc: kirmizi | yesil | calismadi | atlandi | desen_yok; neden yalnizca
    'calismadi' icin dolu.
    """
    faz, ad, dosya, aranan, yerine, testler = KANITLAR[no - 1]
    with tempfile.TemporaryDirectory() as d:
        kopya = Path(d) / "kopya"
        shutil.copytree(KOK, kopya, ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".git", "venv", ".venv", "denetim", "workspace"))
        hedef = kopya / dosya
        metin = hedef.read_text(encoding="utf-8")
        if metin.count(aranan) != 1:
            return [(t, "desen_yok", "") for t in testler]
        hedef.write_text(metin.replace(aranan, yerine), encoding="utf-8")
        sonuclar = []
        for i, test in enumerate(testler):
            if _pg_gerekli(test) and not os.getenv("VASI_TEST_PG"):
                sonuclar.append((test, "atlandi", ""))
                continue
            rapor = Path(d) / f"rapor_{i}.xml"   # kopyanin DISINDA
            r = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x",
                 f"--junitxml={rapor}", test],
                cwd=kopya, capture_output=True, text=True,
            )
            sonuc, neden = _sonucu_oku(r.returncode, rapor, r.stdout + "\n" + r.stderr)
            sonuclar.append((test, sonuc, neden))
        return sonuclar


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    secilen = list(range(1, len(KANITLAR) + 1))
    if args[:1] == ["--sadece"] and len(args) > 1:
        secilen = [int(x) for x in args[1].split(",")]

    print("🔨 Korumayı kır → ilgili test kırmızıya dönmeli.")
    print("   Kaynak kodun bir kopyasında; depoya ve çalışan bota dokunulmaz.\n")
    # Gercek veritabani testleri ayni test veritabanini paylasiyor: paralel
    # kosarlarsa birbirinin tablosunu silerler. O zaman sirayla.
    isci = 1 if os.getenv("VASI_TEST_PG") else max(2, min(6, os.cpu_count() or 2))
    with ThreadPoolExecutor(max_workers=isci) as havuz:
        sonuclar = dict(zip(secilen, havuz.map(kanitla, secilen)))

    yakalanan = toplam = atlanan = 0
    sorunlu = []
    faz_onceki = None
    for no in secilen:
        faz, ad = KANITLAR[no - 1][:2]
        if faz != faz_onceki:
            print(f"Faz {faz}")
            faz_onceki = faz
        for test, sonuc, neden in sonuclar[no]:
            kisa = test.split("::")[1]
            if sonuc == "atlandi":
                atlanan += 1
                print(f"  –  {no:>2} {ad}  (gerçek veritabanı ister: atlandı)")
                continue
            toplam += 1
            if sonuc == "kirmizi":
                yakalanan += 1
                print(f"  ✓  {no:>2} {ad}  →  {kisa}")
            elif sonuc == "desen_yok":
                sorunlu.append(no)
                print(f"  ✗  {no:>2} {ad}  →  KOD DEĞİŞMİŞ: bozulacak satır bulunamadı")
            elif sonuc == "calismadi":
                sorunlu.append(no)
                print(f"  ✗  {no:>2} {ad}  →  {kisa} ÇALIŞMADI, kanıt yok")
                print(f"         neden: {neden}")
            else:
                sorunlu.append(no)
                print(f"  ✗  {no:>2} {ad}  →  {kisa} YEŞİL KALDI: bozulma yakalanmadı!")

    print()
    ek = f" · {atlanan} atlandı" if atlanan else ""
    print(f"{toplam} bozma · {yakalanan} tanesi yakalandı{ek}")
    if sorunlu:
        print(f"Yakalanmayan ya da eskimiş kanıt: {', '.join(map(str, sorted(set(sorunlu))))}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
