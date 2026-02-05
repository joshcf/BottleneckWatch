"""Release script for BottleneckWatch.

Automates the release process:
1. Generates a date-based version (YYYY-MM-DD-HH) from current UTC time
2. Updates __version__ in src/__init__.py
3. Git commit + tag + push
4. Creates a zip with distributable files only
5. Creates a GitHub release via `gh release create`
6. Cleans up the temp zip

Usage:
    python release.py              # Full release
    python release.py --dry-run    # Show what would happen without doing it
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Files/directories to EXCLUDE from the release zip
EXCLUDE_PATTERNS = {
    ".git",
    ".gitignore",
    ".claude",
    "CLAUDE.md",
    "release.py",
    "venv",
    ".venv",
    "ENV",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
}

# File extensions to exclude
EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".log",
    ".zip",
}


def generate_version() -> str:
    """Generate version string from current UTC time."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d-%H")


def update_version_file(version: str, dry_run: bool = False) -> None:
    """Update __version__ in src/__init__.py."""
    init_file = PROJECT_ROOT / "src" / "__init__.py"
    content = init_file.read_text(encoding="utf-8")

    new_content = re.sub(
        r'__version__\s*=\s*"[^"]*"',
        f'__version__ = "{version}"',
        content
    )

    if dry_run:
        print(f"  Would update {init_file}")
        print(f"  __version__ = \"{version}\"")
    else:
        init_file.write_text(new_content, encoding="utf-8")
        print(f"  Updated {init_file}")


def should_include(path: Path) -> bool:
    """Check if a file/directory should be included in the release zip."""
    parts = path.relative_to(PROJECT_ROOT).parts

    # Check each path component against exclude patterns
    for part in parts:
        if part in EXCLUDE_PATTERNS:
            return False

    # Check file extension
    if path.is_file() and path.suffix in EXCLUDE_EXTENSIONS:
        return False

    return True


def create_release_zip(version: str, dry_run: bool = False) -> Path:
    """Create a zip file containing distributable files."""
    zip_name = f"BottleneckWatch-{version}.zip"
    zip_path = PROJECT_ROOT / zip_name

    if dry_run:
        print(f"  Would create {zip_path}")
        print("  Contents:")
        for root, dirs, files in os.walk(PROJECT_ROOT):
            root_path = Path(root)

            # Filter out excluded directories in-place
            dirs[:] = [d for d in dirs if should_include(root_path / d)]

            for file in files:
                file_path = root_path / file
                if should_include(file_path):
                    rel_path = file_path.relative_to(PROJECT_ROOT)
                    print(f"    {rel_path}")
        return zip_path

    print(f"  Creating {zip_path}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            root_path = Path(root)

            # Filter out excluded directories in-place
            dirs[:] = [d for d in dirs if should_include(root_path / d)]

            for file in files:
                file_path = root_path / file
                if should_include(file_path):
                    arcname = str(Path("BottleneckWatch") / file_path.relative_to(PROJECT_ROOT))
                    zf.write(file_path, arcname)

    print(f"  Created {zip_path}")
    return zip_path


def git_commit_and_tag(version: str, dry_run: bool = False) -> None:
    """Commit the version change, create a tag, and push."""
    tag = f"v{version}"

    commands = [
        (["git", "add", "src/__init__.py"], "Stage version file"),
        (["git", "commit", "-m", f"Release {tag}"], "Commit version bump"),
        (["git", "tag", tag], f"Create tag {tag}"),
        (["git", "push"], "Push commits"),
        (["git", "push", "origin", tag], f"Push tag {tag}"),
    ]

    for cmd, description in commands:
        if dry_run:
            print(f"  Would run: {' '.join(cmd)} ({description})")
        else:
            print(f"  {description}: {' '.join(cmd)}")
            result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  ERROR: {result.stderr.strip()}")
                sys.exit(1)


def create_github_release(version: str, zip_path: Path, dry_run: bool = False) -> None:
    """Create a GitHub release using the gh CLI."""
    tag = f"v{version}"

    cmd = [
        "gh", "release", "create", tag,
        str(zip_path),
        "--title", f"BottleneckWatch {tag}",
        "--notes", f"Release {tag}",
    ]

    if dry_run:
        print(f"  Would run: {' '.join(cmd)}")
    else:
        print(f"  Creating GitHub release {tag}...")
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: {result.stderr.strip()}")
            sys.exit(1)
        print(f"  Release created: {result.stdout.strip()}")


def cleanup(zip_path: Path, dry_run: bool = False) -> None:
    """Remove the temporary zip file."""
    if dry_run:
        print(f"  Would delete {zip_path}")
    else:
        if zip_path.exists():
            zip_path.unlink()
            print(f"  Cleaned up {zip_path}")


def main() -> None:
    """Run the release process."""
    parser = argparse.ArgumentParser(description="Release BottleneckWatch")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    args = parser.parse_args()

    dry_run = args.dry_run

    if dry_run:
        print("=== DRY RUN (no changes will be made) ===\n")

    version = generate_version()
    print(f"Version: {version}\n")

    # Check for clean working tree (skip in dry run)
    if not dry_run:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT, capture_output=True, text=True
        )
        if result.stdout.strip():
            print("ERROR: Working tree is not clean. Commit or stash changes first.")
            print(result.stdout)
            sys.exit(1)

    # Check that gh CLI is available
    gh_check = subprocess.run(
        ["gh", "--version"],
        capture_output=True, text=True
    )
    if gh_check.returncode != 0:
        print("ERROR: GitHub CLI (gh) is not installed or not in PATH.")
        print("Install it from: https://cli.github.com/")
        sys.exit(1)

    print("Step 1: Update version file")
    update_version_file(version, dry_run)
    print()

    print("Step 2: Git commit, tag, and push")
    git_commit_and_tag(version, dry_run)
    print()

    print("Step 3: Create release zip")
    zip_path = create_release_zip(version, dry_run)
    print()

    print("Step 4: Create GitHub release")
    create_github_release(version, zip_path, dry_run)
    print()

    print("Step 5: Cleanup")
    cleanup(zip_path, dry_run)
    print()

    if dry_run:
        print("=== DRY RUN COMPLETE ===")
    else:
        print(f"Release v{version} complete!")


if __name__ == "__main__":
    main()
