#!/usr/bin/env bash
#
# Commit ve push ONCESI son kontrol: depoya gidecek dosyalarda sir var mi?
#
# Neden var: bu depo herkese acik. Gercek Telegram kimligi bir kez bir test
# girdisine girdi. tests/test_inceleme_aciklari.py o gunden beri sayilari
# tariyor, ama yalnizca konteynere kopyalanan .py dosyalarinda ve yalnizca
# 10+ haneli sayilari. Bu betik .env'deki GERCEK degerleri, depoya gidecek
# HER dosyada arar: .py, .md, .yml, betikler, hepsi. Hem diskteki halini
# hem sahnelenmis (git add edilmis) halini: commit, sahnelenmis hali alir.
#
# Degerleri ASLA ekrana yazmaz; yalnizca dosya adini ve degiskenin ADINI
# soyler. Ciktisi bu yuzden guvenle bir yere yapistirilabilir.
#
# Kullanim:
#   ./commit_oncesi.sh
#
# Cikis kodu: 0 temiz · 1 sorun var, commit etme · 2 git deposu bulunamadi
#
# macOS'un sistem bash'i (3.2) ve BSD araclariyla uyumlu tutulur.
#
set -uo pipefail

kirmizi=$'\033[31m'; yesil=$'\033[32m'; sari=$'\033[33m'; sifirla=$'\033[0m'
sorun=0
uyari=0
bildir() { echo "${kirmizi}SORUN${sifirla}  $*"; sorun=$((sorun + 1)); }
dikkat() { echo "${sari}DIKKAT${sifirla} $*"; uyari=$((uyari + 1)); }
tamam()  { echo "${yesil}tamam${sifirla}  $*"; }
listele() { while IFS= read -r d; do [ -n "$d" ] && echo "         $d"; done; }

# Betigin kendi deposu -- nereden calistirilirsa calistirilsin.
cd "$(dirname "$0")" || exit 2
kok="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo "Git deposu bulunamadi. Betik depo kokunde durmali."
    exit 2
}
cd "$kok" || exit 2

liste="$(mktemp)"; desen="$(mktemp)"
trap 'rm -f "$liste" "$desen"' EXIT
chmod 600 "$desen"

# Bir dizenin bastaki ve sondaki bosluklarini atar.
kirp() {
    local x="$1"
    x="${x#"${x%%[![:space:]]*}"}"
    x="${x%"${x##*[![:space:]]}"}"
    printf '%s' "$x"
}

# Desen dosyasindaki degerlerden birini iceren dosyalar: hem diskte
# (yeni ve degismis dosyalar) hem sahnede (commit'in alacagi hal).
desenli_dosyalar() {         # $1: -F (sabit dize) ya da -E (ifade)
    { xargs -0 grep -ls "$1" -f "$desen" -- < "$liste"
      git grep -l --cached "$1" -f "$desen"; } 2>/dev/null | sort -u
}

# ── 1) .env ve postgres.env hic takibe girmemis ve yok sayiliyor olmali ─────
# postgres.env veritabaninin SUPER KULLANICI parolasini tasir (Ekim 2026'dan
# beri .env'de degil: .env botun dosyasi, bot onu tamamen alir).
for sirli in .env postgres.env; do
    if git ls-files --error-unmatch "$sirli" >/dev/null 2>&1; then
        bildir "$sirli takibe alinmis (sahnelenmis ya da commit edilmis)."
        echo "         Sahnelendiyse: git rm --cached $sirli"
        echo "         Commit edildiyse: gecmisten silinmeli ve icindeki her anahtar yenilenmeli."
    elif [ ! -e "$sirli" ]; then
        tamam "$sirli bu klasorde yok (takipte de degil)"
    elif ! git check-ignore -q "$sirli"; then
        bildir "$sirli .gitignore'da yok; 'git add -A' onu da ekler."
    else
        tamam "$sirli takipte degil ve yok sayiliyor"
    fi
done

# ── 2) Depoya gidecek dosyalar ──────────────────────────────────────────────
# Takipteki her dosya + yok sayilmayan yeni dosyalar: 'git add -A' tam
# olarak bunlari ekler. Zaten yayinda olan dosyalar da taranir: orada bir
# sir bulunursa o sir COKTAN yayinlanmis demektir ve yenilenmelidir.
git ls-files -z -c -o --exclude-standard > "$liste"
adet="$(tr -cd '\000' < "$liste" | wc -c | tr -d ' ')"
degisen="$(git status --porcelain -uall | wc -l | tr -d ' ')"
tamam "$adet dosya taranacak ($degisen tanesi yeni ya da degismis)"

# ── 3) Asla depoya girmemesi gereken dosya adlari ───────────────────────────
yasak="$( { tr '\000' '\n' < "$liste"; git diff --cached --name-only --diff-filter=d; } \
    | sort -u \
    | grep -E '(^|/)denetim/|(^|/)cekim_|(^|/)eski_iz|\.log(\.[0-9]+)?$|\.pem$|\.key$|(^|/)id_(rsa|ed25519)|(^|/)\.env(\.|$)|(^|/)postgres\.env$' \
    | grep -vE '(^|/)\.env\.example$' || true)"
# .pem bir anahtar da olabilir, acik bir sertifika da. Yalnizca sertifika
# iceren (ozel anahtar icermeyen) .pem dosyasi depoya girebilir: capanin TSA
# sertifikasi (scripts/capa/freetsa/) ve testlerin sahte TSA'si boyle.
acik_sertifika=""
if [ -n "$yasak" ]; then
    kalan=""
    for f in $yasak; do
        case "$f" in
            *.pem)
                if [ -f "$f" ] && grep -q -- '-----BEGIN CERTIFICATE-----' "$f" \
                   && ! grep -q 'PRIVATE KEY' "$f"; then
                    acik_sertifika="$acik_sertifika $f"
                    continue
                fi ;;
        esac
        kalan="$kalan
$f"
    done
    yasak="$(printf '%s' "$kalan" | sed '/^$/d')"
fi
if [ -n "$acik_sertifika" ]; then
    tamam "acik sertifika (ozel anahtar yok):$acik_sertifika"
fi
if [ -n "$yasak" ]; then
    bildir "su dosyalar depoya girmemeli (log, denetim izi, cekim, anahtar, .env, postgres.env):"
    printf '%s\n' "$yasak" | listele
else
    tamam "log, denetim izi, cekim ya da anahtar dosyasi yok"
fi

# ── 4) .env'deki gizli degerler hicbir dosyada gecmemeli ────────────────────
# .env ve postgres.env'de adinda TOKEN, KEY, PASSWORD ya da SECRET gecen
# her degisken (en az 8 karakter) ve MY_TELEGRAM_ID (en az 5 hane).
# YAYINDAKI ornek dosyada (.env.example / postgres.env.example)
# (son commit) aynen gecen bir deger ornek degerdir, sir sayilmaz; diskteki
# .env.example'a sonradan yazilmis gercek bir deger ise taranir. Kimlik hic
# ornek sayilmaz. Her deger sirayla
# yalnizca senin okuyabildigin gecici bir dosyaya yazilir, aranir, ustune
# bir sonraki yazilir; ekrana hic yazilmaz.
taranan=""
ornek=""
# $1: sirli dosya, $2: yayindaki ornegi. Adlar dosyayla birlikte yazilir.
tara() {
    local sirli="$1" ornek_dosya="$2" satir ad deger en_az bulunan
    [ -f "$sirli" ] || return 0
    while IFS= read -r satir || [ -n "$satir" ]; do
        satir="${satir%$'\r'}"
        satir="$(kirp "$satir")"
        case "$satir" in ''|'#'*) continue ;; esac
        satir="${satir#export }"
        case "$satir" in *=*) ;; *) continue ;; esac
        ad="$(kirp "${satir%%=*}")"
        deger="$(kirp "${satir#*=}")"
        case "$deger" in
            \"*) deger="${deger#\"}"; deger="${deger%%\"*}" ;;
            \'*) deger="${deger#\'}"; deger="${deger%%\'*}" ;;
            *)   deger="${deger%%[[:space:]]#*}"; deger="$(kirp "$deger")" ;;
        esac
        case "$ad" in
            MY_TELEGRAM_ID) en_az=5 ;;
            *TOKEN*|*KEY*|*PASSWORD*|*SECRET*) en_az=8 ;;
            *) continue ;;
        esac
        [ "${#deger}" -ge "$en_az" ] || continue
        printf '%s\n' "$deger" > "$desen"
        if [ "$ad" != MY_TELEGRAM_ID ] \
            && git show "HEAD:$ornek_dosya" 2>/dev/null | grep -qF -f "$desen"; then
            ornek="${ornek:+$ornek, }$sirli:$ad"
            continue
        fi
        taranan="${taranan:+$taranan, }$sirli:$ad"
        bulunan="$(desenli_dosyalar -F)"
        if [ -n "$bulunan" ]; then
            bildir "$sirli icindeki $ad degeri su dosyalarda geciyor (deger yazilmadi):"
            printf '%s\n' "$bulunan" | listele
        fi
    done < "$sirli"
    : > "$desen"
}
tara .env .env.example
tara postgres.env postgres.env.example

if [ ! -f .env ]; then
    dikkat ".env yok: gizli deger taramasi yapilmadi."
elif [ -z "$taranan" ]; then
    dikkat ".env ve postgres.env'de taranacak dolu bir gizli deger bulunamadi."
else
    tamam "taranan degiskenler: $taranan"
fi
if [ -n "$ornek" ]; then
    dikkat "bu degiskenlerde yayindaki .env.example'in ornek degeri duruyor, taranmadi: $ornek"
fi

# ── 5) .env'de olmasa da tanidik anahtar bicimleri ──────────────────────────
# Telegram bot tokeni, Google API anahtari, Anthropic anahtari, ozel anahtar.
printf '%s\n' \
    '[0-9]{8,10}:[A-Za-z0-9_-]{35}' \
    'AIza[0-9A-Za-z_-]{35}' \
    'sk-ant-[A-Za-z0-9_-]{20,}' \
    '-----BEGIN [A-Z ]*PRIVATE KEY-----' > "$desen"
bicimli="$(desenli_dosyalar -E)"
: > "$desen"
if [ -n "$bicimli" ]; then
    dikkat "anahtara benzeyen bir dize su dosyalarda var; ac ve bak:"
    printf '%s\n' "$bicimli" | listele
else
    tamam "anahtara benzeyen dize yok"
fi

echo
if [ "$sorun" -gt 0 ]; then
    echo "${kirmizi}$sorun SORUN${sifirla} — commit etme. Once yukaridakileri duzelt."
    exit 1
fi
if [ "$uyari" -gt 0 ]; then
    echo "${sari}TEMIZ, $uyari DIKKAT${sifirla} — sorun yok ama yukaridakilere bir bak."
else
    echo "${yesil}TEMIZ${sifirla} — $adet dosya tarandi; commit edebilirsin."
fi
exit 0
