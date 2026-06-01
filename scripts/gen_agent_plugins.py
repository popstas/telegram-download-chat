#!/usr/bin/env python3
"""Generate per-agent plugin files from the canonical Claude skill.

Single source of truth: ``skills/telegram-download-chat/SKILL.md``. This script
projects that skill into the native locations each AI coding agent
auto-discovers, so the same "drive the telegram-download-chat CLI" capability is
installable in Claude Code, Cursor, and OpenAI Codex without hand-maintaining
three copies.

Outputs (all derived from SKILL.md, do not edit by hand):
  - .claude-plugin/plugin.json        Claude Code plugin manifest (bundles skills/)
  - .claude-plugin/marketplace.json   Claude Code marketplace listing
  - .cursor/rules/telegram-download-chat.mdc   Cursor project rule
  - .codex/prompts/telegram-download-chat.md   Codex custom prompt / slash command

Usage:
  python scripts/gen_agent_plugins.py            # write the generated files
  python scripts/gen_agent_plugins.py --check    # exit 1 if any file is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "telegram-download-chat" / "SKILL.md"

GEN_NOTE = (
    "GENERATED from skills/telegram-download-chat/SKILL.md by "
    "scripts/gen_agent_plugins.py — do not edit; run the script to regenerate."
)
HTML_NOTE = f"<!-- {GEN_NOTE} -->"


def parse_skill(text: str) -> tuple:
    """Split a SKILL.md into (frontmatter dict, markdown body)."""
    if not text.startswith("---"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    _, fm, body = text.split("---", 2)
    meta = yaml.safe_load(fm) or {}
    return meta, body.lstrip("\n")


def one_line(value: str) -> str:
    """Collapse a (possibly folded) string to a single trimmed line."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def build_plugin_json(name: str, description: str) -> str:
    # No version here on purpose: it would couple this generated file to release
    # bumps and make the staleness test fail on every version bump. The plugin
    # ships alongside the package, whose version is the source of truth.
    data = {
        "name": name,
        "description": one_line(description),
        "author": {"name": "Stanislav Popov", "url": "https://github.com/popstas"},
        "homepage": "https://github.com/popstas/telegram-download-chat",
        "keywords": ["telegram", "export", "cli", "chat", "download"],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def build_marketplace_json(name: str, description: str) -> str:
    data = {
        "name": name,
        "owner": {
            "name": "popstas",
            "url": "https://github.com/popstas/telegram-download-chat",
        },
        "plugins": [
            {
                "name": name,
                "source": "./",
                "description": one_line(description),
            }
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def build_cursor_rule(description: str, body: str) -> str:
    front = (
        "---\n"
        f"description: {one_line(description)}\n"
        "globs:\n"
        "alwaysApply: false\n"
        "---\n"
    )
    return f"{front}{HTML_NOTE}\n\n{body.rstrip()}\n"


def build_codex_prompt(description: str, arg_hint: str, body: str) -> str:
    front_lines = ["---", f"description: {one_line(description)}"]
    if arg_hint:
        front_lines.append(f"argument-hint: {one_line(arg_hint)}")
    front_lines.append("---")
    front = "\n".join(front_lines) + "\n"
    intro = (
        "The target (chat id, username, or JSON export path) is provided as "
        "`$ARGUMENTS` when present; otherwise ask the user for it.\n\n"
    )
    return f"{front}{HTML_NOTE}\n\n{intro}{body.rstrip()}\n"


def generate() -> dict:
    """Return ``{relative_path: content}`` for every generated file."""
    meta, body = parse_skill(SKILL_PATH.read_text(encoding="utf-8"))
    name = meta.get("name", "telegram-download-chat")
    description = meta.get("description", "")
    arg_hint = meta.get("argument-hint", "")
    return {
        ".claude-plugin/plugin.json": build_plugin_json(name, description),
        ".claude-plugin/marketplace.json": build_marketplace_json(name, description),
        f".cursor/rules/{name}.mdc": build_cursor_rule(description, body),
        f".codex/prompts/{name}.md": build_codex_prompt(description, arg_hint, body),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any generated file is missing or stale.",
    )
    args = parser.parse_args(argv)

    files = generate()
    stale = []
    for rel, content in files.items():
        path = REPO_ROOT / rel
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != content:
            stale.append(rel)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

    if args.check:
        if stale:
            print(
                "Stale agent plugin files (run `python scripts/gen_agent_plugins.py`):",
                file=sys.stderr,
            )
            for rel in stale:
                print(f"  - {rel}", file=sys.stderr)
            return 1
        print("Agent plugin files are up to date.")
        return 0

    if stale:
        print("Wrote:")
        for rel in stale:
            print(f"  - {rel}")
    else:
        print("Agent plugin files already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
