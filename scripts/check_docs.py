"""Check the repository's documentation contract without third-party dependencies.

The check is intentionally small and deterministic so it can run in CI before
the API dependencies are installed. It catches stale local Markdown links and
the project entry points that are easy to forget when the layout changes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")

REQUIRED_FILES = (
    "CONTEXT.md",
    "TODO.md",
    "docs/PRD.md",
    "docs/metrics.md",
    "docs/architecture.md",
    "docs/security-audit.md",
    "deploy/docker-compose.production.yml",
    "apps/api/requirements-dev.txt",
)


def _markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if ".git" not in path.parts and ".venv" not in path.parts
    )


def _local_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip("<>").split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "tel:")):
        return None
    return (source.parent / target).resolve()


def check() -> list[str]:
    errors: list[str] = []

    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required project document or entry point: {relative}")

    for markdown in _markdown_files():
        text = markdown.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK.finditer(line):
                target = _local_target(markdown, match.group(1))
                if target is not None and not target.is_file():
                    relative_source = markdown.relative_to(ROOT).as_posix()
                    errors.append(
                        f"{relative_source}:{line_number}: local link target does not exist: "
                        f"{match.group(1)}"
                    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "[CONTEXT](CONTEXT.md)" not in readme or "[TODO](TODO.md)" not in readme:
        errors.append("README.md must link to CONTEXT.md and TODO.md")
    if "docs/security-audit.md" not in readme:
        errors.append("README.md must link to docs/security-audit.md")
    if "pip install -r requirements-dev.lock.txt" not in readme:
        errors.append("README.md must document the locked development dependency command")
    if "docker-compose.production.yml" not in readme:
        errors.append("README.md must document the production Compose overlay")

    return errors


def main() -> int:
    errors = check()
    if errors:
        print("Documentation contract failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"Documentation contract passed: {len(_markdown_files())} Markdown files checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
