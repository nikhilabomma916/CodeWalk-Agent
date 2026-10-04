#!/bin/sh
# Selects the site configuration at container start (run by the nginx image's entrypoint).
#   CODEWALK_PROXY_TLS=off (default)  HTTP on 8080
#   CODEWALK_PROXY_TLS=on             HTTPS on 8443, 8080 redirects; needs mounted certificates
set -eu

src=/etc/nginx/codewalk
dst=/etc/nginx/conf.d
mode="${CODEWALK_PROXY_TLS:-off}"

rm -f "$dst"/*.conf
cp "$src/http-context.conf" "$dst/00-codewalk-http-context.conf"

case "$mode" in
  off)
    cp "$src/site-http.conf" "$dst/10-codewalk-site.conf"
    ;;
  on)
    for file in /etc/nginx/tls/fullchain.pem /etc/nginx/tls/privkey.pem; do
      if [ ! -r "$file" ]; then
        echo "codewalk-proxy: CODEWALK_PROXY_TLS=on but $file is missing or not readable by uid $(id -u)" >&2
        exit 1
      fi
    done
    cp "$src/site-https.conf" "$dst/10-codewalk-site.conf"
    ;;
  *)
    echo "codewalk-proxy: CODEWALK_PROXY_TLS must be 'on' or 'off' (got '$mode')" >&2
    exit 1
    ;;
esac

echo "codewalk-proxy: TLS $mode"
