"""Check dynamic pywin32 dependencies inside every executable before release."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


EXECUTABLES = ("福格微信助手.exe", "wechat-agent.exe", "wechat-contact-reader.exe")
REQUIRED_MODULES = frozenset({"win32timezone"})


def verify_package(package_dir: Path) -> None:
    failures = []
    for name in EXECUTABLES:
        executable = package_dir / name
        try:
            archive = CArchiveReader(str(executable))
            modules = archive.open_embedded_archive("PYZ.pyz").toc
        except (OSError, KeyError, ValueError) as exc:
            failures.append(f"{name}: cannot inspect executable ({type(exc).__name__})")
            continue
        missing = REQUIRED_MODULES.difference(modules)
        if missing:
            failures.append(f"{name}: missing {', '.join(sorted(missing))}")
    if failures:
        raise RuntimeError("Package dependency verification failed:\n" + "\n".join(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        verify_package(args.package_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("Verified dynamic pywin32 dependencies in all three executables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
