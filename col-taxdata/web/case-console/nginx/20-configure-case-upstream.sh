#!/bin/sh
set -eu

: "${CASE_API_UPSTREAM:?CASE_API_UPSTREAM must be set to the CASE REST origin}"

# The upstream is deployment configuration, never browser input. Restrict it to
# an HTTP(S) origin with optional numeric port so sed/template expansion cannot
# create nginx directives or arbitrary-path proxying.
if ! printf '%s\n' "$CASE_API_UPSTREAM" | grep -Eq '^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?/?$'; then
  echo "CASE_API_UPSTREAM must be an http(s) origin without a path, query or fragment" >&2
  exit 64
fi

CASE_API_UPSTREAM="${CASE_API_UPSTREAM%/}"
sed "s|__CASE_API_UPSTREAM__|${CASE_API_UPSTREAM}|g" \
  /etc/nginx/case-console.conf.template > /etc/nginx/conf.d/default.conf
