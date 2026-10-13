# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
What a child process may see and touch.

Two questions, answered on the parent side and handed to the child:

* ``child_env`` - the *environment* a process running generated code gets.
  An allow-list (interpreter and locale basics, Windows loader variables,
  proxy and CA variables, pip's index settings) rather than ``os.environ``,
  so a secret the host process holds (an API key, a session signing key) is
  private by default. This is DAYA's ``execution.child_env``.
* ``RootsPolicy`` - the *filesystem* roots the child may write, may read, and
  must not see. The child enforces it with the CPython audit hook in
  ``itailor/guard.py`` (DAYA's ``daya_guard``), which is launched around a
  generated Python script by ``guard_argv``.

``resolve_path`` is the parent-side check the file tools use: a path that
escapes the project is refused before anything is touched (Patch Code's
``confineToWorkspace``).

Honest limits: this is a local-machine posture for the user's own
environment. The audit hook is a real boundary against generated code doing
something destructive; it is not a jail against a human attacker (PEP 578
says so itself). OS-level confinement belongs to an ``ExecutionContext``
adapter when one is added.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field

MODE_ENV = "ITAILOR_SANDBOX"
READ_EXTRA_ENV = "ITAILOR_SANDBOX_READ_EXTRA"
PASSTHROUGH_ENV = "ITAILOR_CHILD_ENV_PASSTHROUGH"
MODES = ("strict", "writes", "off")
DEFAULT_MODE = "writes"
# "writes" rather than DAYA's "strict" as the library default: on a developer's
# own machine a script that reads a file elsewhere is routine, while writing
# elsewhere is not. A shared server sets ITAILOR_SANDBOX=strict (or the
# `shared-server` profile does).

SCRATCH_DIRNAME = ".tmp"
MPL_DIRNAME = ".mplconfig"
HOME_DIRNAME = ".home"

GUARD_MODULE = "guard"
GUARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), GUARD_MODULE + ".py")

# ---------------------------------------------------------------------------
# Environment allow-list (DAYA execution.py)
# ---------------------------------------------------------------------------
_BASE = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TZ", "TMPDIR", "TEMP", "TMP",
    "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "TERM",
)
_WINDOWS = (
    "SYSTEMROOT", "SystemRoot", "SYSTEMDRIVE", "SystemDrive", "WINDIR", "windir",
    "COMSPEC", "ComSpec", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMDATA",
    "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH",
)
_NETWORK = (
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "FTP_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "ftp_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST", "PIP_CERT",
    "PIP_CONFIG_FILE", "PIP_RETRIES", "PIP_TIMEOUT",
)
# Toolchains that do not start without their own variables.
_TOOLCHAINS = (
    "JAVA_HOME", "GOPATH", "GOROOT", "CARGO_HOME", "RUSTUP_HOME", "DOTNET_ROOT",
    "R_HOME", "R_LIBS_USER", "CONDA_PREFIX", "VIRTUAL_ENV", "NODE_PATH", "NVM_DIR",
)
ALLOWED = tuple(dict.fromkeys(_BASE + _WINDOWS + _NETWORK + _TOOLCHAINS))


def _site_passthrough() -> tuple:
    raw = os.environ.get(PASSTHROUGH_ENV, "")
    return tuple(name.strip() for name in raw.replace(";", ",").split(",") if name.strip())


def child_env(extra: dict | None = None, *, base: dict | None = None) -> dict:
    """The environment for a process running generated code.

    ``extra`` is merged last, so a caller's own variables win. A value of
    ``None`` in ``extra`` removes a name.
    """
    source = os.environ if base is None else base
    env: dict = {}
    for name in ALLOWED + _site_passthrough():
        value = source.get(name)
        if value is not None:
            env[name] = str(value)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    for key, value in (extra or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = str(value)
    return env


def redacted_names(base: dict | None = None) -> list:
    """Which of the parent's variables are being withheld. For diagnostics."""
    source = os.environ if base is None else base
    passed = set(ALLOWED) | set(_site_passthrough())
    return sorted(name for name in source if name not in passed)


# ---------------------------------------------------------------------------
# Filesystem roots (DAYA sandbox.py)
# ---------------------------------------------------------------------------
def mode_from_env(default: str = DEFAULT_MODE) -> str:
    value = str(os.environ.get(MODE_ENV, default) or default).strip().lower()
    return value if value in MODES else default


def _join(paths) -> str:
    seen, out = set(), []
    for path in paths:
        if not path:
            continue
        absolute = os.path.abspath(path)
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return os.pathsep.join(out)


def _split(value) -> list:
    return [item for item in str(value or "").split(os.pathsep) if item.strip()]


@dataclass
class RootsPolicy:
    """Where generated code may reach. ``workdir`` is where it runs."""

    workdir: str
    project_root: str = ""
    scratch: str = ""
    mode: str = field(default_factory=mode_from_env)
    extra_read: tuple = ()
    extra_write: tuple = ()
    readonly: tuple = ()
    hidden: tuple = ()

    def __post_init__(self) -> None:
        self.workdir = os.path.abspath(self.workdir or os.getcwd())
        self.project_root = os.path.abspath(self.project_root) if self.project_root else ""
        self.scratch = os.path.abspath(self.scratch) if self.scratch else self.workdir
        if self.mode not in MODES:
            self.mode = DEFAULT_MODE

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def child_paths(self) -> dict:
        """The environment that tells a child what it may touch."""
        tmp = os.path.join(self.scratch, SCRATCH_DIRNAME)
        home = os.path.join(self.scratch, HOME_DIRNAME)
        for folder in (tmp, home):
            with contextlib.suppress(OSError):
                os.makedirs(folder, exist_ok=True)
        environment = {
            MODE_ENV: self.mode,
            "ITAILOR_WORKDIR": self.workdir,
            "ITAILOR_SCRATCH_DIR": self.scratch,
            "MPLCONFIGDIR": os.path.join(self.scratch, MPL_DIRNAME),
            "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp,
            "JOBLIB_TEMP_FOLDER": tmp,
            "HOME": home, "USERPROFILE": home,
            "XDG_CACHE_HOME": os.path.join(home, ".cache"),
            "XDG_CONFIG_HOME": os.path.join(home, ".config"),
            "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
            "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
        }
        if self.project_root:
            environment["ITAILOR_PROJECT_DIR"] = self.project_root
        if not self.enabled:
            return environment
        environment["ITAILOR_SANDBOX_WRITE"] = _join([self.workdir, self.scratch, *self.extra_write])
        environment["ITAILOR_SANDBOX_READONLY"] = _join(list(self.readonly))
        hidden = list(self.hidden)
        if self.project_root:
            # Other runs' folders are not this run's business.
            hidden.append(os.path.join(self.project_root, ".itailor", "runs"))
        environment["ITAILOR_SANDBOX_HIDDEN"] = _join(hidden)
        operator = _split(os.environ.get(READ_EXTRA_ENV))
        environment["ITAILOR_SANDBOX_READ"] = _join(
            [self.project_root, *self.extra_read, *operator])
        return environment

    def guard_argv(self, python_executable: str, script: str, *args) -> list:
        """``python guard.py script.py ...``, or the plain command when off."""
        if not self.enabled:
            return [python_executable, script, *args]
        return [python_executable, GUARD_PATH, script, *args]

    def prompt_rules(self) -> str:
        """The limits, phrased for the model that writes the code."""
        if self.mode == "off":
            return ""
        lines = ["SANDBOX - enforced at runtime, not advice:",
                 "* Write only inside the working directory (a subfolder is fine). "
                 "Anywhere else raises PermissionError. Name output files descriptively."]
        if self.mode == "strict":
            lines.append("* Read only the project folder. Do not touch absolute paths elsewhere.")
            lines.append("* No network access: no requests, urllib, sockets or downloads.")
        lines.append("* Do not start another process (subprocess, os.system, shell) from "
                     "generated Python; do the work in the script, or use the Shell tool.")
        return "\n".join(lines) + "\n"

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "enabled": self.enabled,
            "workdir": self.workdir,
            "projectRoot": self.project_root,
            "summary": {
                "strict": "Generated Python may write only in the working directory, read "
                          "only the project, and may not start processes or use the network.",
                "writes": "Generated Python may read anywhere and use the network, but may "
                          "write only in the working directory and may not start processes.",
                "off": "Generated code runs with no filesystem or process limits.",
            }[self.mode],
        }


# ---------------------------------------------------------------------------
# Parent-side path confinement for the file tools
# ---------------------------------------------------------------------------
class PathOutsideProject(PermissionError):
    pass


def resolve_path(root: str, path: str, *, confine: bool = True, must_exist: bool = False) -> str:
    """Resolve ``path`` against ``root``; refuse escapes when confined."""
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("A path is required.")
    root_abs = os.path.abspath(root)
    absolute = os.path.abspath(os.path.join(root_abs, raw))
    if confine:
        try:
            real_root = os.path.realpath(root_abs)
            real_abs = os.path.realpath(absolute)
        except OSError:
            real_root, real_abs = root_abs, absolute
        rel = os.path.relpath(real_abs, real_root)
        if rel.startswith("..") or os.path.isabs(rel):
            raise PathOutsideProject(
                f"'{raw}' is outside the project ({root_abs}). The sandbox confines "
                "iTailor to the project; set sandbox.confineToProject to false to allow it.")
    if must_exist and not os.path.exists(absolute):
        raise FileNotFoundError(f"No such file or directory: {raw}")
    return absolute


def rel_of(root: str, absolute: str) -> str:
    try:
        rel = os.path.relpath(absolute, root)
    except ValueError:
        return absolute
    return rel.replace(os.sep, "/") or "."
