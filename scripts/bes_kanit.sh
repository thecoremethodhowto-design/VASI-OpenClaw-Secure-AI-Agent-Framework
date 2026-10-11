#!/usr/bin/env bash
# Sovereign — beş regresyon kanıtı
#
# Tek çekimde çalışır. Her kanıt kendi başlığını basar.
#
#   bash bes_kanit.sh              normal
#   BEKLE=5 bash bes_kanit.sh      her blok arası 5 sn (yavaş okuma)
#
# GÜVENLİK: Başlamadan önce bütün testlerin geçtiğini doğrular.
# Ctrl-C'ye bassan bile dosyalar geri konur.

set -u
BEKLE="${BEKLE:-3}"
PYTEST="docker compose run --rm -T vasi-core python -m pytest"

M='\033[0m'; KIRMIZI='\033[1;31m'; YESIL='\033[1;32m'
MAVI='\033[1;36m'; SARI='\033[1;33m'; GRI='\033[0;90m'

YEDEK_DIZIN="$(mktemp -d)"

# Her çıkışta — normal, hata, Ctrl-C — dosyaları geri koy.
hepsini_geri () {
  for f in "$YEDEK_DIZIN"/*; do
    [ -e "$f" ] || continue
    cp "$f" "./$(basename "$f")"
  done
  rm -rf "$YEDEK_DIZIN"
}
trap hepsini_geri EXIT INT TERM

yedekle () { [ -e "$YEDEK_DIZIN/$1" ] || cp "$1" "$YEDEK_DIZIN/$1"; }
geri     () { cp "$YEDEK_DIZIN/$1" "$1"; }

baslik () {
  echo
  echo -e "${MAVI}══════════════════════════════════════════════════════════${M}"
  echo -e "${MAVI}  $1 / 5   ${SARI}$2${M}"
  echo -e "${GRI}  kırılan: $3${M}"
  echo -e "${MAVI}══════════════════════════════════════════════════════════${M}"
  echo
}

# pytest ozet satirini cikarir. "tail -1" ILERLEME NOKTALARINI yakalayabiliyor;
# satir sonuna degil, DESENE bakiyoruz.
ozet_bul () { printf '%s\n' "$1" | tr -d '\r' | grep -E "[0-9]+ (passed|failed|error)" | tail -1; }

calistir () {
  $PYTEST "tests/test_sovereign.py::$1" -q --no-header --tb=long 2>/dev/null \
    | grep -E "^E " | head -2 | sed 's/^E *//' \
    | while IFS= read -r satir; do echo -e "   ${KIRMIZI}${satir}${M}"; done
  echo
  echo -e "   ${KIRMIZI}✗ test kırıldı${M}"
  sleep "$BEKLE"
}

# ── ÖN KONTROL ───────────────────────────────────────────────────
# Kırmaya başlamadan önce her şeyin sağlam olduğunu doğrula.
# Atlamak için:  ATLA=1 bash bes_kanit.sh
clear
if [ "${ATLA:-0}" != "1" ]; then
  echo -e "${GRI}başlangıç durumu kontrol ediliyor…${M}"
  ONC="$($PYTEST -q --no-header 2>&1)"
  OZET="$(ozet_bul "$ONC")"

  if printf '%s\n' "$ONC" | tr -d '\r' | grep -qE "[0-9]+ (failed|error)"; then
    echo
    echo -e "${KIRMIZI}DURDURULDU — testler zaten temiz değil:${M}"
    echo -e "   ${OZET:-$(printf '%s\n' "$ONC" | tail -3)}"
    echo
    echo -e "${GRI}Önce bunu düzelt. Kırık bir temelin üzerine kanıt kurulmaz.${M}"
    echo -e "${GRI}Yine de devam etmek için:  ATLA=1 bash bes_kanit.sh${M}"
    exit 1
  fi

  if [ -z "$OZET" ]; then
    echo -e "${SARI}⚠ Özet satırı okunamadı, ama hata da görünmüyor. Devam ediliyor.${M}"
  else
    echo -e "${YESIL}✓ $OZET${M}"
  fi
  sleep 2
fi

clear
echo -e "${SARI}Beş güvenlik testi.${M}"
echo -e "${SARI}Her biri, koruduğu kod kırılarak sınanıyor.${M}"
sleep 2

# ── 1 ────────────────────────────────────────────────────────────
baslik 1 "KATMAN KURALI" "sovereign.py → import access"
yedekle sovereign.py
sed -i 's/^import logging$/import logging\nimport access/' sovereign.py
calistir test_sovereign_hicbir_yerel_modulu_import_etmiyor
geri sovereign.py

# ── 2 ────────────────────────────────────────────────────────────
baslik 2 "DURDURMA KURALI" "durdurabilir → deterministik koşulu çıkarıldı"
yedekle sovereign.py
python3 - <<'EOF'
import pathlib
p=pathlib.Path("sovereign.py"); t=p.read_text(encoding="utf-8")
p.write_text(t.replace("            self.tur == DETERMINISTIK\n            and self.onem == KRITIK",
                       "            self.onem == KRITIK",1),encoding="utf-8")
EOF
calistir test_sezgisel_bulgu_durduramaz
geri sovereign.py

# ── 3 ────────────────────────────────────────────────────────────
baslik 3 "ANLIK GÖRÜNTÜ" "vasi.py → prompta_girebilen alanı silindi"
yedekle vasi.py
python3 - <<'EOF'
import pathlib
p=pathlib.Path("vasi.py"); t=p.read_text(encoding="utf-8")
p.write_text(t.replace('        "prompta_girebilen": memory.PROMPTA_GIREBILEN,\n',"",1),encoding="utf-8")
EOF
calistir test_anlik_goruntu_tum_alanlari_iceriyor
geri vasi.py

# ── 4 ────────────────────────────────────────────────────────────
baslik 4 "GEÇERSİZ KILMA SÜRESİ" "süre kontrolü devre dışı"
yedekle sovereign.py
python3 - <<'EOF'
import pathlib
p=pathlib.Path("sovereign.py"); t=p.read_text(encoding="utf-8")
p.write_text(t.replace("        if (simdi or datetime.now(timezone.utc)) >= bitis:",
                       "        if False:",1),encoding="utf-8")
EOF
calistir test_gecersiz_kilma_suresi_dolunca_yetenek_yeniden_kapaniyor
geri sovereign.py

# ── 5 ────────────────────────────────────────────────────────────
baslik 5 "SARMALAYICI" "ham araç fonksiyonu doğrudan çağrıldı"
yedekle vasi.py
python3 - <<'EOF'
import pathlib
p=pathlib.Path("vasi.py"); t=p.read_text(encoding="utf-8")
p.write_text(t.replace('    sonuc = await run_model_with_tools(model_for_role("teknik")',
                       '    sonuc = await _araclarla_calistir(model_for_role("teknik")',1),encoding="utf-8")
EOF
calistir test_hicbir_yerde_ham_arac_fonksiyonu_dogrudan_cagrilmiyor
geri vasi.py

# ── KAPANIŞ ──────────────────────────────────────────────────────
echo
echo -e "${MAVI}══════════════════════════════════════════════════════════${M}"
echo -e "   ${KIRMIZI}✗  ✗  ✗  ✗  ✗${M}     beşi de kırıldı"
echo -e "${MAVI}══════════════════════════════════════════════════════════${M}"
echo
sleep 2
echo -e "${GRI}kod geri konuyor…${M}"
echo
SONUC="$(ozet_bul "$($PYTEST -q --no-header 2>&1)")"
echo -e "   ${YESIL}✓ ${SONUC:-testler çalıştı}${M}"
echo