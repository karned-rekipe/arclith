#!/usr/bin/env bash

set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-http://127.0.0.1:8080}"
KEYCLOAK_URL="${KEYCLOAK_URL%/}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-arclith-local}"
KEYCLOAK_CLIENT_ID="${KEYCLOAK_CLIENT_ID:-todo-swagger}"
KEYCLOAK_PASSWORD="${KEYCLOAK_PASSWORD:-arclith-dev-only}"
TODO_API_URL="${TODO_API_URL:-}"

openid_url="${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/.well-known/openid-configuration"

keycloak_request() {
  curl --fail --silent --show-error \
    --connect-timeout 3 \
    --max-time 10 \
    "$@"
}

token_for() {
  local username="$1"
  keycloak_request \
    --request POST \
    --header "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "client_id=${KEYCLOAK_CLIENT_ID}" \
    --data-urlencode "username=${username}" \
    --data-urlencode "password=${KEYCLOAK_PASSWORD}" \
    --data-urlencode "scope=openid profile" \
    "${token_endpoint}" \
    | jq -er '.access_token'
}

decode_claims() {
  python -c '
import base64
import json
import sys

segment = sys.stdin.read().split(".")[1]
segment += "=" * (-len(segment) % 4)
payload = base64.urlsafe_b64decode(segment)
print(json.dumps(json.loads(payload)))
'
}

discovery="$(keycloak_request "${openid_url}")"
token_endpoint="$(jq -er '.token_endpoint' <<<"${discovery}")"
jwks_uri="$(jq -er '.jwks_uri' <<<"${discovery}")"
expected_base="${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}/protocol/openid-connect"

test "${token_endpoint}" = "${expected_base}/token"
test "${jwks_uri}" = "${expected_base}/certs"
keycloak_request "${jwks_uri}" | jq -e '.keys | length > 0' >/dev/null

alice_token="$(token_for alice)"
alice_claims="$(printf '%s' "${alice_token}" | decode_claims)"
jq -e \
  --arg issuer "${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}" \
  --arg audience "todo-api" \
  --arg tenant "client-a" \
  --arg role "rekipe:licensed" \
  'def has_audience($expected):
     (.aud == $expected)
     or (((.aud | type) == "array") and ((.aud | index($expected)) != null));
   (.iss == $issuer)
   and has_audience($audience)
   and (.tenant_id == $tenant)
   and ((.realm_access.roles | index($role)) != null)' \
  <<<"${alice_claims}" >/dev/null

bob_token="$(token_for bob)"
bob_claims="$(printf '%s' "${bob_token}" | decode_claims)"
jq -e \
  '((.realm_access.roles // []) | index("rekipe:licensed")) == null' \
  <<<"${bob_claims}" >/dev/null

printf '%s\n' \
  "Keycloak local prêt :" \
  "- discovery et JWKS cohérents pour ${KEYCLOAK_REALM}" \
  "- alice : audience, tenant_id et rôle licence présents" \
  "- bob : rôle licence absent"

if [[ -n "${TODO_API_URL}" ]]; then
  anonymous_status="$(
    curl --silent --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 3 --max-time 10 "${TODO_API_URL}"
  )"
  alice_status="$(
    curl --silent --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 3 --max-time 10 \
      --header "Authorization: Bearer ${alice_token}" "${TODO_API_URL}"
  )"
  bob_status="$(
    curl --silent --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 3 --max-time 10 \
      --header "Authorization: Bearer ${bob_token}" "${TODO_API_URL}"
  )"

  test "${anonymous_status}" = "401"
  test "${alice_status}" = "200"
  test "${bob_status}" = "403"
  printf '%s\n' "- route protégée : sans token=401, alice=200, bob=403"
fi
