# Development

## Structure

| File | Responsibility |
| --- | --- |
| `src/index.tsx` | Decky interface: setup, game selection, install, restore |
| `main.py` | Async Decky RPCs and cancellable setup process |
| `core.py` | Steam discovery, pinned download, transactional file changes |
| `tests/` | Temporary-library tests and mocked Decky lifecycle tests |
| `scripts/package.py` | Deterministic installable ZIP, source ZIP, and SHA-256 sums |

The UI calls Python with a discovered game ID, not arbitrary filesystem paths. The backend resolves that ID again before each operation. Setup and game modifications share an operation lock. The plugin runs as the normal Deck user and does not request Decky's root flag.

Setup downloads the complete official HelixSR archive, retaining its licenses and notices, and invokes `bash helixsr-setup.sh --yes` only after in-plugin consent. `HELIXSR_FORCE_PORTABLE=1` forces local dependencies. Both shell and child processes run in a separate process group for cancellation. We do not use `sys.executable` as a Python interpreter because Decky can be packaged with PyInstaller.

Current upstream pin:

- HelixSR: **1.4.3**
- Archive: `HelixSR-1.4.3.zip`
- SHA-256: `d79e849444e0ea8928c0b8df22ec21368ac08ec038417c087a3d2df7a6722119`
- Source: https://github.com/lonewolf0622/HelixSR/releases/tag/v1.4.3

To update the runtime, inspect the new release's licenses, scripts, dependencies, CLI, archive layout, and generated file format. Then update the version and digest together and run tests. Existing game installations are not updated automatically.

## Recovery and data

Runtime data is stored at Decky's `DECKY_PLUGIN_RUNTIME_DIR`, usually under `~/homebrew/data/`. The exact plugin directory is chosen by Decky.

- `runtime/`: complete upstream release and locally generated network.
- `dependencies/`: portable Python, shader compiler, and upstream setup cache.
- `transactions/<game-id>/manifest.json`: file journal with before/after checksums.
- `transactions/<game-id>/*.backup`: snapshots of preexisting game files.
- `setup.log`: internal setup output, without an in-plugin log viewer in v1.

Installation writes a journal before changing game files. Files are replaced atomically. A handled write failure attempts rollback; a process interruption leaves the journal available for **Restore original files**. Restore checks all current files and all original snapshots before making changes. It can resume after an interrupted restore.

If Steam updates a managed DLL, automatic restoration stops rather than reverting the update. Preserve the current game files and the transaction folder. Compare the journal's checksums to determine which files remain ours, then remove only confirmed mod files and use Steam's **Verify integrity of game files** to recover the current game version. Do not blindly copy an old backup over an updated DLL. Keep the journal until recovery is complete.

V1 does not automatically follow games moved to a different library. Restore before moving a game. Symlinked game directories and DLLs are not managed. A missing or unmounted library remains untouched.

## Validation

Run `npm test`, `npm run typecheck`, and `npm run build`. Tests do not download or execute the real HelixSR setup and do not require game files.

Before a hardware-tested release:

- [ ] Install the ZIP in a current Decky Loader release.
- [ ] Complete setup on SteamOS as the normal Deck user.
- [ ] Cancel setup during download and during compilation; retry successfully.
- [ ] Detect one internal-storage and one microSD game.
- [ ] Install in an eligible DirectX 12 game and confirm HelixSR is active in its renderer log.
- [ ] Launch the game, select FSR, and inspect image quality and frame time.
- [ ] Restore and verify the original DLL checksum and a successful game launch.
- [ ] Restart Steam/Decky and verify the managed-game state persists.

## Releases

CI builds and tests on pushes and pull requests. A version tag, such as `v0.1.0`, runs the same checks, packages the plugin, and creates a **GitHub prerelease** with the installable ZIP, source ZIP, and checksums. This keeps untested builds clearly marked.

Update the package version and README filename when cutting a new version. Tag only after reviewing the changes. The release ZIP uses the single top-level `HelixDeck/` directory expected by Decky's manual installer; it includes plugin source, tests, documentation, lockfile, workflows, and the exact LGPL library distributions with their sources. Neither archive includes node_modules, HelixSR DLLs, or NVIDIA network files. The source ZIP omits the built plugin frontend.

GitHub's `releases/latest` endpoint does not resolve prereleases. Copy the asset URL from the tagged prerelease when installing this alpha through Decky.
