#!/bin/sh
# Entrypoint фронтенд-контейнера на Railway (замена Docker embedded DNS из compose).
#
# 1. Берёт IP резолвера приватной сети из /etc/resolv.conf контейнера
#    (на Railway это не 127.0.0.11, как в compose, а другой адрес —
#    поэтому вычисляем его в рантайме, а не хардкодим).
# 2. Требует API_UPSTREAM (host:port api-сервиса, например
#    api.railway.internal:8000 — см. переменную окружения в Railway).
# 3. Рендерит /etc/nginx/conf.d/default.conf из шаблона и запускает nginx.
set -eu

RESOLVER_IP="$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf 2>/dev/null || true)"
: "${RESOLVER_IP:=127.0.0.11}"

if [ -z "${API_UPSTREAM:-}" ]; then
    echo "[entrypoint-frontend] ERROR: переменная окружения API_UPSTREAM не задана" >&2
    echo "[entrypoint-frontend] Пример: API_UPSTREAM=\${{api.RAILWAY_PRIVATE_DOMAIN}}:\${{api.PORT}}" >&2
    exit 1
fi

export RESOLVER_IP API_UPSTREAM

echo "[entrypoint-frontend] resolver=${RESOLVER_IP} api_upstream=${API_UPSTREAM}"

envsubst '${RESOLVER_IP} ${API_UPSTREAM}' \
    < /etc/nginx/conf.d/default.conf.template \
    > /etc/nginx/conf.d/default.conf

exec "$@"
