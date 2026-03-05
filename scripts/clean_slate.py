#!/usr/bin/env python3
"""Repository cleanup helper for getting back to a clean baseline.

Usage examples:
  python scripts/clean_slate.py --dry-run
  python scripts/clean_slate.py --delete
  python scripts/clean_slate.py --delete --remove-actions
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Common local artifact paths created by bots/runners and browser automation.
CANDIDATE_PATHS = [
    "playwright-report",
    "test-results",
    ".playwright",
    ".cache/ms-playwright",
    "logs",
    "tmp",
    "artifacts",
    "screenshots",
    "videos",
]

# Files that should generally survive a cleanup.
PROTECTED_PATHS = {
    ".git",
    ".github/workflows",
    "data",
    "public",
    "scripts",
}


def resolve_existing_paths() -> list[Path]:
    existing = []
    for rel in CANDIDATE_PATHS:
        path = ROOT / rel
        if path.exists():
            existing.append(path)
    return existing


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def disable_github_actions() -> list[Path]:
    workflows_dir = ROOT / ".github" / "workflows"
    if not workflows_dir.exists():
        return []

    disabled = []
    for workflow in workflows_dir.glob("*.y*ml"):
        new_path = workflow.with_suffix(workflow.suffix + ".disabled")
        workflow.rename(new_path)
        disabled.append(new_path)
    return disabled


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean local artifacts to reset this repo.")
    parser.add_argument("--dry-run", action="store_true", help="Preview cleanup without deleting anything.")
    parser.add_argument("--delete", action="store_true", help="Actually delete discovered artifact paths.")
    parser.add_argument(
        "--remove-actions",
        action="store_true",
        help="Disable GitHub Actions by renaming workflow YAML files to *.disabled.",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.delete:
        parser.error("Choose either --dry-run or --delete.")

    paths = resolve_existing_paths()

    print(f"Repository root: {ROOT}")
    print("Protected paths:")
    for rel in sorted(PROTECTED_PATHS):
        print(f"  - {rel}")

    if not paths:
        print("No known automation artifacts were found.")
    else:
        print("Found cleanup candidates:")
        for path in paths:
            print(f"  - {path.relative_to(ROOT)}")

    if args.dry_run:
        print("Dry run complete; no files were changed.")
        return 0

    for path in paths:
        print(f"Deleting {path.relative_to(ROOT)}")
        remove_path(path)

    if args.remove_actions:
        disabled = disable_github_actions()
        if disabled:
            print("Disabled workflows:")
            for path in disabled:
                print(f"  - {path.relative_to(ROOT)}")
        else:
            print("No GitHub workflow files found to disable.")

    print("Cleanup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
