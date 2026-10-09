# Helix Deck

Install and remove **HelixSR** for supported Steam games from **Decky Loader**, without leaving Gaming Mode.

**v0.1.0 alpha** · Open-source plugin · Steam Deck hardware testing pending

## What it does

- Sets up HelixSR once, including its required downloads and local network generation.
- Finds Steam games on internal storage and mounted microSD libraries.
- Installs HelixSR for a selected game using the upstream default settings.
- Backs up original game DLLs and restores them when you remove the mod.
- Detects changed files before restoring and keeps a journal for interrupted installations.
- Optional per-game sharpening and reconstruction settings, written to the game's `helixsr.ini`.
- Shows the installed HelixSR version, setup status, and the setup and renderer logs.
- Requires the game to be closed before changing its files, and blocks installation when known anti-cheat software is detected.

## Requirements

- Steam Deck running SteamOS, with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) installed.
- An installed Proton version in Steam's normal internal library or compatibility-tools directory.
- Internet access for the initial setup.
- A DirectX 12 game with a separate FSR 3.1 DLL.

The plugin looks for `amd_fidelityfx_upscaler_dx12.dll` or `amd_fidelityfx_dx12.dll`. Finding one makes a game an installation candidate; it does not guarantee that HelixSR works correctly in that game.

## Install the plugin

1. Open [Releases](https://github.com/ks692/dlss-decky/releases) and locate the `HelixDeck-v0.1.0.zip` asset. Use the plugin ZIP, not GitHub's automatic source archive.
2. In Gaming Mode, open **Decky → Settings → General** and enable **Developer Mode**.
3. Open **Developer → Install Plugin from ZIP**. Paste the URL below and select **Install**. Some Decky versions label this **Manual Plugin Install**.

   ```text
   https://github.com/ks692/dlss-decky/releases/download/v0.1.0/HelixDeck-v0.1.0.zip
   ```
4. Open **Helix Deck** from the Decky menu.

The plugin is distributed through this repository; it is not listed in the Decky store. No source build is required to use a release ZIP.

## Set up HelixSR

1. Open **Helix Deck** and review the upstream license links.
2. Enable **Accept upstream terms**.
3. Select **Set up HelixSR** and keep the Deck awake.
4. Wait for **HelixSR is ready**.

Setup downloads the pinned official HelixSR release and verifies its SHA-256. It uses the upstream setup script with portable dependencies in the user's Decky data directory. It does not disable SteamOS read-only mode or run a system package manager.

The network is generated on your Deck. Setup can take several minutes, depending on downloads and hardware. You can cancel and retry from the plugin. Generated network files are not uploaded or included in this repository.

## Install for a game

1. Close the game. Helix Deck also refuses to change files while the game's processes are running.
2. Select it under **Your games**. Use **Refresh games** after installing a game or mounting a library.
3. Select **Install HelixSR**. Installation is blocked when known anti-cheat software (such as Easy Anti-Cheat or BattlEye) is detected in the game folder, because modified DLLs risk an account ban. Detection cannot cover every game; check the game's policy before modding.
4. Launch normally and select **AMD FSR** in the game's graphics settings.

No launch options are required for this direct installation path. When a game has several eligible upscaler DLLs, the plugin manages them together. A dedicated upscaler DLL takes precedence over the combined FidelityFX DLL, following HelixSR's installer behavior.

## Tune HelixSR settings

For a managed game, **HelixSR settings** offers sharpening mode and strength plus the reconstruction network and its resolution. Settings are written to `helixsr.ini` next to the game's upscaler DLL, apply on the next launch, and are left untouched by restore. Keys Helix Deck does not manage are preserved.

**Diagnostics** shows the setup log and the renderer's `helixsr.log` for the selected game, and the setup panel reports the plugin and HelixSR runtime versions.

## Remove from a game

1. Close the game.
2. Select it in Helix Deck.
3. Select **Restore original files**.

The plugin restores the original DLLs and removes the network files it installed. Existing configuration files are left unchanged. Any `helixsr.log` produced by the renderer is also left in place.

Restore games **before removing the plugin or moving a game to another library**. Removing the plugin does not automatically undo its game installations. Keep its data directory until every game has been restored.

## If something goes wrong

| Problem | What to do |
| --- | --- |
| No games appear | Check that the library is mounted and the game has a separate FSR 3.1 DLL, then refresh. |
| Setup cannot find Proton | Install a Proton version through Steam in the internal library, then retry. |
| Setup fails or is cancelled | Read the short error shown in the plugin and select **Retry setup**. |
| Installation is interrupted | Reopen Helix Deck, select the managed game, and use **Restore original files** before reinstalling. |
| Restore reports changed files | Stop and preserve the changed files. The plugin refuses to overwrite game updates or other edits. Recovery details are in [DEVELOPMENT.md](DEVELOPMENT.md#recovery-and-data). |
| A previous mod or backup is detected | Remove that installation using its own installer before using Helix Deck. |
| Install is blocked: anti-cheat detected | Helix Deck refuses to patch games shipping known anti-cheat software. Do not work around this; a ban is likely. |
| Install or restore says the game is running | Close the game fully (check the process is gone) and retry. |
| Settings will not save | The game must be closed, and HelixSR must be installed for that game first. |

## Scope

V1 handles direct HelixSR installation for Steam games, with per-game sharpening and reconstruction settings, an installed-version view, setup and renderer logs, running-game detection, and blocking of known anti-cheat conflicts.

It includes no OptiScaler integration, frame generation, non-Steam launcher support, or automatic updates. Anti-cheat detection is best-effort and cannot cover every game.

## Development

Requires Node.js 20+ and Python 3.10+ on Linux.

```bash
npm ci
npm test
npm run typecheck
npm run build
npm run package
```

The installable ZIP is written to `release/HelixDeck-v0.1.0.zip`. See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, release instructions, and the Steam Deck test checklist.

Automated tests use temporary game directories and mocked setup processes. They do not prove graphics compatibility. Test setup, a real game launch, and restore on Steam Deck before promoting this alpha to a general release.

## License and credits

Helix Deck's original code is [MIT licensed](LICENSE).

[HelixSR](https://github.com/lonewolf0622/HelixSR), by **lonewolf0622**, is a separate external component. Its renderer is closed source under the HelixSR Freeware License; its setup scripts are Apache-2.0. NVIDIA components remain under NVIDIA's terms. This plugin does not change those licenses or redistribute generated NVIDIA weights or kernels.

Built using [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader), `@decky/api`, and `@decky/ui`. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Independent community project; not affiliated with or endorsed by Valve, the Decky team, NVIDIA, AMD, or the HelixSR author.
