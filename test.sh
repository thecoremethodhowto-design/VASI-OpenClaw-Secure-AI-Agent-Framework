#!/usr/bin/env bash
#
# Testleri DOGRU ortamda calistirir.
#
# Neden var: bu proje Python 3.10+ sozdizimi kullaniyor (int | None).
# macOS'un sistem python3'u 3.9. "python3 -m pytest" yazdiginda
# proje import bile edilemiyor ve ekran yuzlerce satir TypeError ile
# doluyor -- hicbiri gercek bir test hatasi degil.
#
# Daha kotusu: kaynak METNINI okuyan testler o durumda bile GECER.
# Sistem tamamen oluyken yesil yanan bir test, hicbir sey soylemeyen
# bir testtir.
#
# Kullanim:
#   ./test.sh                      tum testler (konteynerde)
#   ./test.sh tests/test_x.py -v   pytest'e dogrudan aktarilir
#   YEREL=1 ./test.sh              konteyner yerine yerel Python
#
set -euo pipefail

SERVIS="${SERVIS:-vasi-core}"
ASGARI_SURUM="3.10"

renk_kirmizi=$'\033[31m'; renk_yesil=$'\033[32m'
renk_sari=$'\033[33m';    renk_sifirla=$'\033[0m'

surum_yeterli() {           # $1: python calistirilabiliri
    "$1" - <<'PY' 2>/dev/null
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

if [ "${YEREL:-0}" = "1" ]; then
    # ── Yerel Python ────────────────────────────────────────────────
    # Secim sirasi: etkin venv -> ./venv -> surumu YETEN ve pytest'i
    # OLAN ilk aday. Yalnizca en yuksek surumu secmek yanlis: o
    # yorumlayicida bagimliliklar kurulu olmayabilir, yaninda calisan
    # bir tanesi dururken "pytest yok" deriz.
    adaylar=()
    [ -n "${VIRTUAL_ENV:-}" ] && adaylar+=("$VIRTUAL_ENV/bin/python")
    [ -x "./venv/bin/python" ] && adaylar+=("./venv/bin/python")
    for p in python3.13 python3.12 python3.11 python3.10 python3 python; do
        k="$(command -v "$p" 2>/dev/null || true)"
        [ -n "$k" ] && adaylar+=("$k")
    done

    aday=""; yeten=""
    for k in "${adaylar[@]}"; do
        [ -x "$k" ] || continue
        surum_yeterli "$k" || continue
        [ -z "$yeten" ] && yeten="$k"
        if "$k" -c "import pytest" 2>/dev/null; then aday="$k"; break; fi
    done

    if [ -z "$aday" ] && [ -z "$yeten" ]; then
        echo "${renk_kirmizi}DURDURULDU${renk_sifirla} — Python ${ASGARI_SURUM}+ bulunamadi."
        echo
        echo "  Sistemde bulunanlar:"
        for p in python3 python3.12 python3.11; do
            k="$(command -v "$p" 2>/dev/null || true)"
            [ -n "$k" ] && echo "    $k  ->  $("$k" --version 2>&1)"
        done
        echo
        echo "  Bu proje 'int | None' sozdizimi kullaniyor; 3.9 onu tanimiyor."
        echo "  Konteynerde calistirmak icin: ./test.sh"
        exit 1
    fi

    if [ -z "$aday" ]; then
        echo "${renk_sari}pytest kurulu degil${renk_sifirla} ($yeten) — su komutla kur:"
        echo "    $yeten -m venv venv && source venv/bin/activate"
        echo "    pip install -r requirements.txt pytest"
        exit 1
    fi

    echo "${renk_yesil}Yorumlayici${renk_sifirla}: $aday ($("$aday" --version 2>&1))"
    exec "$aday" -m pytest "$@"
fi

# ── Konteyner (varsayilan) ──────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
    echo "${renk_kirmizi}DURDURULDU${renk_sifirla} — docker bulunamadi."
    echo "  Yerel Python ile denemek icin: YEREL=1 ./test.sh"
    exit 1
fi

# On kontrol: Dockerfile her modulu tek tek kopyaliyor. Yeni bir modul
# eklenip burada unutulursa konteynerde import patlar ve bot acilamaz;
# testler de yuzlerce ModuleNotFoundError ile dolar. Tek cumleyle soyle.
eksik=""
for f in *.py; do
    grep -q "^COPY $f " Dockerfile || eksik="$eksik $f"
done
if [ -n "$eksik" ]; then
    echo "${renk_kirmizi}DURDURULDU${renk_sifirla} — Dockerfile su modulleri kopyalamiyor:$eksik"
    echo "  Dockerfile'a ekle:  COPY <modul>.py ."
    exit 1
fi

# Imaji tazele: COPY tests ./tests katmani guncellenmezse konteyner
# ESKI testleri calistirir ve sonuc yanlis bir guven verir.
echo "${renk_yesil}Imaj hazirlaniyor${renk_sifirla} (yeni/degisen dosyalar icin)..."
docker compose build "$SERVIS" >/dev/null

# Calisan bot, az once test edilen imajla mi calisiyor? Olcum: konteynerin
# olusturuldugu imajin kimligi ile etiketin SU ANKI kimligi. Sorgulardan
# biri cevap vermezse sessizce gecer: bu bir uyari, test sonucunu degistirmez.
calisan_bot_eski_mi() {
    local kap kap_imaj etiket etiket_imaj
    kap="$(docker compose ps -q "$SERVIS" 2>/dev/null | head -n 1)" || return 0
    [ -n "$kap" ] || return 0
    kap_imaj="$(docker inspect -f '{{.Image}}' "$kap" 2>/dev/null)" || return 0
    etiket="$(docker inspect -f '{{.Config.Image}}' "$kap" 2>/dev/null)" || return 0
    etiket_imaj="$(docker image inspect -f '{{.Id}}' "$etiket" 2>/dev/null)" || return 0
    if [ -n "$etiket_imaj" ] && [ "$kap_imaj" != "$etiket_imaj" ]; then
        echo
        echo "${renk_sari}DIKKAT${renk_sifirla} — testler YENI imajda calisti; Telegram'daki bot ise ESKI imajla calisiyor."
        echo "  Yayina almak icin:  docker compose up -d --build"
        echo "  (docker compose start/restart ayni eski konteyneri baslatir; yeni imaji almaz.)"
    fi
}

echo "${renk_yesil}Testler konteynerde${renk_sifirla} ($SERVIS)"
set +e
docker compose run --rm "$SERVIS" python -m pytest "$@"
kod=$?
set -e

# Yesil sonuc, test edilen imaj hakkindadir -- Telegram'da konusan bot
# hakkinda degil. Olculdu (3 Ekim 2026): 530 test yesilken bot eski
# surumdu; denetim izinde tek bir zincirli satir yoktu.
calisan_bot_eski_mi
exit "$kod"
