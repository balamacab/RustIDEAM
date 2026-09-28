#!/bin/sh
set -eu

BASE_URL="${CASE_CONSOLE_HEALTH_BASE_URL:-http://127.0.0.1:8080}"

fetch_headers() {
  wget -S -O /dev/null "${BASE_URL}$1" 2>&1
}

require_status_ok() {
  path="$1"
  headers="$(fetch_headers "$path")" || {
    echo "CASE console readiness failed to fetch $path" >&2
    return 1
  }
  printf '%s\n' "$headers" | grep -Eq '^[[:space:]]*HTTP/[0-9.]+ 200([[:space:]]|$)' || {
    echo "CASE console readiness did not receive HTTP 200 for $path" >&2
    return 1
  }
}

require_content_type() {
  path="$1"
  expected="$2"
  headers="$(fetch_headers "$path")" || {
    echo "CASE console readiness failed to fetch $path" >&2
    return 1
  }
  printf '%s\n' "$headers" | grep -Eiq     "^[[:space:]]*Content-Type:[[:space:]]*${expected}([;[:space:]]|$)" || {
      echo "CASE console readiness received an invalid Content-Type for $path" >&2
      return 1
    }
}

require_status_ok "/healthz"
require_content_type "/app.js" '(application|text)/javascript'
require_content_type "/app-core.mjs" '(application|text)/javascript'
require_content_type "/public-contract.json" 'application/json'
require_content_type "/fixtures/index.json" 'application/json'
