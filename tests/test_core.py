import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
import core
from core import Manager, ManagerError, DLL, UPSCALER, NETWORK, VERSION, atomic, sha, safe_extract, write_json


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.steam = self.home / ".local/share/Steam"
        self.root = self.steam / "steamapps/common/Test Game"
        self.root.mkdir(parents=True)
        (self.steam / "steamapps/appmanifest_42.acf").write_text('"AppState" { "appid" "42" "name" "Test Game" "installdir" "Test Game" }')
        self.target = self.root / "Engine/Plugins/FSR/Win64" / UPSCALER
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"Original game DLL")
        self.original = self.target.read_bytes()
        self.manager = Manager(self.home, self.base / "state")
        self.manager.runtime.mkdir(parents=True)
        for name, data in [(DLL, b"HelixSR fake test DLL"), (NETWORK[0], b"fake weights"), (NETWORK[1], b"HXSRKPAK fake test kernels")]:
            (self.manager.runtime / name).write_bytes(data)
        self.manager.finish_setup()
        self.key = self.manager.scan()[0]["id"]

    def install(self):
        return self.manager.install(self.key)

    def test_install_restore_roundtrip_and_default_settings(self):
        ini = self.target.parent / "helixsr.ini"
        ini.write_bytes(b"; user setting kept intact\n")
        self.install()
        self.assertEqual(self.target.read_bytes(), (self.manager.runtime / DLL).read_bytes())
        self.assertTrue(self.manager.scan()[0]["installed"])
        self.assertEqual(self.target.with_suffix(".original.dll").read_bytes(), self.original)
        self.manager.restore(self.key)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.manager.scan()[0]["installed"])
        self.assertFalse((self.target.parent / NETWORK[0]).exists())
        self.assertEqual(ini.read_bytes(), b"; user setting kept intact\n")

    def test_missing_network_prevents_all_writes(self):
        (self.manager.runtime / NETWORK[0]).unlink()
        with self.assertRaisesRegex(ManagerError, "Set up"):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.target.with_suffix(".original.dll").exists())

    def test_existing_backup_prevents_install(self):
        self.target.with_suffix(".original.dll").write_bytes(b"someone else's backup")
        with self.assertRaisesRegex(ManagerError, "earlier installation"):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_modified_game_dll_prevents_any_restore(self):
        self.install()
        self.target.write_bytes(b"new game update")
        with self.assertRaisesRegex(ManagerError, "changed after installation"):
            self.manager.restore(self.key)
        self.assertEqual(self.target.read_bytes(), b"new game update")
        self.assertTrue((self.target.parent / NETWORK[0]).exists())
        self.assertTrue(self.target.with_suffix(".original.dll").exists())

    def test_damaged_snapshot_prevents_restore(self):
        self.install()
        journal = self.manager.state / "transactions" / self.key / "manifest.json"
        record = json.loads(journal.read_text())
        entry = next(e for e in record["files"] if e["before"] is not None)
        (journal.parent / entry["backup"]).write_bytes(b"damaged")
        with self.assertRaisesRegex(ManagerError, "backup is missing or damaged"):
            self.manager.restore(self.key)
        self.assertNotEqual(self.target.read_bytes(), self.original)

    def test_one_failed_write_rolls_back_all_changes(self):
        real_atomic = core.atomic
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path.name == NETWORK[1] and not failed:
                failed = True
                raise OSError("disk full")
            return real_atomic(path, data)
        with patch.object(core, "atomic", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.install()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.target.with_suffix(".original.dll").exists())
        self.assertFalse((self.target.parent / NETWORK[0]).exists())
        self.assertFalse(self.manager.scan()[0]["installed"])

    def test_interrupted_install_can_be_restored(self):
        real_atomic = core.atomic
        def interrupt(path, data):
            if path.name == NETWORK[1]:
                raise KeyboardInterrupt()
            return real_atomic(path, data)
        with patch.object(core, "atomic", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.install()
        self.assertTrue(self.manager.scan()[0]["installed"])
        self.manager.restore(self.key)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.target.with_suffix(".original.dll").exists())

    def test_scan_keeps_recovery_when_target_missing(self):
        self.install()
        self.target.unlink()
        self.assertTrue(self.manager.scan()[0]["installed"])
        with self.assertRaisesRegex(ManagerError, "changed after installation"):
            self.manager.restore(self.key)

    def test_symlink_dll_is_not_discovered(self):
        self.target.unlink()
        elsewhere = self.base / "outside.dll"
        elsewhere.write_bytes(b"outside")
        self.target.symlink_to(elsewhere)
        self.assertEqual(self.manager.scan(), [])
        self.assertEqual(elsewhere.read_bytes(), b"outside")

    def test_symlink_parent_cannot_redirect_restore(self):
        self.install()
        original_folder = self.target.parent
        moved = original_folder.with_name("moved")
        original_folder.rename(moved)
        original_folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ManagerError, "Symbolic links"):
            self.manager.restore(self.key)

    def test_sd_library_and_alias_are_deduplicated(self):
        sd = self.base / "SD Card"
        sdroot = sd / "steamapps/common/SD Game"
        sdroot.mkdir(parents=True)
        (sdroot / DLL).write_bytes(b"original SD DLL")
        (sd / "steamapps/appmanifest_43.acf").write_text('"appid" "43" "name" "SD Game" "installdir" "SD Game"')
        (self.steam / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path" "' + str(sd) + '" }}')
        (self.home / ".steam").mkdir()
        (self.home / ".steam/steam").symlink_to(self.steam, target_is_directory=True)
        self.assertEqual([g["name"] for g in self.manager.scan()], ["SD Game", "Test Game"])

    def test_installdir_traversal_is_ignored(self):
        (self.steam / "steamapps/appmanifest_99.acf").write_text('"appid" "99" "installdir" "../outside"')
        self.assertEqual(len(self.manager.scan()), 1)

    def test_all_game_targets_install_and_restore_together(self):
        second = self.root / "other" / UPSCALER
        second.parent.mkdir()
        second.write_bytes(b"second original")
        self.install()
        self.assertEqual(second.read_bytes(), (self.manager.runtime / DLL).read_bytes())
        self.manager.restore(self.key)
        self.assertEqual(second.read_bytes(), b"second original")
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_upscaler_dll_preferred_over_combined_dll(self):
        combined = self.root / DLL
        combined.write_bytes(b"original combined DLL")
        self.install()
        self.assertEqual(combined.read_bytes(), b"original combined DLL")

    def test_anticheat_blocks_installation(self):
        (self.root / "EasyAntiCheat").mkdir()
        (self.root / "EasyAntiCheat/BEService.exe").write_bytes(b"fixture")
        with self.assertRaisesRegex(ManagerError, "Anti-cheat detected"):
            self.install()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse(self.manager.scan()[0]["installed"])

    def test_anticheat_detection_is_case_insensitive(self):
        (self.root / "BattlEye").mkdir()
        with self.assertRaisesRegex(ManagerError, "BattlEye"):
            self.install()

    def test_install_blocked_while_game_runs(self):
        with patch.object(core, "running_processes", return_value=["game.exe"]):
            with self.assertRaisesRegex(ManagerError, "Close the game"):
                self.install()
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_restore_blocked_while_game_runs(self):
        self.install()
        with patch.object(core, "running_processes", return_value=["game.exe"]):
            with self.assertRaisesRegex(ManagerError, "Close the game"):
                self.manager.restore(self.key)
        self.assertTrue(self.manager.scan()[0]["installed"])
        self.manager.restore(self.key)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_manifest_records_installed_helixsr_version(self):
        self.install()
        journal = self.manager.state / "transactions" / self.key / "manifest.json"
        self.assertEqual(json.loads(journal.read_text())["helixsr_version"], VERSION)
        self.assertEqual(self.manager.scan()[0]["installed_version"], VERSION)

    def test_versions_reports_plugin_and_helixsr(self):
        info = self.manager.versions()
        self.assertEqual(info["helixsr"], VERSION)
        self.assertTrue(info["ready"])
        self.assertRegex(info["plugin"], r"^\d+\.\d+\.\d+$")

    def test_setup_log_returns_tail(self):
        log = self.manager.state / "setup.log"
        log.write_bytes(b"\n".join(f"line {i}".encode() for i in range(50)))
        tail = self.manager.setup_log_text(10).splitlines()
        self.assertEqual(len(tail), 10)
        self.assertEqual(tail[-1], "line 49")

    def test_setup_log_missing_is_empty(self):
        self.assertEqual(self.manager.setup_log_text(), "")

    def test_game_log_returns_renderer_tail(self):
        (self.root / "helixsr.log").write_bytes(b"a\nb\nc\n")
        self.assertEqual(self.manager.game_log_text(self.key, 2), "b\nc")

    def test_game_log_missing_is_empty(self):
        self.assertEqual(self.manager.game_log_text(self.key), "")

    def test_is_running_reports_process_names(self):
        with patch.object(core, "running_processes", return_value=["game.exe"]):
            self.assertEqual(self.manager.is_running(self.key), {"running": True, "processes": ["game.exe"]})
        with patch.object(core, "running_processes", return_value=[]):
            self.assertEqual(self.manager.is_running(self.key), {"running": False, "processes": []})

    def test_running_processes_finds_cwd(self):
        import os as _os
        before = _os.getcwd()
        try:
            _os.chdir(self.root)
            names = core.running_processes(self.root)
        finally:
            _os.chdir(before)
        self.assertTrue(names)

    def test_get_settings_returns_defaults_without_ini(self):
        result = self.manager.get_settings(self.key)
        self.assertFalse(result["customized"])
        self.assertEqual(result["values"]["Sharpening"]["Mode"], "off")
        self.assertEqual(result["values"]["Sharpening"]["Sharpness"], 0.3)
        self.assertEqual(result["values"]["ModelE"]["Network"], "auto")
        self.assertEqual(result["values"]["Upscaling"]["NetworkResolution"], "auto")
        self.assertEqual(len(result["schema"]), 4)

    def test_set_and_get_settings_roundtrip(self):
        self.install()
        message = self.manager.set_settings(self.key, {
            "Sharpening": {"Mode": "override", "Sharpness": 0.75},
            "ModelE": {"Network": "nvidia"},
            "Upscaling": {"NetworkResolution": "full"},
        })
        self.assertIn("next time the game launches", message)
        result = self.manager.get_settings(self.key)
        self.assertTrue(result["customized"])
        self.assertEqual(result["values"]["Sharpening"]["Mode"], "override")
        self.assertEqual(result["values"]["Sharpening"]["Sharpness"], 0.75)
        self.assertEqual(result["values"]["ModelE"]["Network"], "nvidia")
        self.assertEqual(result["values"]["Upscaling"]["NetworkResolution"], "full")
        ini = (self.target.parent / "helixsr.ini").read_text()
        self.assertIn("Mode = override", ini)

    def test_settings_preserve_unknown_keys(self):
        self.install()
        ini_path = self.target.parent / "helixsr.ini"
        ini_path.write_text("[Sharpening]\nMode = game\nMotionAdaptive = false\n[Custom]\nFoo = bar\n")
        self.manager.set_settings(self.key, {"Sharpening": {"Sharpness": 0.9}})
        text = ini_path.read_text()
        self.assertIn("MotionAdaptive = false", text)
        self.assertIn("Foo = bar", text)
        self.assertIn("Sharpness = 0.9", text)
        self.assertEqual(self.manager.get_settings(self.key)["values"]["Sharpening"]["Mode"], "game")

    def test_settings_written_next_to_every_target(self):
        second = self.root / "other" / UPSCALER
        second.parent.mkdir()
        second.write_bytes(b"second original")
        self.install()
        self.manager.set_settings(self.key, {"Sharpening": {"Mode": "game"}})
        self.assertTrue((self.target.parent / "helixsr.ini").is_file())
        self.assertTrue((second.parent / "helixsr.ini").is_file())

    def test_settings_reject_unknown_or_invalid(self):
        self.install()
        with self.assertRaisesRegex(ManagerError, "Unknown setting"):
            self.manager.set_settings(self.key, {"Sharpening": {"Bogus": 1}})
        with self.assertRaisesRegex(ManagerError, "No settings"):
            self.manager.set_settings(self.key, {})
        # Out-of-range sharpness is clamped to the schema, not rejected.
        self.manager.set_settings(self.key, {"Sharpening": {"Sharpness": 99}})
        self.assertEqual(self.manager.get_settings(self.key)["values"]["Sharpening"]["Sharpness"], 1.0)
        self.manager.set_settings(self.key, {"Sharpening": {"Mode": "HYPER"}})
        self.assertEqual(self.manager.get_settings(self.key)["values"]["Sharpening"]["Mode"], "off")

    def test_settings_require_installation(self):
        with self.assertRaisesRegex(ManagerError, "Install HelixSR"):
            self.manager.set_settings(self.key, {"Sharpening": {"Mode": "game"}})

    def test_settings_require_closed_game(self):
        self.install()
        with patch.object(core, "running_processes", return_value=["game.exe"]):
            with self.assertRaisesRegex(ManagerError, "Close the game"):
                self.manager.set_settings(self.key, {"Sharpening": {"Mode": "game"}})

    def test_operation_lock_prevents_overlap(self):
        with self.manager.locked():
            with self.assertRaisesRegex(ManagerError, "in progress"):
                self.install()

    def test_bad_selection_is_rejected(self):
        with self.assertRaisesRegex(ManagerError, "Invalid"):
            self.manager.install("../../oops")

    def test_download_hash_mismatch_never_extracts(self):
        response = io.BytesIO(b"not the pinned release")
        with patch("urllib.request.urlopen", return_value=response), patch.object(core, "safe_extract") as extract:
            with self.assertRaisesRegex(ManagerError, "checksum"):
                self.manager.download_release(threading.Event())
            extract.assert_not_called()

    def test_cancel_download_never_extracts(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"data")), patch.object(core, "safe_extract") as extract:
            with self.assertRaisesRegex(ManagerError, "cancelled"):
                self.manager.download_release(cancelled)
            extract.assert_not_called()

    def test_valid_pinned_download_retains_license_and_executable(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"HelixSR-{VERSION}/helixsr-setup.sh", "#!/bin/bash\n")
            z.writestr(f"HelixSR-{VERSION}/setup/lib/model/launch_synth", "fixture")
            z.writestr(f"HelixSR-{VERSION}/LICENSE", "upstream license")
        data = buf.getvalue()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(data)), patch.object(core, "RELEASE_SHA", hashlib.sha256(data).hexdigest()):
            self.manager.download_release(threading.Event())
        self.assertEqual((self.manager.runtime / "LICENSE").read_text(), "upstream license")
        self.assertTrue((self.manager.runtime / "setup/lib/model/launch_synth").stat().st_mode & 0o111)
        self.assertFalse(self.manager.ready())


class ArchiveTests(unittest.TestCase):
    def test_archive_path_traversal(self):
        for name in ["../escape", "/absolute", "prefix/../../escape", "prefix\\escape"]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr(name, "bad")
                with self.assertRaises(ManagerError):
                    safe_extract(buf.getvalue(), Path(temp))
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_archive_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                info = zipfile.ZipInfo("link")
                info.external_attr = 0o120777 << 16
                z.writestr(info, "/outside")
            with self.assertRaisesRegex(ManagerError, "link"):
                safe_extract(buf.getvalue(), Path(temp))


if __name__ == "__main__":
    unittest.main()
