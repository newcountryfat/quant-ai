#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
START="${START:-2025-01-01}"
END="${END:-$(date +%F)}"
ASSET_TYPE="${ASSET_TYPE:-index}"
LIMIT="${LIMIT:-3}"
SYMBOL="${SYMBOL:-sh000300}"
SECTOR_SYMBOL="${SECTOR_SYMBOL:-sector:银行}"
SECTOR_SYMBOL_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "${SECTOR_SYMBOL}")"

call() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  echo
  echo "==> ${method} ${BASE_URL}${path}"
  if [[ -n "${data}" ]]; then
    curl -fsS -X "${method}" "${BASE_URL}${path}" \
      -H "Content-Type: application/json" \
      -d "${data}"
  else
    curl -fsS -X "${method}" "${BASE_URL}${path}"
  fi
  echo
}

call GET "/health"
call POST "/api/v1/universe/bootstrap"
call GET "/api/v1/universe/assets?limit=50"
call GET "/api/v1/universe/mappings?relation_type=tracks"
call POST "/api/v1/universe/sync" "{\"asset_type\":\"${ASSET_TYPE}\",\"start\":\"${START}\",\"end\":\"${END}\",\"only_active\":true,\"limit\":${LIMIT}}"
call GET "/api/v1/universe/statuses?asset_type=${ASSET_TYPE}"
call POST "/api/v1/features/breadth/rebuild" "{\"start\":\"${START}\",\"end\":\"${END}\"}"
call GET "/api/v1/features/breadth?limit=5"
call GET "/api/v1/data/${SYMBOL}/info"
call GET "/api/v1/factors/${SYMBOL}"
call POST "/api/v1/backtest" "{\"strategy_id\":\"ma_cross\",\"symbol\":\"${SYMBOL}\",\"start\":\"${START}\",\"end\":\"${END}\",\"params\":{\"fast\":5,\"slow\":20}}"
call POST "/api/v1/universe/sectors/rebuild?market=A"
call GET "/api/v1/universe/assets?asset_type=sector&limit=20"
call GET "/api/v1/universe/sectors/constituents?sector_symbol=${SECTOR_SYMBOL_ENCODED}"
call GET "/api/v1/logs/jobs?limit=20"

echo
echo "P1 backend curl suite completed."
