# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""Copy the iTailor library package from ../itailor/itailor into ./itailor.

Patchbook always imports the copy that ships inside its own folder, so a
Patchbook directory can be copied to another computer and run as it is.

    python sync_itailor.py            # copy (overwrites ./itailor)
    python sync_itailor.py --check    # only report whether the copy is up to date
"""

from __future__ import annotations

import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.environ.get("ITAILOR_SOURCE") or os.path.join(os.path.dirname(HERE), "itailor", "itailor")
TARGET = os.path.join(HERE, "itailor")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def differences(a: str, b: str) -> list[str]:
    out: list[str] = []
    if not os.path.isdir(b):
        return ["(no copy yet)"]
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", "SYNCED_FROM.txt"])

    def walk(node, prefix=""):
        out.extend(prefix + n for n in node.left_only)
        out.extend(prefix + n + " (only in copy)" for n in node.right_only)
        out.extend(prefix + n + " (differs)" for n in node.diff_files)
        for name, sub in node.subdirs.items():
            walk(sub, prefix + name + "/")
    walk(cmp)
    return out


def main() -> int:
    if not os.path.isdir(SOURCE):
        if os.path.isdir(TARGET) and "--check" not in sys.argv:
            print(f"source not found ({SOURCE}); keeping the copy that is already here: {TARGET}")
            return 0
        print(f"source not found: {SOURCE} (set ITAILOR_SOURCE)")
        return 1
    if "--check" in sys.argv:
        diff = differences(SOURCE, TARGET)
        print("up to date" if not diff else "out of date:\n  " + "\n  ".join(diff))
        return 0 if not diff else 2
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET, ignore=IGNORE)
    version = ""
    try:
        with open(os.path.join(TARGET, "__init__.py"), "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("__version__"):
                    version = line.split("=", 1)[1].strip().strip("\"'")
                    break
    except OSError:
        pass
    with open(os.path.join(TARGET, "SYNCED_FROM.txt"), "w", encoding="utf-8") as handle:
        handle.write("This folder is a copy of the iTailor library package" + (f" (version {version})" if version else "") + ",\n"
                     "made by sync_itailor.py from the sibling repository ../itailor/itailor.\n"
                     "Edit the library there, not here; run sync_itailor.py to refresh this copy.\n")
    print(f"copied {SOURCE} -> {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
