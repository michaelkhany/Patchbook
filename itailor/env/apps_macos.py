# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Installed applications on macOS: ``*.app`` bundles under /Applications and ~/Applications, read from Info.plist."""

from __future__ import annotations

import os
import plistlib

APP_DIRS = ("/Applications", "/Applications/Utilities", "/System/Applications", os.path.expanduser("~/Applications"))


def _bundle_info(bundle: str) -> dict | None:
    plist = os.path.join(bundle, "Contents", "Info.plist")
    try:
        with open(plist, "rb") as handle:
            info = plistlib.load(handle)
    except Exception:  # noqa: BLE001
        info = {}
    name = str(info.get("CFBundleDisplayName") or info.get("CFBundleName") or os.path.basename(bundle)[:-4])
    executable = str(info.get("CFBundleExecutable") or "")
    exe = os.path.join(bundle, "Contents", "MacOS", executable) if executable else ""
    return {"name": name, "version": str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or ""),
            "path": bundle, "exe": exe if os.path.isfile(exe) else "", "bundleId": str(info.get("CFBundleIdentifier") or ""),
            "source": "bundle"}


def list_apps(*, max_depth: int = 2) -> list[dict]:
    if not os.path.isdir("/Applications"):
        return []
    apps: list[dict] = []
    seen: set = set()
    for root in APP_DIRS:
        if not os.path.isdir(root):
            continue
        stack = [(root, 0)]
        while stack:
            directory, depth = stack.pop()
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            for entry in entries:
                if entry.name.endswith(".app") and entry.is_dir():
                    info = _bundle_info(entry.path)
                    if info and info["name"].lower() not in seen:
                        seen.add(info["name"].lower())
                        apps.append(info)
                elif entry.is_dir() and depth < max_depth and not entry.name.startswith("."):
                    stack.append((entry.path, depth + 1))
    apps.sort(key=lambda a: a["name"].lower())
    return apps
