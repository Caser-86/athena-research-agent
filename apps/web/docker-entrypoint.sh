#!/bin/sh
set -eu

# 仅允许适合放入 Nginx 双引号字符串的 API Key，避免配置注入。
case "${ATHENA_API_KEY:-}" in
  *[!A-Za-z0-9._~-]*)
    echo "ATHENA_API_KEY contains unsupported characters for the web proxy" >&2
    exit 1
    ;;
esac

envsubst '${ATHENA_API_KEY}' \
  < /etc/nginx/athena.conf.template \
  > /etc/nginx/conf.d/default.conf

# 继续使用官方镜像入口脚本的默认初始化与信号处理。
exec /docker-entrypoint.sh "$@"
