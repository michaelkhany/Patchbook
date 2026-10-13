# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Installed applications on Linux: ``.desktop`` entries, Flatpak and Snap listings."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

DESKTOP_DIRS = (
    "/usr/share/applications", "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
)


def _parse_desktop(path: str) -> dict | None:
    name = exec_ = version = ""
    no_display = False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            in_entry = False
            for line in handle:
                line = line.strip()
                if line.startswith("["):
                    in_entry = line == "[Desktop Entry]"
                    continue
                if not in_entry or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key == "Name" and not name:
                    name = value.strip()
                elif key == "Exec":
                    exec_ = value.strip()
                elif key == "Version":
                    version = value.strip()
                elif key == "NoDisplay" and value.strip().lower() == "true":
                    no_display = True
                elif key == "Type" and value.strip() != "Application":
                    return None
    except OSError:
        return None
    if not name or no_display:
        return None
    program = re.sub(r"\s%[a-zA-Z]", "", exec_).split()[0] if exec_ else ""
    exe = shutil.which(program) if program and not os.path.isabs(program) else program
    return {"name": name, "version": version, "path": path, "exe": exe or "", "source": "desktop"}


def list_apps(*, timeout: float = 10.0) -> list[dict]:
    apps: list[dict] = []
    seen: set = set()
    for directory in DESKTOP_DIRS:
        if not os.path.isdir(directory):
            continue
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".desktop"):
                continue
            info = _parse_desktop(os.path.join(directory, entry))
            if info and info["name"].lower() not in seen:
                seen.add(info["name"].lower())
                apps.append(info)
    if shutil.which("flatpak"):
        try:
            out = subprocess.run(["flatpak", "list", "--app", "--columns=name,version,application"],
                                 capture_output=True, text=True, timeout=timeout).stdout
            for line in out.splitlines():
                parts = line.split("\t")
                if parts and parts[0].strip() and parts[0].strip().lower() not in seen:
                    seen.add(parts[0].strip().lower())
                    apps.append({"name": parts[0].strip(), "version": parts[1].strip() if len(parts) > 1 else "",
                                 "path": parts[2].strip() if len(parts) > 2 else "", "exe": "flatpak run " + (parts[2].strip() if len(parts) > 2 else ""),
                                 "source": "flatpak"})
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("snap"):
        try:
            out = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=timeout).stdout
            for line in out.splitlines()[1:]:
                parts = line.split()
                if parts and parts[0].lower() not in seen:
                    seen.add(parts[0].lower())
                    apps.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else "", "path": "",
                                 "exe": shutil.which(parts[0]) or "", "source": "snap"})
        except Exception:  # noqa: BLE001
            pass
    apps.sort(key=lambda a: a["name"].lower())
    return apps
