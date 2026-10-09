"""Independent MIT-licensed installation manager. No upstream code is vendored."""
from __future__ import annotations
import contextlib
import configparser
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import shutil
import stat
import tempfile
import urllib.request
import zipfile

VERSION = "1.4.3"
RELEASE_URL = f"https://github.com/lonewolf0622/HelixSR/releases/download/v{VERSION}/HelixSR-{VERSION}.zip"
RELEASE_SHA = "d79e849444e0ea8928c0b8df22ec21368ac08ec038417c087a3d2df7a6722119"
DLL = "amd_fidelityfx_dx12.dll"
UPSCALER = "amd_fidelityfx_upscaler_dx12.dll"
NETWORK = ("helixsr_weights.bin", "helixsr_kernels.pak")
RENDERER_LOG = "helixsr.log"
SETTINGS_FILE = "helixsr.ini"


def _plugin_version() -> str:
    try:
        return json.loads((Path(__file__).parent / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "0.0.0"


PLUGIN_VERSION = _plugin_version()

# User-facing subset of helixsr.ini. Unknown keys in an existing file are preserved.
SETTINGS_SCHEMA = (
    {"section": "Sharpening", "key": "Mode", "label": "Sharpening mode", "kind": "choice",
     "options": ["off", "game", "override"], "default": "off",
     "help": "off: no sharpening. game: follow the game's FSR sharpness, falling back to Sharpness. override: always use Sharpness."},
    {"section": "Sharpening", "key": "Sharpness", "label": "Sharpness", "kind": "float",
     "min": 0.0, "max": 1.0, "default": 0.3,
     "help": "Strength on the FidelityFX scale, 0 is none and 1 is strongest."},
    {"section": "ModelE", "key": "Network", "label": "Reconstruction network", "kind": "choice",
     "options": ["auto", "nvidia", "main", "ultraperformance"], "default": "auto",
     "help": "auto: the main network at every ratio. nvidia: NVIDIA DLSS behavior in Ultra Performance."},
    {"section": "Upscaling", "key": "NetworkResolution", "label": "Network resolution", "kind": "choice",
     "options": ["auto", "fast", "full"], "default": "auto",
     "help": "auto: balanced default. fast: lower internal resolution, a little softer. full: always full output size."},
)

class ManagerError(Exception):
    pass


def sha(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise ManagerError(f"Expected a regular file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ManagerError(f"Refusing symbolic link: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".helix-deck-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic(path, (json.dumps(value, indent=2) + "\n").encode())


def within(root: Path, path: Path) -> Path:
    # Reject symlinks in every component below the canonical game root.
    root = root.resolve()
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise ManagerError("Path escaped the selected game")
    cursor = root
    for part in parts:
        if part in ("..", "."):
            raise ManagerError("Invalid relative path")
        cursor /= part
        if cursor.is_symlink():
            raise ManagerError(f"Symbolic links are not managed: {cursor}")
    if not path.resolve().is_relative_to(root):
        raise ManagerError("Path escaped the selected game")
    return path


def safe_extract(data: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 128 * 1024 * 1024:
            raise ManagerError("Archive expands beyond the allowed size")
        seen = set()
        for info in archive.infolist():
            p = PurePosixPath(info.filename)
            if "\\" in info.filename or p.is_absolute() or ".." in p.parts or not p.parts:
                raise ManagerError("Unsafe archive path")
            if stat.S_ISLNK(info.external_attr >> 16) or info.filename in seen:
                raise ManagerError("Archive contains a link or duplicate")
            seen.add(info.filename)
        archive.extractall(destination)


def libraries(home: Path) -> list[Path]:
    roots = [home / p for p in (".local/share/Steam", ".steam/steam", ".steam/root", ".var/app/com.valvesoftware.Steam/.local/share/Steam")]
    result = set()
    for root in roots:
        paths = [root]
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            paths += [Path(s.replace("\\\\", "\\").replace('\\"', '"')) for s in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', vdf.read_text(errors="replace"))]
        for p in paths:
            if (p / "steamapps/common").is_dir():
                result.add(p.resolve())
    return sorted(result)


def fields(text: str) -> dict[str, str]:
    return {k.lower(): v.replace('\\"', '"').replace("\\\\", "\\") for k, v in re.findall(r'"([^"\\]+)"\s+"((?:\\.|[^"\\])*)"', text)}


def walk_files(root: Path):
    for folder, dirs, files in os.walk(root, followlinks=False):
        here = Path(folder)
        dirs[:] = [d for d in dirs if not (here / d).is_symlink() and d not in {".git", "node_modules"} and len(here.relative_to(root).parts) < 18]
        yield here, dirs, files


def read_tail(path: Path, lines: int = 200, max_bytes: int = 256 * 1024) -> str:
    """Last lines of a log file; empty string when there is nothing safe to read."""
    try:
        if not path.is_file() or path.is_symlink():
            return ""
        size = path.stat().st_size
        with path.open("rb") as f:
            f.seek(max(0, size - max_bytes))
            text = f.read().decode(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def running_processes(root: Path) -> list[str]:
    """Process names whose executable or working directory is inside the game root."""
    root = root.resolve()
    found = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            for link in ("exe", "cwd"):
                target = os.readlink(f"/proc/{pid}/{link}")
                if target and Path(target).is_relative_to(root):
                    with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                        found.add(f.read().strip() or pid)
                    break
        except (OSError, RuntimeError):
            continue
    return sorted(found)


class Manager:
    def __init__(self, home: Path, state: Path):
        self.home, self.state = home.resolve(), state.resolve()
        self.runtime = self.state / "runtime" / f"HelixSR-{VERSION}"
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "transactions").mkdir(exist_ok=True)

    @contextlib.contextmanager
    def locked(self):
        with (self.state / "operation.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ManagerError("Another Helix Deck operation is in progress")
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def ready(self) -> bool:
        marker = self.runtime / "helix-deck-ready.json"
        if not marker.exists():
            return False
        try:
            expected = json.loads(marker.read_text())
            return all(sha(self.runtime / n) == expected[n] for n in (DLL,) + NETWORK)
        except (OSError, ValueError, KeyError, ManagerError):
            return False

    def versions(self) -> dict:
        return {"plugin": PLUGIN_VERSION, "helixsr": VERSION, "ready": self.ready()}

    def setup_log_text(self, lines: int = 200) -> str:
        return read_tail(self.state / "setup.log", lines)

    def game_log_text(self, key: str, lines: int = 200) -> str:
        game = self.selected(key)
        return read_tail(Path(game["root"]) / RENDERER_LOG, lines)

    def is_running(self, key: str) -> dict:
        game = self.selected(key)
        processes = running_processes(Path(game["root"]))
        return {"running": bool(processes), "processes": processes[:5]}

    def _settings_dirs(self, game: dict) -> list[Path]:
        root = Path(game["root"])
        dirs = []
        for target in game["targets"]:
            parent = within(root, Path(target)).parent
            if parent not in dirs:
                dirs.append(parent)
        return dirs

    @staticmethod
    def _read_ini(path: Path) -> dict | None:
        try:
            if not path.is_file() or path.is_symlink():
                return None
        except OSError:
            return None
        parser = configparser.ConfigParser()
        parser.optionxform = str
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            return None
        return {section: dict(parser.items(section)) for section in parser.sections()}

    @staticmethod
    def _coerce(item: dict, raw: str):
        text = raw.strip()
        if item["kind"] == "choice":
            lowered = text.lower()
            return lowered if lowered in item["options"] else item["default"]
        try:
            value = float(text)
        except ValueError:
            return item["default"]
        return min(item["max"], max(item["min"], value))

    def get_settings(self, key: str) -> dict:
        game = self.selected(key)
        values: dict[str, dict[str, object]] = {}
        for item in SETTINGS_SCHEMA:
            values.setdefault(item["section"], {})[item["key"]] = item["default"]
        customized = False
        for directory in self._settings_dirs(game):
            data = self._read_ini(directory / SETTINGS_FILE)
            if not data:
                continue
            customized = True
            for item in SETTINGS_SCHEMA:
                raw = data.get(item["section"], {}).get(item["key"])
                if raw is not None:
                    values[item["section"]][item["key"]] = self._coerce(item, raw)
        return {"schema": [dict(item) for item in SETTINGS_SCHEMA],
                "values": values, "customized": customized}

    def _validate_settings(self, values) -> dict[tuple[str, str], object]:
        if not isinstance(values, dict):
            raise ManagerError("Settings must be a section-to-key mapping")
        known = {(item["section"], item["key"]): item for item in SETTINGS_SCHEMA}
        normalized = {}
        for section, entries in values.items():
            if not isinstance(entries, dict):
                raise ManagerError(f"Invalid settings for [{section}]")
            for name, raw in entries.items():
                item = known.get((section, name))
                if item is None:
                    raise ManagerError(f"Unknown setting [{section}] {name}")
                normalized[(section, name)] = self._coerce(item, str(raw))
        if not normalized:
            raise ManagerError("No settings to save")
        return normalized

    def set_settings(self, key: str, values: dict) -> str:
        with self.locked():
            game = self.selected(key)
            if not game["installed"]:
                raise ManagerError("Install HelixSR for this game before changing its settings")
            self._require_closed(game, "changing HelixSR settings")
            normalized = self._validate_settings(values)
            root = Path(game["root"])
            for directory in self._settings_dirs(game):
                path = within(root, directory / SETTINGS_FILE)
                parser = configparser.ConfigParser()
                parser.optionxform = str
                if path.exists() and not path.is_symlink():
                    try:
                        parser.read(path, encoding="utf-8")
                    except (OSError, configparser.Error) as exc:
                        raise ManagerError(f"Could not read existing settings: {exc}")
                for (section, name), value in normalized.items():
                    if not parser.has_section(section):
                        parser.add_section(section)
                    text = f"{value:.3g}" if isinstance(value, float) else str(value)
                    parser.set(section, name, text)
                buffer = io.StringIO()
                parser.write(buffer)
                atomic(path, buffer.getvalue().encode())
            return "HelixSR settings saved. They apply the next time the game launches."

    def download_release(self, cancelled: threading.Event) -> None:
        """Called under the operation lock; only executes a pinned official archive."""
        req = urllib.request.Request(RELEASE_URL, headers={"User-Agent": "HelixDeck/0.1.0"})
        chunks, size = [], 0
        with urllib.request.urlopen(req, timeout=30) as response:
            while True:
                if cancelled.is_set():
                    raise ManagerError("Setup cancelled")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 32 * 1024 * 1024:
                    raise ManagerError("Release exceeds maximum size")
                chunks.append(chunk)
        data = b"".join(chunks)
        if hashlib.sha256(data).hexdigest() != RELEASE_SHA:
            raise ManagerError("Release checksum mismatch; no code was executed")
        if cancelled.is_set():
            raise ManagerError("Setup cancelled")
        with tempfile.TemporaryDirectory(prefix="download-", dir=self.state) as temp:
            safe_extract(data, Path(temp))
            source = Path(temp) / f"HelixSR-{VERSION}"
            if not (source / "helixsr-setup.sh").is_file():
                raise ManagerError("Unexpected release layout")
            self.runtime.parent.mkdir(exist_ok=True)
            if self.runtime.exists():
                shutil.rmtree(self.runtime)
            shutil.move(str(source), self.runtime)
        (self.runtime / "setup/lib/model/launch_synth").chmod(0o755)

    def finish_setup(self):
        for name in (DLL,) + NETWORK:
            p = self.runtime / name
            if not p.is_file() or p.stat().st_size < 8:
                raise ManagerError(f"Setup did not produce {name}")
        with (self.runtime / NETWORK[1]).open("rb") as stream:
            if stream.read(8) != b"HXSRKPAK":
                raise ManagerError("Unexpected kernel file format")
        write_json(self.runtime / "helix-deck-ready.json", {n: sha(self.runtime / n) for n in (DLL,) + NETWORK})

    def scan(self) -> list[dict]:
        games = []
        seen = set()
        for lib in libraries(self.home):
            for manifest in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
                try:
                    meta = fields(manifest.read_text(errors="replace"))
                    appid, dirname = meta["appid"], meta["installdir"]
                    if not appid.isdigit() or Path(dirname).name != dirname or dirname in {".", ".."}:
                        continue
                    common = (lib / "steamapps/common").resolve()
                    root = common / dirname
                    if root.is_symlink() or not root.is_dir() or root in seen:
                        continue
                    seen.add(root)
                    dlls = []
                    for folder, _dirs, files in walk_files(root):
                        for name in files:
                            p = folder / name
                            if not p.is_symlink() and name.lower() in {DLL, UPSCALER}:
                                dlls.append(p)
                    targets = sorted(p for p in dlls if p.name.lower() == UPSCALER) or sorted(dlls)
                    key = hashlib.sha256(str(root).encode()).hexdigest()[:24]
                    record = self.state / "transactions" / key / "manifest.json"
                    installed_version = None
                    if record.exists():
                        try:
                            installed_version = json.loads(record.read_text()).get("helixsr_version")
                        except (OSError, ValueError):
                            installed_version = None
                    if targets or record.exists():
                        games.append({"id": key, "appid": appid, "name": meta.get("name", dirname),
                                      "root": str(root), "targets": [str(p) for p in targets], "installed": record.exists(),
                                      "installed_version": installed_version})
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(games, key=lambda g: g["name"].lower())

    def selected(self, key: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{24}", key):
            raise ManagerError("Invalid game selection")
        for game in self.scan():
            if game["id"] == key:
                return game
        raise ManagerError("Game not found. Rescan after mounting your Steam library.")

    def _require_closed(self, game: dict, action: str) -> None:
        processes = running_processes(Path(game["root"]))
        if processes:
            names = ", ".join(processes[:3])
            raise ManagerError(f"Close the game before {action} (running: {names}).")

    def install(self, key: str) -> str:
        with self.locked():
            game = self.selected(key)
            if game["installed"]:
                raise ManagerError("Already installed. Restore before reinstalling.")
            if not self.ready():
                raise ManagerError("Set up HelixSR first")
            root = Path(game["root"])
            self._require_closed(game, "installing HelixSR")
            changes = {}
            for target_text in game["targets"]:
                target = within(root, Path(target_text))
                backup = target.with_name(target.stem + ".original.dll")
                if backup.exists() or backup.is_symlink() or b"HelixSR" in target.read_bytes()[:4 << 20]:
                    raise ManagerError("Existing HelixSR or DLL backup found. Restore the earlier installation first.")
                changes[backup] = target.read_bytes()
                changes[target] = (self.runtime / DLL).read_bytes()
                for name in NETWORK:
                    path = within(root, target.parent / name)
                    if path.exists() or path.is_symlink():
                        raise ManagerError(f"Existing network file left unchanged: {path}")
                    changes[path] = (self.runtime / name).read_bytes()
            if not changes:
                raise ManagerError("No supported DLL remains. Scan games again.")
            for path in changes:
                within(root, path)
            self._apply(game, changes)
            return "HelixSR installed. Launch the game and select AMD FSR."

    def _apply(self, game: dict, changes: dict[Path, bytes]):
        root = Path(game["root"])
        transaction = self.state / "transactions" / game["id"]
        transaction.mkdir(exist_ok=True)
        entries = []
        for index, (path, data) in enumerate(changes.items()):
            old = sha(path)
            backup = f"{index}.backup"
            if old is not None:
                shutil.copy2(path, transaction / backup)
            entries.append({"path": str(path.relative_to(root)), "before": old, "after": hashlib.sha256(data).hexdigest(), "backup": backup})
        record = {"root": str(root), "game": game["name"], "helixsr_version": VERSION, "phase": "applying", "files": entries}
        journal = transaction / "manifest.json"
        write_json(journal, record)
        try:
            for path, data in changes.items():
                atomic(path, data)
            record["phase"] = "installed"
            write_json(journal, record)
        except Exception:
            # The on-disk journal remains recoverable if even rollback encounters an error.
            self._restore(transaction, record)
            raise

    def restore(self, key: str) -> str:
        with self.locked():
            game = self.selected(key)
            transaction = self.state / "transactions" / key
            journal = transaction / "manifest.json"
            if not journal.exists():
                raise ManagerError("No Helix Deck installation to restore")
            record = json.loads(journal.read_text())
            if record["root"] != game["root"]:
                raise ManagerError("Game location changed; refusing to restore into a different folder")
            self._require_closed(game, "restoring original files")
            self._restore(transaction, record)
            return "Original game files restored."

    def _restore(self, transaction: Path, record: dict):
        root = Path(record["root"])
        # Validate ALL files and snapshots before changing any of them.
        for item in record["files"]:
            path = within(root, root / item["path"])
            current = sha(path)
            if current not in {item["before"], item["after"]}:
                raise ManagerError(f"File changed after installation; nothing restored: {path}. Preserve your changes before restoring.")
            if item["before"] is not None and sha(transaction / item["backup"]) != item["before"]:
                raise ManagerError("Original backup is missing or damaged; nothing restored")
        record["phase"] = "restoring"
        write_json(transaction / "manifest.json", record)
        for item in reversed(record["files"]):
            path = within(root, root / item["path"])
            if item["before"] is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, (transaction / item["backup"]).read_bytes())
        shutil.rmtree(transaction)
