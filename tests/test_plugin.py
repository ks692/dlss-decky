"""Exercise the Decky RPC lifecycle with an isolated fake Decky module."""
import asyncio
import importlib.util
import logging
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch

from core import ManagerError


class PluginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        stub = types.SimpleNamespace(DECKY_USER_HOME=str(self.base / "home"), DECKY_PLUGIN_RUNTIME_DIR=str(self.base / "state"), logger=logging.getLogger("test-decky"))
        spec = importlib.util.spec_from_file_location("helix_deck_test_main", Path(__file__).parents[1] / "main.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"decky": stub}):
            spec.loader.exec_module(self.module)
        self.plugin = self.module.Plugin()
        await self.plugin._main()

    async def test_setup_requires_explicit_consent(self):
        with self.assertRaisesRegex(ManagerError, "terms"):
            await self.plugin.setup(False)
        self.assertIsNone(self.plugin.task)

    async def test_setup_refuses_root(self):
        with patch.object(self.module.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(ManagerError, "Deck user"):
                await self.plugin.setup(True)

    async def test_setup_calls_bash_with_portable_dependencies(self):
        fake_process = types.SimpleNamespace(wait=AsyncMock(return_value=0), pid=12345)
        create = AsyncMock(return_value=fake_process)
        with patch.object(self.module.os, "geteuid", return_value=1000), \
             patch.object(self.plugin.manager, "download_release") as download, \
             patch.object(self.plugin.manager, "finish_setup") as finish, \
             patch.object(self.module.asyncio, "create_subprocess_exec", create):
            await self.plugin.setup(True)
            await self.plugin.task
        download.assert_called_once()
        finish.assert_called_once()
        args, kwargs = create.call_args
        self.assertEqual(args[0], "bash")
        self.assertEqual(args[2], "--yes")
        self.assertEqual(kwargs["env"]["HELIXSR_FORCE_PORTABLE"], "1")
        self.assertEqual(kwargs["env"]["HOME"], str(self.base / "home"))
        self.assertTrue(kwargs["start_new_session"])
        self.assertTrue((await self.plugin.status())["ready"])

    async def test_setup_failure_is_visible_and_retryable(self):
        with patch.object(self.module.os, "geteuid", return_value=1000), \
             patch.object(self.plugin.manager, "download_release", side_effect=ManagerError("Download unavailable")):
            await self.plugin.setup(True)
            await self.plugin.task
        result = await self.plugin.status()
        self.assertEqual(result["phase"], "error")
        self.assertIn("Download unavailable", result["message"])
        self.assertFalse(result["busy"])
        self.assertFalse(result["ready"])

    async def test_cancel_during_download_never_starts_upstream(self):
        def fake_download(event):
            event.set()
        create = AsyncMock()
        with patch.object(self.module.os, "geteuid", return_value=1000), \
             patch.object(self.plugin.manager, "download_release", side_effect=fake_download), \
             patch.object(self.module.asyncio, "create_subprocess_exec", create):
            await self.plugin.setup(True)
            await self.plugin.task
        create.assert_not_called()
        self.assertIn("cancelled", (await self.plugin.status())["message"])

    async def test_rapid_duplicate_setup_is_rejected(self):
        hold = asyncio.Event()
        self.plugin.task = asyncio.create_task(hold.wait())
        with self.assertRaisesRegex(ManagerError, "already running"):
            await self.plugin.setup(True)
        hold.set()
        await self.plugin.task

    async def test_install_and_restore_rpc_take_only_game_id(self):
        with patch.object(self.plugin.manager, "install", return_value="installed") as install, \
             patch.object(self.plugin.manager, "restore", return_value="restored") as restore:
            self.assertEqual(await self.plugin.install("game-id"), "installed")
            self.assertEqual(await self.plugin.restore("game-id"), "restored")
        install.assert_called_once_with("game-id")
        restore.assert_called_once_with("game-id")
