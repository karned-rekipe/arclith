#!/bin/bash
# Test E2E complet : arclith-cli new → uv sync → imports → server start
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

version_lt() {
    local left_major left_minor left_patch right_major right_minor right_patch
    IFS=. read -r left_major left_minor left_patch <<< "$1"
    IFS=. read -r right_major right_minor right_patch <<< "$2"

    ((left_major < right_major)) && return 0
    ((left_major > right_major)) && return 1
    ((left_minor < right_minor)) && return 0
    ((left_minor > right_minor)) && return 1
    ((left_patch < right_patch))
}

echo "🧪 Test E2E — arclith-cli scaffold"
echo ""

# Cleanup
TEST_DIR="/tmp/arclith-e2e-test-$(date +%s)"
trap "rm -rf $TEST_DIR" EXIT

# Step 1 — Scaffold
echo "Step 1/5 — Scaffolding project..."
arclith-cli new Widget e2e-test --dir /tmp --port 9700 > /dev/null
mv /tmp/e2e-test "$TEST_DIR"
cd "$TEST_DIR"

# Step 2 — Verify stable PyPI
echo "Step 2/5 — Verifying stable PyPI dependencies..."
if grep -q '\[tool\.uv\.sources\]' pyproject.toml; then
    echo -e "${RED}✗ FAIL: [tool.uv.sources] detected in generated project${NC}"
    exit 1
fi

ARCLITH_VERSION=$(grep 'arclith\[' pyproject.toml | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
MIN_ARCLITH_VERSION="0.18.0"
if version_lt "$ARCLITH_VERSION" "$MIN_ARCLITH_VERSION"; then
    echo -e "${RED}✗ FAIL: arclith version < $MIN_ARCLITH_VERSION (found: $ARCLITH_VERSION)${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} arclith>=$MIN_ARCLITH_VERSION from PyPI (found: $ARCLITH_VERSION)"

# Step 3 — Install
echo "Step 3/5 — Installing dependencies (uv sync)..."
uv sync --no-dev > /dev/null 2>&1

# Step 4 — Validate imports
echo "Step 4/5 — Validating critical imports..."
uv run python -c "
from pathlib import Path
from arclith import load_config_dir, Arclith
from e2e_test.adapters.inbound.fastapi.dependencies import require_auth
from e2e_test.adapters.inbound.fastmcp.dependencies import require_auth_mcp
print('✅ All imports OK')
" 2>&1 | grep "✅" || {
    echo -e "${RED}✗ FAIL: Import error${NC}"
    exit 1
}

# Step 5 — Test server start (timeout 3s)
echo "Step 5/5 — Testing server startup..."
timeout 3 uv run python main.py > /dev/null 2>&1 &
PID=$!
sleep 2

if ps -p $PID > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Server started successfully"
    kill $PID 2>/dev/null || true
else
    echo -e "${RED}✗ FAIL: Server failed to start${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ E2E TEST PASSED${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Project scaffolded in: $TEST_DIR"
echo "To explore:"
echo "  cd $TEST_DIR"
echo "  uv run python main.py"
