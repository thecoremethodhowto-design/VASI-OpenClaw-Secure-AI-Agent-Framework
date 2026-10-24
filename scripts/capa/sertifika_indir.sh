#!/bin/sh
# freeTSA'nin sertifikalarini indirir ve parmak izlerini sitedekiyle karsilastirir.
#
# Neden depoda: makbuzun imzasi bu sertifikayla dogrulanir. Sertifika
# makinede degil depoda (GitHub'da) durursa, makineyi ele geciren biri onu
# kendi sahte TSA'sinin sertifikasiyla degistiremez -- degistirse bile
# git diff ve GitHub'daki kopya bunu gosterir.
#
# Parmak izleri https://freetsa.org/ sayfasinda yayinlanir (Mart 2026'dan
# itibaren gecerli sertifika, Subat 2040'a kadar). Sayfadaki deger
# degistiyse once SITEDE kontrol et, sonra asagidaki iki satiri guncelle.
#
# Kullanim (proje klasorunde, bir kez):
#   sh scripts/capa/sertifika_indir.sh
set -eu

TSA_SHA256="8bfb0305bb64e2571ca507552ef3245cb1c2fee8728e0ff8689225081ea13467"
CA_SHA256="2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438"
HEDEF="$(dirname "$0")/freetsa"
mkdir -p "$HEDEF"

ozet() {    # dosyanin SHA-256'si (macOS: shasum, Linux: sha256sum)
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

der_ozeti() {   # sertifikanin kendisinin (DER) SHA-256 parmak izi
    openssl x509 -in "$1" -outform DER 2>/dev/null | { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; } | cut -d' ' -f1
}

indir_dogrula() {   # $1 url  $2 dosya adi  $3 beklenen
    gecici="$HEDEF/.$2.indirilen"
    curl -fsS "$1" -o "$gecici"
    dosya=$(ozet "$gecici")
    der=$(der_ozeti "$gecici" || true)
    if [ "$dosya" = "$3" ] || [ "$der" = "$3" ]; then
        mv "$gecici" "$HEDEF/$2"
        echo "TAMAM  $2  $3"
    else
        rm -f "$gecici"
        echo "DURDURULDU: $2 parmak izi sitedekiyle uyusmuyor." >&2
        echo "  beklenen : $3" >&2
        echo "  dosya    : $dosya" >&2
        echo "  sertifika: $der" >&2
        exit 1
    fi
}

indir_dogrula "https://freetsa.org/files/tsa.crt" tsa.crt "$TSA_SHA256"
indir_dogrula "https://freetsa.org/files/cacert.pem" cacert.pem "$CA_SHA256"
echo "Sertifikalar $HEDEF altinda. Commit'le: imzalar artik dogrulanir."
