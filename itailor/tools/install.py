# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Missing-dependency detection and installation for every package manager a
runnable language may need - deterministic, before any model is asked.

"No module named 'sklearn'" becomes ``pip install scikit-learn``; "Cannot
find module 'lodash'" becomes ``npm install lodash``. Import names are
mapped to the distribution that provides them, names that are not plain
packages are rejected, and stdlib modules are never "installed".
"""

from __future__ import annotations

import os
import re
import sys

from ..events import CancelToken
from . import shell

IMPORT_TO_PIP = {
    "sklearn": "scikit-learn", "cv2": "opencv-python-headless", "PIL": "pillow", "yaml": "pyyaml",
    "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "sm": "statsmodels",
    "statsmodels.api": "statsmodels", "skimage": "scikit-image", "OpenSSL": "pyopenssl", "attr": "attrs",
    "serial": "pyserial", "Bio": "biopython", "mpl_toolkits": "matplotlib", "matplotlib.pyplot": "matplotlib",
    "google.protobuf": "protobuf", "pkg_resources": "setuptools", "dotenv": "python-dotenv", "jwt": "pyjwt",
    "git": "gitpython", "fitz": "pymupdf", "docx": "python-docx", "pptx": "python-pptx", "magic": "python-magic",
    "wx": "wxpython", "Crypto": "pycryptodome", "nacl": "pynacl", "psycopg2": "psycopg2-binary",
    "MySQLdb": "mysqlclient", "tf": "tensorflow", "gi": "pygobject", "ldap": "python-ldap", "zmq": "pyzmq",
    "websocket": "websocket-client", "xgboost": "xgboost", "lightgbm": "lightgbm", "tables": "tables",
}

PYTHON_STDLIB = set(getattr(sys, "stdlib_module_names", ()) or ()) | {
    "abc", "argparse", "asyncio", "base64", "collections", "csv", "ctypes", "dataclasses", "datetime",
    "decimal", "enum", "functools", "glob", "hashlib", "http", "importlib", "io", "itertools", "json",
    "logging", "math", "multiprocessing", "os", "pathlib", "pickle", "platform", "queue", "random", "re",
    "shutil", "socket", "sqlite3", "statistics", "string", "subprocess", "sys", "tempfile", "threading",
    "time", "tkinter", "typing", "unittest", "urllib", "uuid", "xml", "zipfile", "zoneinfo", "tomllib",
}
NODE_BUILTINS = set(("assert async_hooks buffer child_process cluster console constants crypto dgram "
                     "diagnostics_channel dns domain events fs http http2 https inspector module net os path "
                     "perf_hooks process punycode querystring readline repl stream string_decoder timers tls "
                     "trace_events tty url util v8 vm wasi worker_threads zlib test").split())

INSTALL_DENYLIST = {"os", "sys", "subprocess", "socket", "pip", "setuptools", "wheel", "paramiko",
                    "requests-oauthlib", "cryptography-vectors"}
SAFE_PACKAGE_RE = re.compile(r"^[@A-Za-z0-9][A-Za-z0-9._\-/]*(\[[A-Za-z0-9,_-]+\])?((==|>=|<=|~=|!=|>|<|@)[A-Za-z0-9._*+\-^~]+)?$")

PATTERNS = (
    ("pip", re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]")),
    ("npm", re.compile(r"Cannot find (?:module|package) '((?:@[^/']+/)?[^'/]+)(?:/[^']*)?'")),
    ("r", re.compile(r"there is no package called ['‘\"]([A-Za-z0-9_.]+)['’\"]")),
    ("gem", re.compile(r"cannot load such file -- ([A-Za-z0-9_\-/]+)")),
    ("go", re.compile(r"no required module provides package ([^\s:]+)")),
    ("cargo", re.compile(r"unresolved import `([A-Za-z0-9_]+)`|use of undeclared crate or module `([A-Za-z0-9_]+)`")),
)

MANAGERS = ("pip", "npm", "npm-dev", "pnpm", "yarn", "r", "gem", "go", "cargo", "dotnet", "composer", "uv")


def missing_module_from(text: str) -> dict | None:
    """``{"manager", "module", "line"}`` or ``None``."""
    s = str(text or "")
    for manager, pattern in PATTERNS:
        match = pattern.search(s)
        if not match:
            continue
        module = match.group(1) or (match.group(2) if match.lastindex and match.lastindex >= 2 else "")
        if not module:
            continue
        if manager == "npm" and (module in NODE_BUILTINS or module.startswith(("node:", ".", "/"))):
            return None
        if manager == "pip" and module.split(".")[0] in PYTHON_STDLIB:
            return None
        return {"manager": manager, "module": module, "line": match.group(0)}
    return None


def package_for(manager: str, import_name: str) -> str:
    name = str(import_name or "").strip()
    if manager == "pip":
        if name in IMPORT_TO_PIP:
            return IMPORT_TO_PIP[name]
        root = name.split(".")[0]
        return IMPORT_TO_PIP.get(root, root)
    if manager == "gem":
        return name.split("/")[0]
    return name


def is_installable_name(name: str) -> bool:
    candidate = str(name or "").strip()
    if not candidate or len(candidate) > 160 or candidate.startswith("-"):
        return False
    bare = re.split(r"==|>=|<=|~=|!=|>|<|@(?!$)", candidate.split("[")[0])[0].strip().lower()
    if bare in INSTALL_DENYLIST:
        return False
    return bool(SAFE_PACKAGE_RE.match(candidate))


def install_command(manager: str, packages, *, python: str | None = None) -> list[str] | None:
    names = [str(p).strip() for p in (packages or []) if is_installable_name(str(p).strip())]
    if not names:
        return None
    py = python or sys.executable or ("python" if os.name == "nt" else "python3")
    if manager == "pip":
        return [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *names]
    if manager == "uv":
        return ["uv", "pip", "install", "--python", py, *names]
    if manager == "npm":
        return ["npm", "install", "--no-audit", "--no-fund", *names]
    if manager == "npm-dev":
        return ["npm", "install", "--save-dev", "--no-audit", "--no-fund", *names]
    if manager == "pnpm":
        return ["pnpm", "add", *names]
    if manager == "yarn":
        return ["yarn", "add", *names]
    if manager == "r":
        quoted = ", ".join(f"'{n}'" for n in names)
        return ["Rscript", "-e",
                f"options(repos = c(CRAN = 'https://cloud.r-project.org')); install.packages(c({quoted}), quiet = TRUE); "
                f"missing <- setdiff(c({quoted}), rownames(installed.packages())); "
                "if (length(missing)) { cat('MISSING:', paste(missing, collapse=', '), '\\n'); quit(status = 1) }"]
    if manager == "gem":
        return ["gem", "install", *names]
    if manager == "go":
        return ["go", "get", *names]
    if manager == "cargo":
        return ["cargo", "add", *names]
    if manager == "dotnet":
        return ["dotnet", "add", "package", *names]
    if manager == "composer":
        return ["composer", "require", *names]
    return None


def install(manager: str, packages, *, cwd: str, python: str | None = None, timeout: float = 900.0,
            cancel: CancelToken | None = None, on_output=None, env: dict | None = None) -> dict:
    names = [str(p).strip() for p in (packages or []) if str(p).strip()]
    rejected = [n for n in names if not is_installable_name(n)]
    accepted = [n for n in names if is_installable_name(n)]
    if not accepted:
        return {"success": False, "installed": [], "rejected": rejected, "stdout": "", "stderr": "",
                "error": "No installable package name was given."}
    argv = install_command(manager, accepted, python=python)
    if not argv:
        return {"success": False, "installed": [], "rejected": rejected, "stdout": "", "stderr": "",
                "error": f"Unknown package manager '{manager}'."}
    result = shell.run_argv(argv, cwd=cwd, timeout=timeout, cancel=cancel, on_output=on_output, env=env)
    if result.get("success") and manager in ("pip", "uv"):
        try:
            import importlib
            importlib.invalidate_caches()
        except Exception:  # noqa: BLE001
            pass
    return {**result, "installed": accepted if result.get("success") else [], "rejected": rejected,
            "error": None if result.get("success") else (result.get("error") or f"{manager} could not install the package(s).")}
