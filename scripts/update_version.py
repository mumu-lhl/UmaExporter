import os
import subprocess
import re


def get_version_from_pyproject():
    try:
        with open("pyproject.toml", "r") as f:
            content = f.read()
            match = re.search(r'version\s*=\s*"(.*?)"', content)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"Error reading pyproject.toml: {e}")
    return "0.0.0"


def get_git_info():
    try:
        # Get the latest tag that matches v*
        tag = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
                stderr=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .strip()
        )

        # Get the current commit hash
        current_hash = (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode("utf-8")
            .strip()
        )

        # Get the hash of the tag
        tag_hash = (
            subprocess.check_output(["git", "rev-list", "-n", "1", tag])
            .decode("utf-8")
            .strip()
        )

        # If current commit is the tag, it's a release
        if current_hash == tag_hash:
            return None  # No hash needed for release

        return current_hash[:7]  # Short hash for commit build
    except Exception:
        # Not a git repo or no tags
        try:
            current_hash = (
                subprocess.check_output(["git", "rev-parse", "HEAD"])
                .decode("utf-8")
                .strip()
            )
            return current_hash[:7]
        except Exception:
            return None


def main():
    version = get_version_from_pyproject()
    git_hash = get_git_info()

    # Override with environment variables if present (for CI)
    github_ref = os.environ.get("GITHUB_REF", "")
    if github_ref.startswith("refs/tags/v"):
        git_hash = ""
    elif not git_hash and os.environ.get("GITHUB_SHA"):
        git_hash = os.environ.get("GITHUB_SHA")[:7]

    version_file = "src/core/version.py"
    content = f"""# This file is updated by build scripts.
# Do not edit manually.
VERSION = "{version}"
HASH = "{git_hash if git_hash else ""}"
"""

    with open(version_file, "w") as f:
        f.write(content)

    print(f"Updated {version_file}: VERSION='{version}', HASH='{git_hash}'")


if __name__ == "__main__":
    main()
