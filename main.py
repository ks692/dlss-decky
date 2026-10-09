"""Decky entry points. All setup and installation operations run as the user."""
import asyncio
import os
from pathlib import Path
import signal
import sys
import threading

import decky

sys.path.insert(0, str(Path(__file__).parent))
from core import Manager, ManagerError


class Plugin:
    async def _main(self):
        self.home = Path(decky.DECKY_USER_HOME)
        self.manager = Manager(self.home, Path(decky.DECKY_PLUGIN_RUNTIME_DIR))
        self.process = None
        self.task = None
        self.cancelled = threading.Event()
        self.setup_log_path = self.manager.state / "setup.log"
        self.guard = asyncio.Lock()
        self.phase = "idle"
        self.message = ""
        self.ready = False
        self.ready = await asyncio.to_thread(self.manager.ready)

    async def status(self):
        return {"ready": self.ready, "busy": self.guard.locked() or self._setting_up(),
                "setting_up": self._setting_up(), "phase": self.phase, "message": self.message}

    async def versions(self):
        return await asyncio.to_thread(self.manager.versions)

    async def setup_log(self, lines: int = 200):
        return await asyncio.to_thread(self.manager.setup_log_text, max(1, min(lines, 1000)))

    async def game_log(self, key: str, lines: int = 200):
        return await asyncio.to_thread(self.manager.game_log_text, key, max(1, min(lines, 1000)))

    async def game_running(self, key: str):
        return await asyncio.to_thread(self.manager.is_running, key)

    async def running_games(self):
        return await asyncio.to_thread(self.manager.running_game_ids)

    async def get_settings(self, key: str):
        return await asyncio.to_thread(self.manager.get_settings, key)

    async def set_settings(self, key: str, values: dict):
        async with self.guard:
            return await asyncio.to_thread(self.manager.set_settings, key, values)

    def _setting_up(self):
        return self.task is not None and not self.task.done()

    async def setup(self, consent: bool):
        async with self.guard:
            if consent is not True:
                raise ManagerError("Agree to the upstream terms before setup")
            if self._setting_up():
                raise ManagerError("Setup is already running")
            if os.geteuid() == 0:
                raise ManagerError("Plugin must run as the Deck user. Reinstall with the supplied plugin.json.")
            self.cancelled.clear()
            self.phase, self.message = "downloading", "Downloading HelixSR…"
            self.task = asyncio.create_task(self._prepare())
            return "Setup started. Keep the Deck awake."

    async def _prepare(self):
        async with self.guard:
            try:
                with self.manager.locked():
                    if await asyncio.to_thread(self.manager.ready):
                        self.ready, self.phase, self.message = True, "ready", "HelixSR is ready."
                        return
                    self.ready = False
                    await asyncio.to_thread(self.manager.download_release, self.cancelled)
                    if self.cancelled.is_set():
                        raise ManagerError("Setup cancelled")
                    self.phase, self.message = "generating", "Preparing dependencies and generating the network…"
                    # Force portable dependencies; upstream must never call a package manager.
                    env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.manager.state / "dependencies"),
                               HELIXSR_FORCE_PORTABLE="1", PYTHONUNBUFFERED="1")
                    # Avoid PyInstaller's bundled-library path leaking into external tools.
                    if "LD_LIBRARY_PATH_ORIG" in env:
                        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
                    else:
                        env.pop("LD_LIBRARY_PATH", None)
                    with self.setup_log_path.open("wb") as log:
                        self.process = await asyncio.create_subprocess_exec(
                            "bash", str(self.manager.runtime / "helixsr-setup.sh"), "--yes",
                            cwd=self.manager.runtime, env=env, stdout=log, stderr=asyncio.subprocess.STDOUT,
                            stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
                    # A cancel request may have arrived while create_subprocess_exec yielded.
                    if self.cancelled.is_set():
                        await self._stop_process()
                    code = await self.process.wait()
                    if self.cancelled.is_set():
                        raise ManagerError("Setup cancelled")
                    if code != 0:
                        detail = self._setup_error()
                        raise ManagerError(detail or f"Setup exited with code {code}. Check internet access and installed Proton, then retry.")
                    await asyncio.to_thread(self.manager.finish_setup)
                    self.ready, self.phase, self.message = True, "ready", "HelixSR is ready. Choose a game below."
            except Exception as exc:
                self.phase, self.message = "error", str(exc)
                decky.logger.error("HelixSR setup: %s", exc)
            finally:
                self.process = None

    def _setup_error(self):
        if not self.setup_log_path.exists():
            return ""
        with self.setup_log_path.open("rb") as f:
            f.seek(max(0, self.setup_log_path.stat().st_size - 8192))
            lines = f.read().decode(errors="replace").splitlines()
        for line in reversed(lines):
            if "error:" in line.lower() or "failed" in line.lower() or line.startswith("no "):
                return line[:500]
        return ""

    async def cancel_setup(self):
        self.cancelled.set()
        self.message = "Cancelling setup…"
        await self._stop_process()
        return "Cancellation requested. Wait for setup to stop before retrying."

    async def _stop_process(self):
        process = self.process
        if process is None:
            return
        # Signal the whole session, even if the shell has exited but left children.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()

    async def scan(self):
        return await asyncio.to_thread(self.manager.scan)

    async def install(self, key: str):
        if self._setting_up():
            raise ManagerError("Wait for setup to finish")
        async with self.guard:
            return await asyncio.to_thread(self.manager.install, key)

    async def restore(self, key: str):
        if self._setting_up():
            raise ManagerError("Wait for setup to finish")
        async with self.guard:
            return await asyncio.to_thread(self.manager.restore, key)

    async def _unload(self):
        self.cancelled.set()
        await self._stop_process()
        if self._setting_up():
            await self.task
        async with self.guard:
            pass  # Wait for a file transaction before unloading.

    async def _uninstall(self):
        pass  # Preserve backup journals; plugin removal does not undo game patches.
