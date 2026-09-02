#!/usr/bin/env bash

set -euo pipefail

: "${VAULT_TOKEN:?Définir VAULT_TOKEN avec le token jetable du serveur Vault dev}"

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_MOUNT="${VAULT_MOUNT:-kv}"

vault_request() {
  curl --fail --silent --show-error \
    --connect-timeout 3 \
    --max-time 10 \
    --header "X-Vault-Token: ${VAULT_TOKEN}" \
    "$@"
}

if mount_details=$(
  vault_request "${VAULT_ADDR}/v1/sys/mounts/${VAULT_MOUNT}/tune" 2>/dev/null
); then
  if ! grep -Fq '"version":"2"' <<<"${mount_details}"; then
    printf 'Erreur : le mount %s existe mais n\x27est pas un KV v2.\n' "${VAULT_MOUNT}" >&2
    exit 1
  fi
else
  vault_request \
    --request POST \
    --header "Content-Type: application/json" \
    --data '{"type":"kv","options":{"version":"2"}}' \
    "${VAULT_ADDR}/v1/sys/mounts/${VAULT_MOUNT}" \
    >/dev/null
fi

vault_request \
  --request POST \
  --header "Content-Type: application/json" \
  --data '{"data":{"value":"mongodb://arclith:arclith@127.0.0.1:27017/todo_list_service?authSource=admin"}}' \
  "${VAULT_ADDR}/v1/${VAULT_MOUNT}/data/apps/todo-list/mongodb" \
  >/dev/null

vault_request \
  --request POST \
  --header "Content-Type: application/json" \
  --data '{"data":{"uri":"mongodb://arclith:arclith@127.0.0.1:27017/todo_client_a?authSource=admin","db_name":"todo_client_a"}}' \
  "${VAULT_ADDR}/v1/${VAULT_MOUNT}/data/rekipe/tenants/client-a" \
  >/dev/null

vault_request \
  "${VAULT_ADDR}/v1/${VAULT_MOUNT}/data/apps/todo-list/mongodb" \
  >/dev/null
vault_request \
  "${VAULT_ADDR}/v1/${VAULT_MOUNT}/data/rekipe/tenants/client-a" \
  >/dev/null

printf '%s\n' \
  "Vault KV v2 prêt :" \
  "- ${VAULT_MOUNT}/apps/todo-list/mongodb" \
  "- ${VAULT_MOUNT}/rekipe/tenants/client-a"
