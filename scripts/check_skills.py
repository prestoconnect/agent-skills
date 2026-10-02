#!/usr/bin/env python3
"""Validate the skills in this repository.

Checks every SKILL.md frontmatter, that each skill only references files inside its own folder and that those
files exist, and that each language reference pins the latest released SDK version.

Usage: python scripts/check_skills.py [--offline]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "plugins" / "presto-pay" / "skills"

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

SDK_REPOS = {
    "go.md": "https://github.com/prestoconnect/presto-pay-sdk-go",
    "java.md": "https://github.com/prestoconnect/presto-pay-sdk-java",
    "js.md": "https://github.com/prestoconnect/presto-pay-sdk-js",
    "php.md": "https://github.com/prestoconnect/presto-pay-sdk-php",
    "python.md": "https://github.com/prestoconnect/presto-pay-sdk-python",
}
PINNED_VERSION = re.compile(r"Written against \*\*[^*]*?v?(\d+\.\d+\.\d+)\*\*")
REFERENCED_PATH = re.compile(r"`(references/[A-Za-z0-9_./-]+\.md)`")
MARKDOWN_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def parse_frontmatter(text: str) -> dict[str, str] | None:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def check_frontmatter(skill_dir: Path, errors: list[str]) -> None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        errors.append(f"{skill_dir.name}: missing SKILL.md")
        return
    fields = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    if fields is None:
        errors.append(f"{skill_file}: missing YAML frontmatter")
        return
    name = fields.get("name", "")
    description = fields.get("description", "")
    if name != skill_dir.name:
        errors.append(f"{skill_file}: name '{name}' doesn't match folder '{skill_dir.name}'")
    if not NAME_PATTERN.match(name) or len(name) > MAX_NAME_LENGTH:
        errors.append(f"{skill_file}: name '{name}' must be lowercase words joined by hyphens, at most 64 characters")
    if not description:
        errors.append(f"{skill_file}: missing description")
    elif len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(f"{skill_file}: description is {len(description)} characters, limit {MAX_DESCRIPTION_LENGTH}")
    if "<" in description or ">" in description:
        errors.append(f"{skill_file}: description must not contain angle brackets")


def check_references(skill_dir: Path, errors: list[str]) -> None:
    for markdown in skill_dir.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for path in REFERENCED_PATH.findall(text):
            if not (skill_dir / path).is_file():
                errors.append(f"{markdown.relative_to(ROOT)}: references missing file {path}")
        for link in MARKDOWN_LINK.findall(text):
            target = (markdown.parent / link.split("#", 1)[0]).resolve()
            if not target.is_relative_to(skill_dir.resolve()):
                errors.append(f"{markdown.relative_to(ROOT)}: link {link} leaves the skill folder")
            elif not target.exists():
                errors.append(f"{markdown.relative_to(ROOT)}: broken link {link}")


def latest_release(repo_url: str) -> str | None:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", repo_url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return None
    versions = re.findall(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$", result.stdout, re.MULTILINE)
    if not versions:
        return None
    return ".".join(map(str, max(tuple(map(int, v)) for v in versions)))


def check_versions(skill_dir: Path, errors: list[str], offline: bool) -> None:
    lang_dir = skill_dir / "references" / "lang"
    if not lang_dir.is_dir():
        return
    for lang_file in sorted(lang_dir.glob("*.md")):
        match = PINNED_VERSION.search(lang_file.read_text(encoding="utf-8"))
        if not match:
            errors.append(f"{lang_file.relative_to(ROOT)}: no 'Written against **<version>**' line")
            continue
        pinned = match.group(1)
        repo_url = SDK_REPOS.get(lang_file.name)
        if offline or repo_url is None:
            continue
        latest = latest_release(repo_url)
        if latest is None:
            print(f"warning: couldn't read release tags from {repo_url}", file=sys.stderr)
        elif latest != pinned:
            errors.append(f"{lang_file.relative_to(ROOT)}: pins {pinned}, latest release is {latest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="skip comparing pinned versions with GitHub tags")
    args = parser.parse_args()

    errors: list[str] = []
    skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
    if not skill_dirs:
        errors.append(f"no skills found under {SKILLS_DIR}")
    for skill_dir in skill_dirs:
        check_frontmatter(skill_dir, errors)
        check_references(skill_dir, errors)
        check_versions(skill_dir, errors, args.offline)

    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"ok: {len(skill_dirs)} skill(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
