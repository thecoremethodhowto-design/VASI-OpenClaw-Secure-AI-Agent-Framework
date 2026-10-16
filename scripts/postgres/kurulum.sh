#!/bin/sh
# Ikinci tanigin hesaplarini kurar: scripts/postgres/tanik.sql'i calistirir.
#
# Iki yerden calisir, ikisi de postgres konteynerinin ICINDE:
#   1) Ilk kurulum: veritabani birimi bossa resmi imaj bu dosyayi
#      /docker-entrypoint-initdb.d/ altinda kendiliginden calistirir.
#   2) Var olan kurulum (bir kez, elle; tekrar calistirmak guvenli):
#        docker compose exec postgres sh /docker-entrypoint-initdb.d/10-vasi-tanik.sh
#
# Ortam (postgres konteynerinde, docker-compose.yml verir):
#   POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD  super kullanici (postgres.env)
#   VASI_BOT_USER                                  botun hesabi (varsayilan vasi_bot)
#   VASI_BOT_PASSWORD                              botun parolasi (.env'deki POSTGRES_PASSWORD)
#
# Govde bir alt kabukta calisir: resmi imaj, calistirma izni olmayan .sh
# dosyalarini KENDI kabugunda "source" eder. O durumda bile `set -eu` ve
# `exit` imajin kabuguna sizmasin; basarida hic `exit` cagrilmaz.
(
set -eu

BOT="${VASI_BOT_USER:-vasi_bot}"
SAHIP="${VASI_TANIK_SAHIBI:-denetim_sahibi}"
SQL_DOSYASI="${VASI_KURULUM_SQL:-/vasi-kurulum/tanik.sql}"

if [ -z "${VASI_BOT_PASSWORD:-}" ]; then
    # Bos parola: hafiza kapali (.env'de POSTGRES_PASSWORD bos). Ilk kurulumu
    # durdurmak veritabanini yarim birakirdi; atlanir ve soylenir.
    echo "ATLANDI: VASI_BOT_PASSWORD bos (hafiza kapali). Tanik hesaplari kurulmadi." >&2
    echo "  Sonra kurmak icin .env'de POSTGRES_PASSWORD'u doldur ve elle calistir." >&2
    exit 0
fi
if [ "$BOT" = "${POSTGRES_USER:-}" ]; then
    echo "DURDURULDU: bot hesabi ($BOT) super kullaniciyla ayni. .env'de POSTGRES_USER=vasi_bot olmali." >&2
    exit 1
fi
if [ -n "${POSTGRES_PASSWORD:-}" ] && [ "$VASI_BOT_PASSWORD" = "$POSTGRES_PASSWORD" ]; then
    # Bot bu parolayla super kullanici olarak da baglanabilirdi: ayri hesap
    # hicbir sey korumazdi.
    echo "DURDURULDU: botun parolasi super kullanicininkiyle ayni. .env'deki POSTGRES_PASSWORD'u yenile." >&2
    exit 1
fi

# Ayarlar stdin'den verilir: psql degiskenleri (:'...') yalnizca oradan
# okunan komutlarda acilir ve guvenli tirnaklanir. tanik.sql duz SQL'dir.
psql -X -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v bot_rol="$BOT" -v sahip_rol="$SAHIP" -v bot_parola="$VASI_BOT_PASSWORD" \
     -v sql_dosyasi="$SQL_DOSYASI" <<'SQL'
SET vasi.bot_rol = :'bot_rol';
SET vasi.sahip_rol = :'sahip_rol';
SET vasi.bot_parola = :'bot_parola';
\i :sql_dosyasi
SQL
echo "Tanik hesaplari hazir: bot=$BOT (yalnizca ekleme), sahip=$SAHIP (giris yapamaz)."
) || {
    echo "KURULUM BASARISIZ: yukaridaki hatayi duzelt ve elle yeniden calistir:" >&2
    echo "  docker compose exec postgres sh /docker-entrypoint-initdb.d/10-vasi-tanik.sh" >&2
    false
}
