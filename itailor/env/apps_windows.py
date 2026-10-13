# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Installed applications on Windows, from the registry (no model, no guessing):

* the Uninstall keys under HKLM and HKCU, both 32- and 64-bit views - what
  "Apps & features" shows - with DisplayName, DisplayVersion, InstallLocation
  and the executable named by DisplayIcon;
* App Paths, which maps ``name.exe`` to a full path for programs that are not
  on PATH;
* ``winget list`` as a slower, optional complement (off by default).
"""

from __future__ import annotations

import os
import re
import subprocess

_UNINSTALL_PATHS = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)
_APP_PATHS = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
)
_NOISE_RE = re.compile(r"^(KB\d+|Update for|Security Update|Hotfix|Microsoft Visual C\+\+ \d{4}.*Redistributable|"
                       r"Windows SDK|Microsoft \.NET.*(Runtime|Targeting)|vs_|VS Community|Microsoft Edge WebView)", re.I)


def _exe_from_icon(icon: str) -> str:
    text = str(icon or "").strip().strip('"')
    if not text:
        return ""
    text = re.sub(r",\s*-?\d+$", "", text).strip().strip('"')
    return text if text.lower().endswith(".exe") and os.path.isfile(text) else ""


def _read_uninstall(winreg, hive, path: str, out: list, seen: set) -> None:
    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    try:
        key = winreg.OpenKey(root, path)
    except OSError:
        return
    with key:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(key, sub) as item:
                    def val(name):
                        try:
                            value, _ = winreg.QueryValueEx(item, name)
                            return str(value or "").strip()
                        except OSError:
                            return ""
                    name = val("DisplayName")
                    if not name or _NOISE_RE.search(name):
                        continue
                    try:
                        system_component, _ = winreg.QueryValueEx(item, "SystemComponent")
                        if int(system_component or 0) == 1:
                            continue
                    except OSError:
                        pass
                    ident = name.lower()
                    if ident in seen:
                        continue
                    seen.add(ident)
                    out.append({"name": name, "version": val("DisplayVersion"),
                                "path": val("InstallLocation"), "exe": _exe_from_icon(val("DisplayIcon")),
                                "publisher": val("Publisher"), "source": f"registry:{hive}"})
            except OSError:
                continue


def _read_app_paths(winreg, hive, path: str) -> dict:
    root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
    found: dict = {}
    try:
        key = winreg.OpenKey(root, path)
    except OSError:
        return found
    with key:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(key, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(key, sub) as item:
                    value, _ = winreg.QueryValueEx(item, None)
                    exe = str(value or "").strip().strip('"')
                    if exe and os.path.isfile(exe):
                        found[sub.lower()] = exe
            except OSError:
                continue
    return found


def list_apps(*, winget: bool = False, timeout: float = 20.0) -> list[dict]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    apps: list[dict] = []
    seen: set = set()
    for hive, path in _UNINSTALL_PATHS:
        _read_uninstall(winreg, hive, path, apps, seen)
    app_paths: dict = {}
    for hive, path in _APP_PATHS:
        app_paths.update(_read_app_paths(winreg, hive, path))
    for exe_name, exe in app_paths.items():
        base = exe_name[:-4] if exe_name.endswith(".exe") else exe_name
        matched = False
        for app in apps:
            if not app.get("exe") and base and base in app["name"].lower().replace(" ", ""):
                app["exe"] = exe
                matched = True
        if not matched and base not in seen:
            seen.add(base)
            apps.append({"name": base, "version": "", "path": os.path.dirname(exe), "exe": exe,
                         "publisher": "", "source": "registry:AppPaths"})
    if winget:
        try:
            result = subprocess.run(["winget", "list", "--disable-interactivity", "--accept-source-agreements"],
                                    capture_output=True, text=True, timeout=timeout,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in (result.stdout or "").splitlines()[2:]:
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts) >= 2 and parts[0].lower() not in seen:
                    seen.add(parts[0].lower())
                    apps.append({"name": parts[0], "version": parts[2] if len(parts) > 2 else "", "path": "",
                                 "exe": "", "publisher": "", "source": "winget"})
        except Exception:  # noqa: BLE001
            pass
    apps.sort(key=lambda a: a["name"].lower())
    return apps
