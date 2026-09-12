import asyncio
from collections.abc import Callable
import os
import signal

from arclith_cli.project_runtime import RuntimeCommand

RuntimeLineSink = Callable[[str], None]


class ManagedRuntime:
    """Own exactly one child runtime and its complete process group."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def run(self, command: RuntimeCommand, on_line: RuntimeLineSink) -> int:
        """Start a runtime, stream merged output, and wait for its completion."""
        if self.is_running:
            raise RuntimeError("Un runtime Arclith est déjà actif.")
        process = await asyncio.create_subprocess_exec(
            *command.argv,
            cwd=command.root,
            env=command.process_environment(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        self._process = process
        assert process.stdout is not None
        try:
            while line := await process.stdout.readline():
                on_line(line.decode(errors="replace").rstrip())
            return await process.wait()
        finally:
            if self._process is process:
                if process.returncode is None:
                    await self.stop()
                self._process = None

    async def stop(self, *, timeout: float = 5.0) -> bool:
        """Stop the owned process group and escalate only after a grace period."""
        process = self._process
        if process is None or process.returncode is not None:
            return False
        try:
            self._interrupt(process)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            try:
                self._kill(process)
            except ProcessLookupError:
                pass
            await process.wait()
        if self._process is process:
            self._process = None
        return True

    @staticmethod
    def _interrupt(process: asyncio.subprocess.Process) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGINT)
            return
        process.terminate()

    @staticmethod
    def _kill(process: asyncio.subprocess.Process) -> None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
            return
        process.kill()
