"""Create reproducible Decky/source archives without proprietary runtime payloads."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT / "package.json").read_text())["version"]
OUT = ROOT / "release"
OUT.mkdir(exist_ok=True)
RUNTIME = ["plugin.json", "package.json", "main.py", "core.py", "dist/index.js", "LICENSE", "README.md", "DEVELOPMENT.md", "THIRD_PARTY_NOTICES.md"]
SOURCE = [".gitignore", "plugin.json", "package.json", "package-lock.json", "main.py", "core.py", "rollup.config.js", "tsconfig.json", "LICENSE", "README.md", "DEVELOPMENT.md", "THIRD_PARTY_NOTICES.md"]
for folder in ["src", "tests", "scripts", ".github", "licenses"]:
    SOURCE += [str(p.relative_to(ROOT)) for p in sorted((ROOT / folder).rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
RUNTIME = SOURCE + ["dist/index.js"]
# Ship the precise LGPL distributions and their preferred TypeScript sources.
# They are generated from locked dependencies, not committed as duplicated code.
LIBRARIES = []
for package in ["@decky/api", "@decky/ui"]:
    base = ROOT / "node_modules" / package
    for path in sorted(base.rglob("*")):
        if path.is_file() and not path.is_symlink():
            LIBRARIES.append((path, "library-sources/" + package + "/" + str(path.relative_to(base))))


def archive(name, prefix, files):
    destination = OUT / name
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for relative in sorted(set(files)):
            p = ROOT / relative
            if p.suffix in {".dll", ".bin", ".pak"} or p.is_symlink():
                raise ValueError(f"Forbidden release content: {relative}")
            info = zipfile.ZipInfo(prefix + relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
        for path, relative in LIBRARIES:
            info = zipfile.ZipInfo(prefix + relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, path.read_bytes())
    print(destination)
    return destination


artifacts = [archive(f"HelixDeck-v{VERSION}.zip", "HelixDeck/", RUNTIME), archive(f"HelixDeck-v{VERSION}-source.zip", "helix-deck/", SOURCE)]
(OUT / "SHA256SUMS.txt").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in artifacts))
