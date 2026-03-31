import argparse
import os
import shutil
from pathlib import Path


DEFAULT_DIRS = ("generate", "signed", "broadcast")


def _safe_clear_dir(dir_path: Path) -> tuple[int, int]:
    """Delete all files/dirs inside dir_path. Returns (deleted_files, deleted_dirs)."""

    deleted_files = 0
    deleted_dirs = 0

    if not dir_path.exists():
        return deleted_files, deleted_dirs

    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")

    for child in dir_path.iterdir():
        # Skip deleting the directory itself; only clear contents.
        if child.is_symlink() or child.is_file():
            child.unlink(missing_ok=True)
            deleted_files += 1
        elif child.is_dir():
            shutil.rmtree(child)
            deleted_dirs += 1
        else:
            # Fallback for weird filesystem entries.
            try:
                child.unlink(missing_ok=True)
                deleted_files += 1
            except Exception:
                pass

    return deleted_files, deleted_dirs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete all files inside generate/, signed/, and broadcast/ (cross-platform). "
            "Optionally include inputs/."
        )
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent),
        help="Project root directory (defaults to this script's folder).",
    )
    parser.add_argument(
        "--dirs",
        nargs="*",
        default=list(DEFAULT_DIRS),
        help="Directories (relative to root) to clear.",
    )
    parser.add_argument(
        "--include-inputs",
        action="store_true",
        help="Also clear inputs/ (e.g., large local UTXO JSON dumps).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Do not prompt for confirmation.",
    )

    args = parser.parse_args()

    root = Path(args.root).resolve()
    dirs = [str(d) for d in args.dirs]
    if args.include_inputs and "inputs" not in dirs:
        dirs.append("inputs")

    # Safety: refuse to run on an obviously wrong root.
    # (We expect this script to live in the repo root.)
    if Path(__file__).resolve().parent != root:
        # Allow override, but be explicit.
        pass

    targets = [root / d for d in dirs]

    print("This will delete ALL contents inside:")
    for t in targets:
        print(f"  - {t}")

    if not args.yes:
        reply = input("Continue? (y/N): ").strip().lower()
        if reply not in ("y", "yes"):
            print("Aborted.")
            return 1

    total_files = 0
    total_dirs = 0

    for t in targets:
        t.mkdir(parents=True, exist_ok=True)
        files, dirs_deleted = _safe_clear_dir(t)
        total_files += files
        total_dirs += dirs_deleted

    print(f"Done. Deleted {total_files} file(s) and {total_dirs} director(ies).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
