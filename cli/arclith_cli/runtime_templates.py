from __future__ import annotations

DEFAULT_UV_VERSION = "0.8.14"
DEFAULT_API_PORT = "8000"
DEFAULT_MCP_PORT = "8001"
DEFAULT_PROBE_PORT = "9000"
DEFAULT_AGENT_PORT = "2024"


DOCKERFILE_TEMPLATE = """# syntax=docker/dockerfile:1.7
# Multi-stage Arclith runtime image. Dependencies come from uv.lock only.
FROM python:3.13-slim-bookworm AS builder

ARG UV_VERSION={uv_version}

ENV UV_LINK_MODE=copy \\
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN python -m pip install --no-cache-dir --root-user-action=ignore "uv==$UV_VERSION"

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \\
    uv sync --frozen --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \\
    uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm AS runtime

RUN groupadd --gid 1001 arclith \\
 && useradd --uid 1001 --gid arclith --home-dir /app --shell /usr/sbin/nologin --no-create-home arclith

WORKDIR /app

COPY --from=builder --chown=1001:1001 /app/.venv /app/.venv
COPY --chown=1001:1001 . .

RUN chmod 0555 /app/arclith-run

ENV PATH="/app/.venv/bin:$PATH" \\
    PYTHONPATH="/app/src:/app" \\
    PYTHONUNBUFFERED=1 \\
    PYTHONDONTWRITEBYTECODE=1 \\
    ARCLITH_PROBE_PORT={probe_port} \\
    LANGGRAPH_PORT={agent_port}

USER 1001:1001

# FastAPI, FastMCP, probes and LangGraph local server.
EXPOSE {api_port} {mcp_port} {probe_port} {agent_port}

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \\
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('ARCLITH_PROBE_PORT', '9000') + '/health', timeout=2)" || exit 1

ENTRYPOINT ["./arclith-run"]
CMD ["api"]
"""


DOCKERIGNORE_TEMPLATE = """.git
.venv
__pycache__/
*.py[cod]
.mypy_cache/
.pytest_cache/
.ruff_cache/
htmlcov/
.coverage
dist/
*.egg-info/
tests/
docs/
site/
.env
.env.*
!.env.example
secrets.yaml
*.pem
*.key
*.crt
id_rsa
id_ed25519
"""


ARCLITH_RUN_TEMPLATE = """#!/usr/bin/env sh
set -eu

if [ -n "${{ARCLITH_RUNTIME_MODE:-}}" ]; then
    mode="$ARCLITH_RUNTIME_MODE"
    case "${{1:-}}" in
        api|mcp|mcp_http|mcp_sse|bus|command_bus|command-bus|agent|all) shift ;;
    esac
elif [ -n "${{MODE:-}}" ]; then
    mode="$MODE"
    case "${{1:-}}" in
        api|mcp|mcp_http|mcp_sse|bus|command_bus|command-bus|agent|all) shift ;;
    esac
elif [ "$#" -gt 0 ]; then
    mode="$1"
    shift
else
    mode="api"
fi

case "$mode" in
    api)
        export MODE=api
        exec python main.py "$@"
        ;;
    mcp|mcp_http)
        export MODE=mcp_http
        exec python main.py "$@"
        ;;
    mcp_sse)
        export MODE=mcp_sse
        exec python main.py "$@"
        ;;
    bus|command_bus|command-bus)
        export MODE=bus
        exec python main.py "$@"
        ;;
    agent)
        if [ -n "${{ARCLITH_AGENT_COMMAND:-}}" ]; then
            exec sh -c "$ARCLITH_AGENT_COMMAND" -- "$@"
        fi
        if [ ! -f langgraph.json ]; then
            echo "langgraph.json missing; configure agent/langgraph or set ARCLITH_AGENT_COMMAND." >&2
            exit 64
        fi
        if [ "${{ARCLITH_AGENT_RUNTIME:-development}}" = "durable" ]; then
            exec arclith-agent-runtime \\
                --config "${{ARCLITH_LANGGRAPH_CONFIG:-langgraph.json}}" \\
                --host "${{LANGGRAPH_HOST:-0.0.0.0}}" \\
                --port "${{LANGGRAPH_PORT:-2024}}" \\
                "$@"
        fi
        exec langgraph dev \\
            --host "${{LANGGRAPH_HOST:-0.0.0.0}}" \\
            --port "${{LANGGRAPH_PORT:-2024}}" \\
            --no-browser \\
            --allow-blocking \\
            "$@"
        ;;
    all)
        export MODE=all
        exec python main.py "$@"
        ;;
    *)
        echo "Unsupported Arclith runtime mode: $mode" >&2
        echo "Expected: api, mcp, mcp_http, mcp_sse, bus, agent or all." >&2
        exit 64
        ;;
esac
"""


def render_dockerfile(
    *,
    uv_version: str = DEFAULT_UV_VERSION,
    api_port: str = DEFAULT_API_PORT,
    mcp_port: str = DEFAULT_MCP_PORT,
    probe_port: str = DEFAULT_PROBE_PORT,
    agent_port: str = DEFAULT_AGENT_PORT,
) -> str:
    return DOCKERFILE_TEMPLATE.format(
        uv_version=uv_version,
        api_port=api_port,
        mcp_port=mcp_port,
        probe_port=probe_port,
        agent_port=agent_port,
    )


def render_arclith_run() -> str:
    return ARCLITH_RUN_TEMPLATE.format()
