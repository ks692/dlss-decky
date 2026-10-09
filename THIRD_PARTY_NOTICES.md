# Third-party notices

The original Helix Deck source is MIT licensed. Dependencies retain their licenses.

- `@decky/api` and `@decky/ui`: Decky contributors, LGPL-2.1. License copies are in `licenses/`. The release archives also include the exact npm distributions (with their TypeScript sources) in `library-sources/`.
- `tslib`: Microsoft Corporation, 0BSD. License copy is in `licenses/`.
- React is supplied by the Decky/Steam host at runtime and is not distributed as a separate React build in this ZIP.

Build tools and their transitive dependencies are recorded in `package-lock.json`; they are not shipped as node_modules in the plugin ZIP.

## External components downloaded at setup time

HelixSR is downloaded as the complete, unmodified official release, with its original licenses and notices retained locally. It is not bundled in the plugin ZIP or source archive.

- HelixSR renderer: HelixSR Freeware License, copyright 2026 lonewolf0622.
- HelixSR setup scripts and setup folder: Apache License 2.0, with third-party exceptions as described upstream.
- NVIDIA DLSS and derived network files: NVIDIA's terms. Generated weights and kernels stay on the user's machine and must not be redistributed.
- Portable Python, NumPy, Microsoft DirectX Shader Compiler, and other upstream dependencies retain their own licenses.

Authoritative upstream notices: https://github.com/lonewolf0622/HelixSR/blob/main/THIRD_PARTY_NOTICES.md

## Rebuilding with modified Decky libraries

The plugin source and build configuration are included in both release ZIPs.
Run `npm ci`, then replace the corresponding `node_modules/@decky/api` or
`node_modules/@decky/ui` distribution with your modified library build before
running `npm run build`. The matching unmodified sources and JavaScript builds
are included in `library-sources/`; the normal lockfile also identifies the
exact npm versions and integrity digests. You may modify these libraries and
rebuild/relink the plugin; no signing key or publisher approval is required.
The original plugin's MIT license does not restrict reverse engineering for
debugging modifications to the LGPL libraries. The libraries retain LGPL-2.1.
