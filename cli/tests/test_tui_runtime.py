import asyncio
from pathlib import Path
import sys

import pytest

from arclith_cli.project_runtime import RuntimeCommand, RuntimeMode
from arclith_cli.tui_runtime import ManagedRuntime


def _command(tmp_path: Path, code: str) -> RuntimeCommand:
    return RuntimeCommand(
        root=tmp_path,
        project_name="runtime-service",
        mode=RuntimeMode.API,
        argv=(sys.executable, "-u", "-c", code),
        environment=(("MODE", "api"),),
        endpoint=None,
    )


@pytest.mark.asyncio
async def test_managed_runtime_streams_output(tmp_path: Path) -> None:
    runtime = ManagedRuntime()
    lines: list[str] = []

    return_code = await runtime.run(_command(tmp_path, "print('ready')"), lines.append)

    assert return_code == 0
    assert lines == ["ready"]
    assert runtime.is_running is False


@pytest.mark.asyncio
async def test_managed_runtime_stops_its_process_group(tmp_path: Path) -> None:
    runtime = ManagedRuntime()
    task = asyncio.create_task(
        runtime.run(
            _command(tmp_path, "import time; print('ready'); time.sleep(30)"),
            lambda _line: None,
        )
    )
    for _ in range(100):
        if runtime.is_running:
            break
        await asyncio.sleep(0.01)

    assert runtime.is_running is True
    assert await runtime.stop(timeout=1.0) is True
    await asyncio.wait_for(task, timeout=2.0)
    assert runtime.is_running is False
    assert await runtime.stop() is False
