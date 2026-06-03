# Two-part Windows build: immutable embeddable-Python base + tiny app update (Variant A)

Date: 2026-06-04
Branch: `tdc-backlog-comments-citations-reactions-gui` (extends PR #84;
replaces the onedir+manifest portable build added earlier in this branch).

## Goal

Split the Windows distribution so updates are tiny. Replace the PyInstaller
onedir build (where our code and all deps are fused into one always-changing
PYZ) and the `manifest.json` + `diff_manifests` incremental scheme with a
simpler two-part layout:

- **Base (`runtime/`)** — installed once, immutable until a Python/dependency
  bump: the official Windows **embeddable CPython** plus **all** third-party
  packages (PySide6/Qt, telethon, jinja2, reportlab, Pillow, …) and a launcher.
- **App (`app/`)** — replaced wholesale on every release: only our
  `telegram_download_chat` source package.

Because the app part is ~0.5–1 MB, updates just download `app-<version>.zip`
and replace the `app/` directory — **no manifest, no per-file diff**. The diff
machinery is removed.

## Install layout

```
telegram-download-chat/
├─ runtime/                         ← Base (one-time)
│  ├─ python/                       embeddable CPython + pythonXY._pth
│  ├─ site-packages/               all third-party deps (pip --target)
│  ├─ telegram-download-chat.cmd    CLI launcher (console)
│  └─ telegram-download-chat-gui.vbs GUI launcher (no console)
└─ app/                             ← App (updated wholesale)
   ├─ telegram_download_chat/       our source package (+ generated _version.py)
   └─ version.txt                   installed app version
```

`python/pythonXY._pth` lists (relative to `runtime/python/`):
```
pythonXY.zip
.
..\site-packages
..\..\app
import site
```
so `import telegram_download_chat` resolves from `app/` and its deps from
`runtime/site-packages/` with no `sys.path` hacks.

Launchers run the existing entry points:
- CLI: `runtime\python\python.exe -m telegram_download_chat %*`
- GUI: `runtime\python\pythonw.exe -m telegram_download_chat gui` (via the
  `.vbs` so no console window flashes).

## Cross-platform packager — `scripts/package_embed.py`

Mirrors the (removed) `package_portable.py` pattern: pure-Python, no Windows
APIs, so it is fully unit-testable on any OS. `build_windows_embed.ps1` calls it
to produce the app zip; the same `apply_app_update` is what an updater (or the
GUI "update" action) calls to install a downloaded app zip.

API:

- `build_app_zip(src_pkg_dir, output_dir, version) -> Path`
  Zip the `telegram_download_chat` package (from `src_pkg_dir`) into
  `output_dir/app-<version>.zip`. The zip's top level is the app *contents*:
  `telegram_download_chat/...`, a generated `telegram_download_chat/_version.py`
  (so `__version__` resolves at runtime without setuptools-scm), and
  `version.txt`. `__pycache__`/`.pyc` are excluded.

- `read_installed_version(install_dir) -> Optional[str]`
  Read `install_dir/app/version.txt`; `None` if absent.

- `apply_app_update(zip_path, install_dir, *, expected_sha256=None) -> str`
  Atomically replace `install_dir/app` from `zip_path`. Steps:
  1. If `expected_sha256` is given, verify the zip hash first (mismatch →
     `ValueError`, install untouched).
  2. Extract to a temp dir next to `app/`.
  3. Validate the payload has `telegram_download_chat/__init__.py` and
     `version.txt` (invalid → raise, install untouched).
  4. Swap: rename current `app` → `app.bak-<rand>`, move new tree → `app`,
     remove the backup. On any failure during the swap, restore the backup so
     the previous install is never left broken.
  Returns the new version string.

- `compute_file_hash(path) -> str` — SHA-256 (used for optional verification).

CLI:
- `python scripts/package_embed.py build-app <src_pkg_dir> --version V [--output-dir D]`
- `python scripts/package_embed.py apply <zip> <install_dir> [--sha256 HEX]`

## Build script — `build_windows_embed.ps1`

1. Download the embeddable CPython zip matching the project's Python minor
   version; extract into `dist/telegram-download-chat/runtime/python/`.
2. Bootstrap pip (`get-pip.py`) and `pip install --target runtime/site-packages`
   the project and its runtime + GUI deps.
3. Write `pythonXY._pth` with the paths above.
4. Emit the CLI `.cmd` and GUI `.vbs` launchers into `runtime/`.
5. Resolve the version (CI `SETUPTOOLS_SCM_PRETEND_VERSION`, else installed
   package) and call `package_embed.py build-app src/telegram_download_chat
   --version <v> --output-dir dist` to produce `app-<v>.zip`; also unzip it into
   `dist/telegram-download-chat/app/` for the full first-install tree.
6. Zip the whole `dist/telegram-download-chat/` as the one-time base installer
   `telegram-download-chat-base-<v>.zip`.

Outputs:
- `telegram-download-chat-base-<v>.zip` — full first install (base + app).
- `app-<v>.zip` — the tiny per-release update.

## Update flow (end-user)

First install: download + extract the base zip, run the launcher.
Update: download `app-<v>.zip`, call `apply_app_update` (atomic swap of `app/`).
Base is re-downloaded only when Python or a dependency is bumped.

## Testing

Unit (`pytest`, cross-platform):
- `build_app_zip`: zip name, contains `telegram_download_chat/__init__.py`,
  generated `_version.py` carrying the version, `version.txt`; excludes `.pyc`.
- `read_installed_version`: reads `version.txt`; `None` when missing.
- `apply_app_update`: replaces `app/`, returns version, new files present / stale
  files gone; sets `version.txt`.
- `apply_app_update` rollback: bad sha256 and invalid payload both raise and
  leave the existing `app/` intact.
- Build-script sanity: `build_windows_embed.ps1` references embeddable python,
  `pip install --target`, the `._pth`, and `package_embed.py build-app`.

E2E (manual, Windows-only — cannot run in CI/Linux): build the base, install,
then build a new app zip and confirm `apply` swaps it and the app still launches.
Documented as a manual step.

## Out of scope / honest caveats

- The embeddable Python **minor version is pinned** by the base; any `.pyd` in
  the deps is ABI-locked to it, so a Python bump (3.12→3.13) requires a new base.
- The base is "rarely changing", not eternal: a dependency bump (Qt, Pillow,
  telethon, …) means a new base download, same as first install.
- Wiring the GUI "Software Update" button to fetch+`apply_app_update` is a
  Windows-runtime follow-up; this change ships the packager, build script, and a
  usable `apply` CLI, plus removes the old onedir/manifest mechanism.
- Launcher executables are unsigned (same SmartScreen note as before).
