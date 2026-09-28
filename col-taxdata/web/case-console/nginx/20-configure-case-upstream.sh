#!/bin/sh
set -eu

: "${CASE_API_UPSTREAM:?CASE_API_UPSTREAM must be set to the CASE REST origin}"

DEFAULT_CASE_API_READ_TIMEOUT_SECONDS=7260
MIN_CASE_API_READ_TIMEOUT_SECONDS=7201
MAX_CASE_API_READ_TIMEOUT_SECONDS=86400
CASE_API_READ_TIMEOUT_SECONDS="${CASE_API_READ_TIMEOUT_SECONDS:-$DEFAULT_CASE_API_READ_TIMEOUT_SECONDS}"

# The upstream is deployment configuration, never browser input. Restrict it to
# an HTTP(S) origin with optional numeric port so sed/template expansion cannot
# create nginx directives or arbitrary-path proxying.
if ! printf '%s\n' "$CASE_API_UPSTREAM" | grep -Eq '^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?/?$'; then
  echo "CASE_API_UPSTREAM must be an http(s) origin without a path, query or fragment" >&2
  exit 64
fi

# The public Web request is synchronous. Its response timeout must remain longer
# than the admitted CASE runtime so the outer proxy cannot terminate valid work.
if ! printf '%s\n' "$CASE_API_READ_TIMEOUT_SECONDS" | grep -Eq '^[0-9]+$'; then
  echo "CASE_API_READ_TIMEOUT_SECONDS must be an integer number of seconds" >&2
  exit 64
fi
if [ "$CASE_API_READ_TIMEOUT_SECONDS" -lt "$MIN_CASE_API_READ_TIMEOUT_SECONDS" ] || \
   [ "$CASE_API_READ_TIMEOUT_SECONDS" -gt "$MAX_CASE_API_READ_TIMEOUT_SECONDS" ]; then
  echo "CASE_API_READ_TIMEOUT_SECONDS must be between $MIN_CASE_API_READ_TIMEOUT_SECONDS and $MAX_CASE_API_READ_TIMEOUT_SECONDS seconds" >&2
  exit 64
fi

CASE_API_UPSTREAM="${CASE_API_UPSTREAM%/}"
sed \
  -e "s|__CASE_API_UPSTREAM__|${CASE_API_UPSTREAM}|g" \
  -e "s|__CASE_API_READ_TIMEOUT_SECONDS__|${CASE_API_READ_TIMEOUT_SECONDS}|g" \
  /etc/nginx/case-console.conf.template > /etc/nginx/conf.d/default.conf
