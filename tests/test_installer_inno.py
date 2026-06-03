"""Sanity checks for the Inno Setup wrapper.

Inno Setup only compiles on Windows, so these tests assert the script's
*content* invariants (mirroring ``test_package_embed``'s build-script check)
rather than running ISCC. The most important invariant: the app installs into a
user-writable location so the in-app self-update can swap ``app\\`` without
elevation.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _iss() -> str:
    return (_ROOT / "installer.iss").read_text(encoding="utf-8")


def _installer_ps() -> str:
    return (_ROOT / "build_windows_installer.ps1").read_text(encoding="utf-8")


def _build_yml() -> str:
    return (_ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")


def test_iss_installs_per_user_writable_for_self_update():
    text = _iss()
    assert "[Setup]" in text
    # Per-user, no-elevation install so app_updater can rewrite app\ in place.
    assert "PrivilegesRequired=lowest" in text
    assert "{localappdata}" in text  # writable DefaultDirName
    assert "{autopf}" not in text  # NOT Program Files (would break self-update)
    assert "AppId=" in text


def test_iss_bundles_two_part_tree_and_versioned_output():
    text = _iss()
    assert "[Files]" in text
    assert "dist\\telegram-download-chat\\*" in text
    assert "recursesubdirs" in text
    # Output name carries the version passed via /dMyAppVersion.
    assert "{#MyAppVersion}" in text
    assert "OutputBaseFilename=telegram-download-chat-v{#MyAppVersion}-setup" in text


def test_iss_shortcut_launches_gui_with_working_dir_at_root():
    text = _iss()
    assert "[Icons]" in text
    assert "-m telegram_download_chat gui" in text
    # WorkingDir must be the install root, not app\, so the app/ dir is not the
    # process cwd (which would block the rename swap during self-update).
    assert 'WorkingDir: "{app}"' in text


def test_installer_ps_runs_embed_build_then_iscc():
    text = _installer_ps()
    assert "build_windows_embed.ps1" in text
    assert "ISCC" in text or "iscc" in text
    assert "installer.iss" in text
    assert "/dMyAppVersion=" in text
    # Version is taken from the embed build's app\version.txt.
    assert "version.txt" in text


def test_release_workflow_builds_and_publishes_installer():
    text = _build_yml()
    # Inno Setup must be available on the runner.
    assert "innosetup" in text.lower()
    # The installer build script is invoked.
    assert "build_windows_installer.ps1" in text
    # The setup.exe (versioned) and the in-app update zip are released assets.
    assert "telegram-download-chat-v" in text and "-setup.exe" in text
    assert "app-" in text and ".zip" in text

