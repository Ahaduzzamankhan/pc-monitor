"""Build ``PC-Monitor.exe`` with PyInstaller.

Usage::

    python build.py            # build the executable
    python build.py --clean    # remove previous build output first
    python build.py --console  # build a console variant for debugging

The default build is ``--onefile --windowed``: a single, GUI-less executable
that runs in the background with no console window - exactly how a normal
Windows background application behaves.  Startup is handled separately (and
visibly) through the standard ``HKCU\\...\\Run`` entry.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "PC-Monitor"

# Data files bundled into the executable.
HIDDEN_IMPORTS = [
    "psutil",
    "httpx",
    "httpx._client",
    "httpcore",
    "pynvml",
]

EXCLUDE_MODULES = [
    "tkinter",
    "matplotlib",
    "numpy",
    "PIL",
    "pytest",
    "IPython",
]


def clean() -> None:
    for path in (DIST, BUILD):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            print(f"removed {path}")
    spec = ROOT / f"{APP_NAME}.spec"
    if spec.exists():
        spec.unlink()
        print(f"removed {spec}")


def build(console: bool = False) -> int:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(ROOT),
        "--paths",
        str(ROOT),
    ]
    command.append("--console" if console else "--windowed")
    command.extend(["--hidden-import", name] for name in HIDDEN_IMPORTS)
    command.extend(["--exclude-module", name] for name in EXCLUDE_MODULES)
    command.append(str(SRC / "main.py"))

    print("running:", " ".join(command))
    result = subprocess.run(command, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        return result.returncode

    executable = DIST / f"{APP_NAME}.exe"
    if executable.exists():
        print(f"\nBuilt {executable} ({executable.stat().st_size / (1024 * 1024):.1f} MB)")
        print("Copy it to the target PC and run it once - it registers automatically.")
    else:  # pragma: no cover - platform dependent
        print(f"Build finished but {executable} was not produced.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PC-Monitor.exe")
    parser.add_argument("--clean", action="store_true", help="remove previous output first")
    parser.add_argument(
        "--console",
        action="store_true",
        help="build with a console window (debugging only)",
    )
    args = parser.parse_args()

    os.environ.setdefault("PYTHONPATH", str(ROOT))
    if args.clean:
        clean()
    return build(console=args.console)


if __name__ == "__main__":
    raise SystemExit(main())