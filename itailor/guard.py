# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The confinement that runs INSIDE a process executing generated Python.

A CPython audit hook (PEP 578) installed before any generated code runs
refuses the operations that leave the run's roots:

* writing, creating, deleting or renaming outside the writable roots;
* reading outside the readable roots, the interpreter's own tree and the OS
  files a scientific-Python process genuinely needs (strict mode only);
* starting another interpreter (which would run without a hook);
* opening a network connection (strict mode only);
* ``ctypes.dlopen`` of a library by path outside the interpreter tree.

An installed library reading its own configuration while being imported is
allowed whatever the path - that is the library's business, not the patch's.

This file is stdlib-only and imports nothing from iTailor on purpose: it runs
in whichever interpreter the script was pointed at.

Usage:
    python guard.py script.py [args...]
    import guard; guard.install()

Ported from DAYA Studio's ``backend/daya_guard.py`` with ``ITAILOR_*``
variable names. Landlock (the Linux kernel layer DAYA adds) is not included
here; it belongs to an execution-context adapter.
"""

from __future__ import annotations

import os
import sys

MODE_ENV = "ITAILOR_SANDBOX"
WRITE_ENV = "ITAILOR_SANDBOX_WRITE"
READ_ENV = "ITAILOR_SANDBOX_READ"
READ_EXTRA_ENV = "ITAILOR_SANDBOX_READ_EXTRA"
READONLY_ENV = "ITAILOR_SANDBOX_READONLY"
HIDDEN_ENV = "ITAILOR_SANDBOX_HIDDEN"

NOT_YOUR_CODE = ("This was requested by an installed library, not by this script, "
                 "so rewriting the script will not fix it.")
MODES = ("strict", "writes", "off")
DEFAULT_MODE = "writes"

_installed = False


def _norm(path) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.fspath(path)))
    except (TypeError, ValueError, OSError):
        return ""


def _split(value) -> list:
    return [item for item in str(value or "").split(os.pathsep) if item]


def _interpreter_roots() -> list:
    roots = [sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix,
             os.path.dirname(os.__file__ or ""), os.path.dirname(sys.executable or "")]
    roots.extend(entry for entry in sys.path if entry)
    try:
        import site
        roots.extend(site.getsitepackages())
        roots.append(site.getusersitepackages())
    except Exception:  # noqa: BLE001
        pass
    return roots


def _stdlib_data_files() -> list:
    files: list = []
    try:
        import mimetypes
        files.extend(mimetypes.knownfiles)
    except Exception:  # noqa: BLE001
        pass
    return files


def _system_read_roots() -> list:
    if os.name == "nt":
        return [os.environ.get("SYSTEMROOT") or r"C:\Windows"] + _stdlib_data_files()
    return [
        "/usr/share/zoneinfo", "/etc/localtime", "/etc/timezone",
        "/usr/lib/locale", "/usr/share/locale", "/usr/share/i18n",
        "/etc/ssl/certs", "/etc/pki/tls", "/usr/share/ca-certificates",
        "/usr/share/mime",
        "/etc/fonts", "/usr/share/fonts", "/usr/local/share/fonts",
        "/usr/share/fontconfig", "/var/cache/fontconfig",
        "/etc/os-release", "/usr/lib/os-release", "/etc/lsb-release",
        "/etc/debian_version", "/etc/redhat-release",
        "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
        "/proc/self", "/proc/meminfo", "/proc/cpuinfo", "/proc/stat",
        "/proc/sys/vm", "/proc/sys/kernel",
        "/sys/devices/system/cpu", "/sys/fs/cgroup",
        "/dev/null", "/dev/zero", "/dev/urandom", "/dev/random",
    ] + _stdlib_data_files()


def _is_under(resolved: str, roots) -> bool:
    for root in roots:
        if resolved == root or resolved.startswith(root + os.sep):
            return True
    return False


class _Policy:
    def __init__(self, mode: str, write_roots, read_roots, readonly_roots=(), hidden_roots=()):
        self.mode = mode
        self.readonly = tuple(dict.fromkeys(p for p in (_norm(x) for x in readonly_roots if x) if p))
        self.hidden = tuple(dict.fromkeys(p for p in (_norm(x) for x in hidden_roots if x) if p))
        self.write = tuple(dict.fromkeys(p for p in (_norm(x) for x in write_roots if x) if p))
        readable = set(self.write)
        readable.update(_norm(p) for p in read_roots if p)
        if mode == "writes":
            self.read_enforced = False
        else:
            self.read_enforced = True
            readable.update(_norm(p) for p in _interpreter_roots())
            readable.update(_norm(p) for p in _system_read_roots())
        readable.discard("")
        self.read = tuple(sorted(readable))
        self._cache: dict = {}

    def _resolve_dir(self, path: str) -> str:
        directory = os.path.dirname(path) or path
        cached = self._cache.get(directory)
        if cached is not None:
            return cached
        try:
            resolved = os.path.normcase(os.path.realpath(directory))
        except OSError:
            resolved = directory
        if len(self._cache) > 4096:
            self._cache.clear()
        self._cache[directory] = resolved
        return resolved

    def allows(self, path, *, write: bool) -> bool:
        raw = _norm(path)
        if not raw:
            return True
        roots = self.write if write else self.read
        if not roots:
            return not write
        resolved = os.path.join(self._resolve_dir(raw), os.path.basename(raw))

        def longest(candidates):
            return max((len(root) for root in candidates
                        if _is_under(resolved, (root,)) or _is_under(raw, (root,))), default=-1)

        allowed = longest(roots)
        denied = longest(self.hidden if not write else self.hidden + self.readonly)
        return allowed >= 0 and allowed > denied


_OPEN = "open"
_WRITE_EVENTS = {
    "os.mkdir": 1, "os.rmdir": 1, "os.remove": 1, "os.unlink": 1,
    "os.rename": 2, "os.replace": 2, "os.link": 2, "os.symlink": 2,
    "os.chmod": 1, "os.chown": 1, "os.truncate": 1, "os.utime": 1,
    "shutil.copyfile": 2, "shutil.copymode": 2, "shutil.copystat": 2,
    "shutil.move": 2, "shutil.rmtree": 1, "shutil.unpack_archive": 2,
}
_READ_EVENTS = {"os.listdir": 1, "os.scandir": 1, "os.chdir": 1,
                "os.getxattr": 1, "pathlib.Path.glob": 1}
_SPAWN_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
                 "os.startfile", "pty.spawn"}
_NETWORK_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.bind",
                   "socket.sendto", "urllib.Request", "ftplib.connect", "smtplib.connect"}
_CTYPES_EVENTS = {"ctypes.dlopen"}
_WATCHED = frozenset({_OPEN} | set(_WRITE_EVENTS) | set(_READ_EVENTS)
                     | _SPAWN_EVENTS | _NETWORK_EVENTS | _CTYPES_EVENTS)
_WRITE_MODE_CHARS = frozenset("wax+")


def _opens_for_writing(args) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str):
        return bool(_WRITE_MODE_CHARS & set(mode))
    if mode is None and isinstance(flags, int):
        writable = 0
        for name in ("O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC"):
            writable |= getattr(os, name, 0)
        return bool(flags & writable)
    return mode is not None


_IMPORT_FRAMES = ("<frozen importlib._bootstrap>", "<frozen importlib._bootstrap_external>",
                  "importlib/_bootstrap.py", "importlib/_bootstrap_external.py",
                  "importlib/__init__.py")


def _importing_library() -> bool:
    frame = sys._getframe(1)
    depth = 0
    while frame is not None and depth < 40:
        name = frame.f_code.co_filename.replace("\\", "/")
        if any(marker in name for marker in _IMPORT_FRAMES):
            return True
        frame = frame.f_back
        depth += 1
    return False


def _frames(interpreter):
    frame = sys._getframe(1)
    depth = 0
    while frame is not None and depth < 40:
        name = frame.f_code.co_filename or ""
        frame = frame.f_back
        depth += 1
        if not name or name == __file__ or name.startswith("<frozen "):
            continue
        library = not name.startswith("<") and _is_under(_norm(name), interpreter)
        yield name, library


def _asked_by_installed_library(interpreter) -> bool:
    for _name, library in _frames(interpreter):
        return library
    return False


def _patch_in_stack(interpreter) -> bool:
    for _name, library in _frames(interpreter):
        if not library:
            return True
    return False


def _refuse(what: str, detail: str, policy: _Policy, *, blame_patch: bool = True):
    where = ", ".join(policy.write) or "(nothing)"
    if blame_patch:
        advice = ("Use a path relative to the working directory. An operator can change "
                  f"this with {MODE_ENV}=writes|off.")
    else:
        advice = (f"{NOT_YOUR_CODE} An operator can allow this path with "
                  f"{READ_EXTRA_ENV}={detail.strip(chr(39))}, or relax the policy with "
                  f"{MODE_ENV}=writes.")
    raise PermissionError(
        f"iTailor sandbox: {what} {detail}. Generated code may write inside {where}. {advice}")


def _make_hook(policy: _Policy):
    interpreter = tuple(sorted({_norm(p) for p in _interpreter_roots()} - {""}))

    def hook(event, args):
        if event not in _WATCHED:
            return
        if event == _OPEN:
            path = args[0] if args else None
            if isinstance(path, int):
                return
            write = _opens_for_writing(args)
            if policy.allows(path, write=write):
                return
            if not write:
                if not policy.read_enforced:
                    return
                if _asked_by_installed_library(interpreter) and _importing_library():
                    return
                _refuse("this script may not read", f"'{path}'", policy,
                        blame_patch=_patch_in_stack(interpreter))
                return
            _refuse("this script may not write", f"'{path}'", policy)
            return
        count = _WRITE_EVENTS.get(event)
        if count:
            for path in args[:count]:
                if isinstance(path, int) or policy.allows(path, write=True):
                    continue
                _refuse("this script may not change", f"'{path}'", policy)
            return
        count = _READ_EVENTS.get(event)
        if count:
            if not policy.read_enforced:
                return
            for path in args[:count]:
                if isinstance(path, int) or policy.allows(path, write=False):
                    continue
                if _asked_by_installed_library(interpreter) and _importing_library():
                    continue
                _refuse("this script may not read", f"'{path}'", policy,
                        blame_patch=_patch_in_stack(interpreter))
            return
        if event in _SPAWN_EVENTS:
            raise PermissionError(
                "iTailor sandbox: generated code may not start another process - a child "
                "would run outside this run's limits. Do the work in Python here, or ask "
                f"iTailor to run the command through its Shell tool. ({MODE_ENV}=off disables this.)")
        if event in _NETWORK_EVENTS:
            if policy.mode != "strict":
                return
            raise PermissionError(
                "iTailor sandbox: generated code may not open a network connection in strict "
                f"mode. ({MODE_ENV}=writes allows it.)")
        if event in _CTYPES_EVENTS:
            name = str(args[0]) if args and args[0] else ""
            if not name or (os.sep not in name and "/" not in name):
                return
            if _is_under(_norm(name), interpreter):
                return
            raise PermissionError(
                f"iTailor sandbox: generated code may not load the native library '{name}'. "
                "Only libraries that ship with this Python may be loaded.")

    return hook


def resolved_mode() -> str:
    mode = str(os.environ.get(MODE_ENV, DEFAULT_MODE) or DEFAULT_MODE).strip().lower()
    return mode if mode in MODES else DEFAULT_MODE


def install(*, write_roots=None, read_roots=None, mode=None) -> str:
    """Install the audit hook once. Returns the mode actually in force."""
    global _installed
    if _installed:
        return resolved_mode()
    mode = (mode or resolved_mode()).strip().lower()
    if mode not in MODES:
        mode = DEFAULT_MODE
    _installed = True
    if mode == "off":
        return mode
    writes = list(write_roots or _split(os.environ.get(WRITE_ENV)))
    if not writes:
        writes = [os.getcwd()]
    reads = list(read_roots or _split(os.environ.get(READ_ENV)))
    readonly = _split(os.environ.get(READONLY_ENV))
    hidden = _split(os.environ.get(HIDDEN_ENV))
    policy = _Policy(mode, writes, reads, readonly, hidden)
    sys.addaudithook(_make_hook(policy))
    return mode


def main(argv) -> int:
    if not argv:
        print("usage: guard.py <script.py> [args...]", file=sys.stderr)
        return 2
    script = os.path.abspath(argv[0])
    install(write_roots=[os.path.dirname(script)] + _split(os.environ.get(WRITE_ENV)))
    sys.argv = [script] + list(argv[1:])
    globals_ = {"__name__": "__main__", "__file__": script, "__doc__": None,
                "__package__": None, "__builtins__": __builtins__}
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or ".") != here]
    sys.path.insert(0, os.path.dirname(script))
    try:
        with open(script, "r", encoding="utf-8-sig") as handle:
            source = handle.read()
    except OSError as exc:
        print(f"guard: cannot read {script}: {exc}", file=sys.stderr)
        return 1
    try:
        exec(compile(source, script, "exec"), globals_, globals_)  # noqa: S102
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
