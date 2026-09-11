#!/bin/bash
# Parcours manuel complet: init -> coeur -> adapters choisis -> route -> serveur.
set -euo pipefail

test_parent=$(mktemp -d)
project_dir="$test_parent/todo-api-e2e"
server_pid=""

cleanup() {
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" 2>/dev/null || true
    fi
    rm -rf "$test_parent"
}
trap cleanup EXIT

arclith-cli init todo-api-e2e --dir "$test_parent"
cd "$project_dir"

arclith-cli add-entity Todo
arclith-cli add-usecase CreateTodo --entity Todo
arclith-cli add-adapter --capability repository --adapter memory --yes
arclith-cli add-adapter \
    --capability api \
    --adapter fastapi \
    --param host=127.0.0.1 \
    --param port=9700 \
    --param reload=false \
    --yes
arclith-cli expose-usecase CreateTodo \
    --via fastapi \
    --feature todos \
    --path /v1/todos \
    --method POST \
    --status-code 201

grep -q 'arclith\[fastapi\]' pyproject.toml
! grep -q 'arclith\[[^]]*mcp' pyproject.toml
test ! -e src/todo_api_e2e/adapters/inbound/fastmcp

uv sync
uv run pytest -q

MODE=api uv run python main.py >server.log 2>&1 &
server_pid=$!
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:9700/openapi.json >/dev/null; then
        break
    fi
    sleep 1
done

curl -fsS http://127.0.0.1:9700/openapi.json | grep -q '"/v1/todos"'
curl -fsS -X POST \
    -H 'Content-Type: application/json' \
    -d '{}' \
    http://127.0.0.1:9700/v1/todos | grep -q '"version":1'

echo "E2E_OK http://127.0.0.1:9700/docs"
