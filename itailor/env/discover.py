# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""
Environment discovery: what this machine can do, enumerated, cached, and
compacted for the prompt (design §2.3). No inference, no model.

Layers: OS and shell, hardware, interpreters and toolchains, package
managers, installed Python packages, developer and document tools, installed
GUI applications (registry / bundles / .desktop files), network posture,
sandbox posture. Every probe is argv-only with a short timeout; the slow
ones run in a thread pool and the whole manifest is cached at
``<project>/.itailor/env.json`` with a TTL.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request

from . import hints

PROGRAMS: dict[str, list] = {
    # interpreters
    "python": ["--version"], "pip": ["--version"], "uv": ["--version"], "conda": ["--version"],
    "Rscript": ["--version"], "node": ["--version"], "npm": ["--version"], "java": ["-version"],
    "julia": ["--version"], "go": ["version"], "cargo": ["--version"], "rustc": ["--version"],
    "dotnet": ["--version"], "ruby": ["--version"], "perl": ["--version"], "lua": ["-v"],
    "swift": ["--version"], "dart": ["--version"], "scala-cli": ["--version"], "runghc": ["--version"],
    "gcc": ["--version"], "g++": ["--version"], "clang": ["--version"], "php": ["--version"],
    "bash": ["--version"], "pwsh": ["--version"], "powershell": ["-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
    # developer tools
    "git": ["--version"], "docker": ["--version"], "apptainer": ["--version"], "singularity": ["--version"],
    "ssh": ["-V"], "rsync": ["--version"], "make": ["--version"], "cmake": ["--version"], "code": ["--version"],
    "sbatch": ["--version"], "squeue": ["--version"], "jupyter": ["--version"], "nvidia-smi": ["--version"],
    # document and media tools
    "pandoc": ["--version"], "quarto": ["--version"], "pdflatex": ["--version"], "soffice": ["--version"],
    "ffmpeg": ["-version"], "magick": ["-version"], "gs": ["--version"],
    # package managers of the OS
    "winget": ["--version"], "brew": ["--version"], "apt-get": ["--version"], "choco": ["--version"],
}
INTERPRETERS = {"python", "pip", "uv", "conda", "Rscript", "node", "npm", "java", "julia", "go", "cargo", "rustc",
                "dotnet", "ruby", "perl", "lua", "swift", "dart", "scala-cli", "runghc", "gcc", "g++", "clang",
                "php", "bash", "pwsh", "powershell"}
DEV_TOOLS = {"git", "docker", "apptainer", "singularity", "ssh", "rsync", "make", "cmake", "code", "sbatch",
             "squeue", "jupyter", "nvidia-smi"}
DOC_TOOLS = {"pandoc", "quarto", "pdflatex", "soffice", "ffmpeg", "magick", "gs"}
OS_PACKAGE_MANAGERS = {"winget", "brew", "apt-get", "choco"}
PACKAGE_MANAGERS = {"pip": "pip", "uv": "uv", "conda": "conda", "npm": "npm", "Rscript": "r", "cargo": "cargo",
                    "go": "go", "dotnet": "dotnet", "ruby": "gem", "php": "composer"}

# Python packages worth naming to the model (DAYA's KNOWN_PACKAGES, extended).
KNOWN_PYTHON_PACKAGES = ["pandas", "numpy", "scipy", "sklearn", "statsmodels", "matplotlib", "seaborn", "plotly",
                         "polars", "pyarrow", "openpyxl", "xlrd", "lxml", "tables", "xgboost", "lightgbm",
                         "networkx", "sympy", "torch", "tensorflow", "transformers", "requests", "flask",
                         "fastapi", "sqlalchemy", "pytest", "jupyter", "nbformat", "PIL", "cv2", "yaml",
                         "bs4", "docx", "pptx", "fitz", "pyspark", "dask", "numba", "psutil", "rich"]
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------
def _probe_version(name: str, args: list, timeout: float = 6.0) -> dict:
    path = shutil.which(name)
    if not path:
        return {"found": False}
    try:
        result = subprocess.run([path, *args], capture_output=True, text=True, timeout=timeout,
                                stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        text = (result.stdout or result.stderr or "").strip()
    except Exception:  # noqa: BLE001
        text = ""
    first = text.splitlines()[0].strip() if text else ""
    match = _VERSION_RE.search(first) or _VERSION_RE.search(text)
    return {"found": True, "path": path, "version": match.group(1) if match else "", "banner": first[:120]}


def _memory_bytes() -> tuple[int, int]:
    try:
        import psutil  # optional
        vm = psutil.virtual_memory()
        return int(vm.total), int(vm.available)
    except Exception:  # noqa: BLE001
        pass
    system = platform.system()
    if system == "Windows":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
        except Exception:  # noqa: BLE001
            return 0, 0
    if system == "Linux":
        total = avail = 0
        try:
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) * 1024
        except Exception:  # noqa: BLE001
            pass
        for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            try:
                with open(path) as fh:
                    raw = fh.read().strip()
                if raw.isdigit() and 0 < int(raw) < total:
                    total = int(raw)
                    avail = min(avail, total)
            except Exception:  # noqa: BLE001
                pass
        return total, avail
    if system == "Darwin":
        try:
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip())
        except Exception:  # noqa: BLE001
            return 0, 0
        return total, total // 2
    return 0, 0


def _gpus() -> list[dict]:
    gpus = []
    nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            out = subprocess.run([nvsmi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=8).stdout
            for line in out.strip().splitlines():
                name, _, mem = line.rpartition(",")
                if name:
                    gpus.append({"name": name.strip(), "vramGb": round(float(mem) / 1024, 1), "vendor": "nvidia"})
        except Exception:  # noqa: BLE001
            pass
    rocm = shutil.which("rocm-smi")
    if rocm and not gpus:
        try:
            out = subprocess.run([rocm, "--showproductname"], capture_output=True, text=True, timeout=8).stdout
            names = re.findall(r"Card series:\s*(.+)", out)
            gpus.extend({"name": n.strip(), "vramGb": None, "vendor": "amd"} for n in names)
        except Exception:  # noqa: BLE001
            pass
    if platform.system() == "Darwin" and platform.machine().lower() in ("arm64", "aarch64"):
        gpus.append({"name": "Apple Silicon GPU (unified memory, Metal)", "vramGb": None, "vendor": "apple"})
    return gpus


def _cpu_name() -> str:
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if platform.system() == "Darwin":
            return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5).stdout.strip()
        if platform.system() == "Windows":
            return os.environ.get("PROCESSOR_IDENTIFIER", "") or platform.processor()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or ""


def hardware(where: str | None = None) -> dict:
    total, avail = _memory_bytes()
    try:
        disk_free = shutil.disk_usage(where or os.getcwd()).free
    except Exception:  # noqa: BLE001
        disk_free = 0
    gpus = _gpus()
    vram = max((g.get("vramGb") or 0) for g in gpus) if gpus else 0
    return {"cpu": _cpu_name(), "cores": os.cpu_count() or 1,
            "ramTotalGb": round(total / 1024 ** 3, 1), "ramAvailableGb": round(avail / 1024 ** 3, 1),
            "diskFreeGb": round(disk_free / 1024 ** 3, 1), "gpus": gpus, "vramGb": vram,
            "arch": platform.machine()}


def _container() -> str:
    if os.environ.get("APPTAINER_CONTAINER") or os.environ.get("SINGULARITY_CONTAINER"):
        return "apptainer"
    if os.path.exists("/.dockerenv"):
        return "docker"
    try:
        with open("/proc/1/cgroup") as fh:
            if "docker" in fh.read() or "kubepods" in fh.read():
                return "docker"
    except Exception:  # noqa: BLE001
        pass
    return ""


def os_info() -> dict:
    system = platform.system()
    shell = os.environ.get("SHELL") or ("PowerShell / cmd" if system == "Windows" else "sh")
    wsl = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in platform.release().lower()
    return {"system": system, "release": platform.release(), "version": platform.version()[:60],
            "arch": platform.machine(), "shell": shell, "container": _container(), "wsl": wsl,
            "python": sys.version.split()[0], "pythonExecutable": sys.executable,
            "user": os.environ.get("USER") or os.environ.get("USERNAME") or "", "cwd": os.getcwd()}


def python_packages() -> dict:
    import importlib.util
    from importlib import metadata
    found: dict = {}
    for name in KNOWN_PYTHON_PACKAGES:
        try:
            if importlib.util.find_spec(name) is None:
                continue
        except Exception:  # noqa: BLE001
            continue
        version = ""
        for dist in (name, {"sklearn": "scikit-learn", "PIL": "pillow", "cv2": "opencv-python", "yaml": "pyyaml",
                            "bs4": "beautifulsoup4", "docx": "python-docx", "pptx": "python-pptx", "fitz": "pymupdf"}.get(name, name)):
            try:
                version = metadata.version(dist)
                break
            except Exception:  # noqa: BLE001
                continue
        found[name] = version
    try:
        total = sum(1 for _ in metadata.distributions())
    except Exception:  # noqa: BLE001
        total = 0
    return {"known": found, "installedCount": total}


def network_posture(timeout: float = 3.0) -> dict:
    proxy = {k: v for k, v in os.environ.items() if k.lower() in ("http_proxy", "https_proxy", "no_proxy")}

    def reach(url: str) -> bool:
        try:
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "itailor"})
            with urllib.request.urlopen(request, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:  # noqa: BLE001
            return False
    return {"proxy": proxy, "pypiReachable": reach("https://pypi.org/simple/"),
            "cranReachable": reach("https://cloud.r-project.org/")}


def list_apps() -> list[dict]:
    system = platform.system()
    try:
        if system == "Windows":
            from . import apps_windows
            return apps_windows.list_apps()
        if system == "Darwin":
            from . import apps_macos
            return apps_macos.list_apps()
        from . import apps_linux
        return apps_linux.list_apps()
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------
def cache_path(project: str | None) -> str:
    base = os.path.join(project, ".itailor") if project else os.path.join(os.path.expanduser("~"), ".itailor")
    return os.path.join(base, "env.json")


def build(*, include_apps: bool = True, include_network: bool = True, project: str | None = None) -> dict:
    started = time.time()
    programs: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_probe_version, name, args): name for name, args in PROGRAMS.items()}
        for future in concurrent.futures.as_completed(futures):
            programs[futures[future]] = future.result()
    found = {k: v for k, v in programs.items() if v.get("found")}
    manifest = {
        "schemaVersion": "1.0",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "os": os_info(),
        "hardware": hardware(project),
        "interpreters": {k: v for k, v in found.items() if k in INTERPRETERS},
        "packageManagers": {PACKAGE_MANAGERS[k]: v for k, v in found.items() if k in PACKAGE_MANAGERS},
        "osPackageManagers": {k: v for k, v in found.items() if k in OS_PACKAGE_MANAGERS},
        "devTools": {k: v for k, v in found.items() if k in DEV_TOOLS},
        "docTools": {k: v for k, v in found.items() if k in DOC_TOOLS},
        "pythonPackages": python_packages(),
        "apps": list_apps() if include_apps else [],
        "network": network_posture() if include_network else {},
        "sandbox": {"auditHook": True, "landlock": False},
        "probeSeconds": round(time.time() - started, 1),
    }
    return manifest


def discover(project: str | None = None, *, refresh: bool = False, ttl_hours: float = 24.0,
             include_apps: bool = True, include_network: bool = True) -> dict:
    path = cache_path(project)
    if not refresh and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                cached = json.load(handle)
            age = time.time() - os.path.getmtime(path)
            if age < ttl_hours * 3600 and cached.get("schemaVersion") == "1.0":
                cached["cached"] = True
                return cached
        except Exception:  # noqa: BLE001
            pass
    manifest = build(include_apps=include_apps, include_network=include_network, project=project)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=1)
    except OSError:
        pass
    manifest["cached"] = False
    return manifest


def summary(manifest: dict, *, max_apps: int = 25) -> str:
    """The ENVIRONMENT block for the system prompt."""
    if not manifest:
        return ""
    o, h = manifest.get("os", {}), manifest.get("hardware", {})
    lines = [f"- OS: {o.get('system')} {o.get('release')} ({o.get('arch')}); shell: {o.get('shell')}"
             + (f"; container: {o.get('container')}" if o.get("container") else "") + ("; WSL" if o.get("wsl") else ""),
             f"- Hardware: {h.get('cores')} cores, {h.get('ramTotalGb')} GB RAM ({h.get('ramAvailableGb')} GB free), "
             f"{h.get('diskFreeGb')} GB disk free"
             + (", GPU: " + ", ".join(f"{g['name']}" + (f" {g['vramGb']} GB" if g.get("vramGb") else "") for g in h.get("gpus", [])) if h.get("gpus") else ", no GPU")]

    def fmt(section: str, label: str) -> None:
        items = manifest.get(section) or {}
        if items:
            lines.append(f"- {label}: " + ", ".join(f"{k} {v.get('version') or ''}".strip() for k, v in sorted(items.items())))
    fmt("interpreters", "Interpreters and toolchains")
    fmt("packageManagers", "Package managers")
    fmt("devTools", "Developer tools")
    fmt("docTools", "Document and media tools")
    pkgs = (manifest.get("pythonPackages") or {}).get("known") or {}
    if pkgs:
        lines.append("- Python packages available: " + ", ".join(f"{k} {v}".strip() for k, v in sorted(pkgs.items()))
                     + f" (+{(manifest.get('pythonPackages') or {}).get('installedCount', 0)} distributions in total)")
    apps = manifest.get("apps") or []
    if apps:
        names = [a["name"] for a in apps[:max_apps]]
        more = f" (+{len(apps) - max_apps} more; use FindApp)" if len(apps) > max_apps else ""
        lines.append(f"- Installed applications ({len(apps)}): " + ", ".join(names) + more)
    net = manifest.get("network") or {}
    if net:
        lines.append(f"- Network: PyPI {'reachable' if net.get('pypiReachable') else 'NOT reachable'}, "
                     f"CRAN {'reachable' if net.get('cranReachable') else 'NOT reachable'}"
                     + (f", proxy configured" if net.get("proxy") else ""))
    missing = [name for name in ("Rscript", "node", "docker", "git", "pandoc", "soffice") if name not in
               {**manifest.get("interpreters", {}), **manifest.get("devTools", {}), **manifest.get("docTools", {})}]
    if missing:
        lines.append("- Not installed: " + ", ".join(missing) + " (FindProgram gives install hints)")
    return "\n".join(lines)


def find_program(name: str) -> dict:
    name = str(name or "").strip()
    if not name:
        return {"found": False, "error": "name is required"}
    probe = _probe_version(name, PROGRAMS.get(name, ["--version"]))
    if probe.get("found"):
        return {"name": name, **probe}
    for candidate in (name.lower(), name + ".exe", name.capitalize()):
        path = shutil.which(candidate)
        if path:
            return {"name": name, "found": True, "path": path, "version": ""}
    return {"name": name, "found": False, "installHint": hints.install_hint(name)}


def find_app(name: str, manifest: dict | None = None) -> dict:
    name = str(name or "").strip().lower()
    if not name:
        return {"found": False, "matches": [], "error": "name is required"}
    apps = (manifest or {}).get("apps") if manifest else None
    if apps is None:
        apps = list_apps()
    tokens = [t for t in re.split(r"\W+", name) if t]
    matches = [a for a in apps if all(t in a["name"].lower() for t in tokens)]
    if not matches:
        matches = [a for a in apps if any(t in a["name"].lower() for t in tokens if len(t) > 2)]
    for app in matches:
        app = dict(app)
    out = [{**a, "headless": hints.headless_mode(a["name"])} for a in matches[:10]]
    program = find_program(name)
    return {"query": name, "found": bool(out) or bool(program.get("found")), "matches": out,
            "program": program if program.get("found") else None,
            "installHint": "" if out or program.get("found") else hints.install_hint(name)}


def machine_for_selection(manifest: dict | None) -> dict:
    h = (manifest or {}).get("hardware") or {}
    return {"ramTotalGb": h.get("ramTotalGb") or 0, "vramGb": h.get("vramGb") or 0}
