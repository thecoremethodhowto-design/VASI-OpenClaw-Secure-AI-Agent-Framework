#!/usr/bin/env bash
#
# Korumalari tek tek bozar; her seferinde ilgili test kirmiziya donmeli.
# Kaynak kodun bir KOPYASINDA calisir: depoya ve calisan bota dokunmaz.
#
# Kullanim:
#   ./kanit.sh                 tum kanitlar (konteynerde)
#   ./kanit.sh --sadece 7      tek bir kanit
#   ./kanit.sh --sadece 1,12   birkac kanit
#
set -euo pipefail
SERVIS="${SERVIS:-vasi-core}"

if ! command -v docker >/dev/null 2>&1; then
    echo "DURDURULDU — docker bulunamadi."
    exit 1
fi

# Imaj, depodaki kodu tasimali: kanit, kodun KOPYASINI bozuyor.
docker compose build "$SERVIS" >/dev/null
exec docker compose run --rm "$SERVIS" python kanit.py "$@"
