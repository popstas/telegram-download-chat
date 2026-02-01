#!/usr/bin/env python3
"""Generate a changelog from conventional commits.

The script scans Git tags that follow semantic versioning in the form
```
v<major>.<minor>.<patch>
```
and keeps only the releases that represent a major or minor bump (patch value
set to zero). It then collects commits between consecutive tags and groups
entries by their Conventional Commit type (currently `feat` and `fix`).

Run the script without arguments to overwrite ``CHANGELOG.md`` with the latest
content. Use ``--check`` in CI to verify the committed changelog is up to date
without touching the working tree.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
COMMIT_RE = re.compile(r"^(feat|fix)(?:\(([^)]+)\))?(!)?:\s*(.+)$")
BREAKING_RE = re.compile(r"^BREAKING CHANGE:\s*(.+)$", re.MULTILINE)


class ChangelogError(RuntimeError):
    """Raised when the changelog cannot be generated."""


def run_git_command(args: Sequence[str]) -> str:
    """Run a git command and return its stdout as text."""

    try:
        output = subprocess.check_output(["git", *args], text=True)
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
    ) as exc:  # pragma: no cover - subprocess errors
        raise ChangelogError(f"Failed to run git {' '.join(args)}: {exc}") from exc
    return output.strip()


@dataclass(frozen=True)
class CommitEntry:
    """A normalized commit ready for the changelog."""

    type: str
    description: str


@dataclass(frozen=True)
class Release:
    """A release represented by a tag and its commits."""

    tag: str
    version: Tuple[int, int, int]
    date: str
    commits: Dict[str, List[CommitEntry]]

    @property
    def display_name(self) -> str:
        return f"{self.tag} - {self.date}"


def parse_semver_tag(tag: str) -> Optional[Tuple[int, int, int]]:
    match = SEMVER_TAG_RE.match(tag)
    if not match:
        return None
    version = tuple(int(part) for part in match.groups())
    return version  # type: ignore[return-value]


def discover_release_tags() -> List[Tuple[str, Tuple[int, int, int]]]:
    tags = run_git_command(["tag", "--sort=creatordate"]).splitlines()
    releases: List[Tuple[str, Tuple[int, int, int]]] = []
    for tag in tags:
        version = parse_semver_tag(tag)
        if not version:
            continue
        if version[2] != 0:
            # Skip patch releases; we only document major/minor bumps.
            continue
        releases.append((tag, version))
    return releases


def collect_commits(
    current_tag: str, previous_tag: Optional[str]
) -> Dict[str, List[CommitEntry]]:
    range_spec = (
        current_tag if previous_tag is None else f"{previous_tag}..{current_tag}"
    )
    log_format = "%H%x1f%s%x1f%b%x1e"
    raw_log = run_git_command(
        ["log", range_spec, "--pretty=format:" + log_format, "--reverse"]
    )
    commits: Dict[str, List[CommitEntry]] = {"feat": [], "fix": []}

    if not raw_log:
        return commits

    for record in raw_log.split(RECORD_SEP):
        if not record.strip():
            continue
        fields = record.split(FIELD_SEP)
        if len(fields) < 3:
            continue
        _hash, subject, body = fields[0], fields[1], fields[2]
        match = COMMIT_RE.match(subject.strip())
        if not match:
            continue
        commit_type, scope, breaking_marker, description = match.groups()
        description = description.strip()
        if scope:
            description = f"{scope}: {description}"
        breaking = bool(breaking_marker)
        breaking_details = None
        if body:
            breaking_match = BREAKING_RE.search(body)
            if breaking_match:
                breaking = True
                breaking_details = breaking_match.group(1).strip()
        if breaking:
            description = f"{description} ⚠️ BREAKING CHANGE"
            if breaking_details:
                description = f"{description} — {breaking_details}"
        commits.setdefault(commit_type, []).append(
            CommitEntry(commit_type, description)
        )

    return commits


def gather_releases() -> List[Release]:
    releases_with_versions = discover_release_tags()
    if not releases_with_versions:
        return []

    releases: List[Release] = []
    previous_tag: Optional[str] = None
    for tag, version in releases_with_versions:
        date_raw = run_git_command(["log", "-1", "--format=%cI", tag])
        date_iso = datetime.fromisoformat(date_raw).date().isoformat()
        commits = collect_commits(tag, previous_tag)
        releases.append(
            Release(tag=tag, version=version, date=date_iso, commits=commits)
        )
        previous_tag = tag

    releases.sort(key=lambda release: release.version, reverse=True)
    return releases


def gather_unreleased_commits(
    latest_tag: Optional[str],
) -> Dict[str, List[CommitEntry]]:
    """Collect commits that have not yet been released."""

    return collect_commits("HEAD", latest_tag)


def render_unreleased(commits: Dict[str, List[CommitEntry]]) -> List[str]:
    """Render the unreleased section for the changelog."""

    lines = ["## Unreleased"]
    sections = (("feat", "Features"), ("fix", "Bug Fixes"))
    has_entries = False
    for commit_type, heading in sections:
        entries = commits.get(commit_type, [])
        if not entries:
            continue
        has_entries = True
        lines.append(f"### {heading}")
        for entry in entries:
            lines.append(f"- {entry.description}")
        lines.append("")
    if has_entries:
        if lines[-1] == "":
            lines.pop()
    else:
        lines.append("No qualifying commits were found for this release.")
    return lines


def render_release(release: Release) -> List[str]:
    lines = [f"## {release.display_name}"]
    sections = (("feat", "Features"), ("fix", "Bug Fixes"))
    has_entries = False
    for commit_type, heading in sections:
        entries = release.commits.get(commit_type, [])
        if not entries:
            continue
        has_entries = True
        lines.append(f"### {heading}")
        for entry in entries:
            lines.append(f"- {entry.description}")
        lines.append("")
    if has_entries:
        if lines[-1] == "":
            lines.pop()  # Remove trailing blank line for neatness.
    else:
        lines.append("No qualifying commits were found for this release.")
    return lines


def build_changelog() -> str:
    releases = gather_releases()
    lines = [
        "# Changelog",
        "",
        "_This changelog is auto-generated by `scripts/generate_changelog.py`._",
        "",
    ]
    latest_tag = releases[0].tag if releases else None
    unreleased_commits = gather_unreleased_commits(latest_tag)

    has_unreleased_entries = any(
        unreleased_commits.get(commit_type) for commit_type in ("feat", "fix")
    )

    if not releases and not has_unreleased_entries:
        lines.append(
            "No major or minor release tags (v<major>.<minor>.0) were found in this repository."
        )
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    lines.extend(render_unreleased(unreleased_commits))
    lines.append("")

    for index, release in enumerate(releases):
        lines.extend(render_release(release))
        if index != len(releases) - 1:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Conventional Commits changelog."
    )
    parser.add_argument(
        "--output",
        default="CHANGELOG.md",
        type=Path,
        help="Path to write the changelog to (default: CHANGELOG.md)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with a non-zero status if the output file is not up to date.",
    )
    args = parser.parse_args(argv)

    try:
        changelog = build_changelog()
    except ChangelogError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.check:
        if not args.output.exists():
            print(
                f"{args.output} is missing; regenerate the changelog.", file=sys.stderr
            )
            return 1
        current = args.output.read_text(encoding="utf-8")
        if current != changelog:
            print(
                "Changelog is out of date. Run scripts/generate_changelog.py to refresh it.",
                file=sys.stderr,
            )
            return 1
        return 0

    args.output.write_text(changelog, encoding="utf-8")
    print(f"Wrote changelog to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
