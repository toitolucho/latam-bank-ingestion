"""DAB task entrypoint: copy S3 objects into the staging volume."""

import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# SCRIPT_DIR is <project_root>/src/python
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Make file_copy importable
sys.path.insert(0, os.path.abspath(os.path.join(SCRIPT_DIR, "..")))

from file_copy.s3_copy import run  # noqa: E402


def resolve_config_dir(raw_path: str | None) -> str:
    """Resolve configs/sources directory robustly across driver environments."""
    if raw_path:
        # 1. Direct path check (e.g. absolute path or relative to CWD)
        if os.path.isdir(raw_path):
            return os.path.abspath(raw_path)

        # 2. If path contains configs/sources or configs/..., check relative to PROJECT_ROOT
        norm = raw_path.replace("\\", "/")
        if "configs/sources" in norm:
            subpath = norm[norm.find("configs/sources"):]
            candidate = os.path.abspath(os.path.join(PROJECT_ROOT, subpath))
            if os.path.isdir(candidate):
                return candidate

        candidate = os.path.abspath(os.path.join(PROJECT_ROOT, raw_path.lstrip("/\\")))
        if os.path.isdir(candidate):
            return candidate

    # 3. Default fallback: <PROJECT_ROOT>/configs/sources
    default_dir = os.path.join(PROJECT_ROOT, "configs", "sources")
    if os.path.isdir(default_dir):
        return default_dir

    raise FileNotFoundError(
        f"Could not locate configs/sources directory (attempted: {raw_path!r}, {default_dir!r})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default=None, help="Path to sources config folder")
    args = parser.parse_args()

    config_dir = resolve_config_dir(args.config_dir)
    print(f"[run_s3_copy] Using config directory: {config_dir}")
    run(config_dir)
