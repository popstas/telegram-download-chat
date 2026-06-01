"""Guard the generated per-agent plugin files against drift.

The Claude plugin manifests, the Cursor rule, and the Codex prompt are all
generated from the canonical skill ``skills/telegram-download-chat/SKILL.md`` by
``scripts/gen_agent_plugins.py``. These tests fail if SKILL.md changed without
regenerating, and sanity-check the generated artifacts.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_agent_plugins.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_agent_plugins", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()


def test_skill_name_is_expected():
    meta, _ = GEN.parse_skill(GEN.SKILL_PATH.read_text(encoding="utf-8"))
    assert meta.get("name") == "telegram-download-chat"


def test_generated_files_are_up_to_date():
    """Every generated file on disk must match a fresh generation."""
    stale = []
    for rel, content in GEN.generate().items():
        path = REPO_ROOT / rel
        assert path.exists(), f"missing generated file: {rel}"
        if path.read_text(encoding="utf-8") != content:
            stale.append(rel)
    assert not stale, (
        "Stale agent plugin files: "
        + ", ".join(stale)
        + ". Run `python scripts/gen_agent_plugins.py`."
    )


def test_check_mode_passes():
    assert GEN.main(["--check"]) == 0


def test_claude_manifests_are_valid_json():
    plugin = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    market = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert plugin["name"] == "telegram-download-chat"
    assert "description" in plugin
    # No version field — decoupled from release bumps (see build_plugin_json).
    assert "version" not in plugin
    assert market["plugins"][0]["name"] == "telegram-download-chat"
    assert market["plugins"][0]["source"] == "./"


def test_cursor_rule_has_frontmatter_and_gen_note():
    text = (REPO_ROOT / ".cursor" / "rules" / "telegram-download-chat.mdc").read_text(
        encoding="utf-8"
    )
    assert text.startswith("---\n")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["alwaysApply"] is False
    assert meta["description"]
    assert GEN.GEN_NOTE in text
    # The skill body carried through.
    assert "telegram-download-chat" in text


def test_codex_prompt_has_frontmatter_and_arguments():
    text = (REPO_ROOT / ".codex" / "prompts" / "telegram-download-chat.md").read_text(
        encoding="utf-8"
    )
    assert text.startswith("---\n")
    meta = yaml.safe_load(text.split("---", 2)[1])
    assert meta["description"]
    assert "argument-hint" in meta
    assert "$ARGUMENTS" in text
    assert GEN.GEN_NOTE in text
