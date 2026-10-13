# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Language registry.

The file tools are language-agnostic. What a *patch* needs on top is here:
the fence tag the model should use, the comment syntax for markers, the
missing-module pattern and package manager, and - where an interpreter or
compiler exists - how to RUN a generated script so it can be repaired against
its real error output.

``run`` is a function ``(script_path, ctx) -> argv | None``; ``ctx`` is a dict
with ``platform``, ``python`` and ``cwd``. ``available()`` says which of these
languages actually have their program on PATH right now.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Callable

IS_WIN = os.name == "nt"


@dataclass
class Language:
    id: str
    label: str
    extensions: tuple
    fence: str
    comment: str = "#"
    comment_end: str = ""
    run: Callable | None = None
    compile: Callable | None = None
    missing_module: re.Pattern | None = None
    package_manager: str = ""
    programs: tuple = field(default_factory=tuple)   # what must be on PATH

    @property
    def runnable(self) -> bool:
        return self.run is not None or self.compile is not None


def _python(ctx):
    return (ctx or {}).get("python") or sys.executable or ("python" if IS_WIN else "python3")


LANGUAGES: list[Language] = [
    Language("python", "Python", (".py", ".pyw"), "python", "#",
             run=lambda s, ctx=None: [_python(ctx), s],
             missing_module=re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]"),
             package_manager="pip", programs=("python",)),
    Language("javascript", "JavaScript", (".js", ".mjs", ".cjs", ".jsx"), "javascript", "//",
             run=lambda s, ctx=None: ["node", s],
             missing_module=re.compile(r"Cannot find (?:module|package) '([^']+)'"),
             package_manager="npm", programs=("node",)),
    Language("typescript", "TypeScript", (".ts", ".mts", ".cts", ".tsx"), "typescript", "//",
             run=lambda s, ctx=None: ["npx", "--yes", "tsx", s],
             missing_module=re.compile(r"Cannot find (?:module|package) '([^']+)'"),
             package_manager="npm", programs=("npx",)),
    Language("r", "R", (".r", ".R", ".rmd"), "r", "#",
             run=lambda s, ctx=None: ["Rscript", s],
             missing_module=re.compile(r"there is no package called ['‘\"]([A-Za-z0-9_.]+)['’\"]"),
             package_manager="r", programs=("Rscript",)),
    Language("shellscript", "Bash", (".sh", ".bash"), "bash", "#",
             run=lambda s, ctx=None: ["bash", s], programs=("bash",)),
    Language("powershell", "PowerShell", (".ps1", ".psm1"), "powershell", "#",
             run=lambda s, ctx=None: ["powershell" if IS_WIN else "pwsh", "-NoProfile",
                                      "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", s],
             programs=("powershell" if IS_WIN else "pwsh",)),
    Language("go", "Go", (".go",), "go", "//",
             run=lambda s, ctx=None: ["go", "run", s], package_manager="go", programs=("go",)),
    Language("rust", "Rust", (".rs",), "rust", "//",
             compile=lambda s, out: ["rustc", s, "-o", out], package_manager="cargo",
             programs=("rustc",)),
    Language("java", "Java", (".java",), "java", "//",
             run=lambda s, ctx=None: ["java", s], programs=("java",)),
    Language("kotlin", "Kotlin", (".kt", ".kts"), "kotlin", "//",
             run=lambda s, ctx=None: ["kotlinc", "-script", s] if s.endswith(".kts") else None,
             programs=("kotlinc",)),
    Language("c", "C", (".c", ".h"), "c", "//",
             compile=lambda s, out: ["gcc", s, "-o", out], programs=("gcc",)),
    Language("cpp", "C++", (".cpp", ".cc", ".cxx", ".hpp", ".hh"), "cpp", "//",
             compile=lambda s, out: ["g++", "-std=c++17", s, "-o", out], programs=("g++",)),
    Language("csharp", "C#", (".cs",), "csharp", "//",
             run=lambda s, ctx=None: ["dotnet", "run", "--project", os.path.dirname(s)],
             package_manager="dotnet", programs=("dotnet",)),
    Language("ruby", "Ruby", (".rb",), "ruby", "#",
             run=lambda s, ctx=None: ["ruby", s],
             missing_module=re.compile(r"cannot load such file -- ([A-Za-z0-9_\-/]+)"),
             package_manager="gem", programs=("ruby",)),
    Language("php", "PHP", (".php",), "php", "//",
             run=lambda s, ctx=None: ["php", s], package_manager="composer", programs=("php",)),
    Language("perl", "Perl", (".pl", ".pm"), "perl", "#",
             run=lambda s, ctx=None: ["perl", s], programs=("perl",)),
    Language("lua", "Lua", (".lua",), "lua", "--",
             run=lambda s, ctx=None: ["lua", s], programs=("lua",)),
    Language("swift", "Swift", (".swift",), "swift", "//",
             run=lambda s, ctx=None: ["swift", s], programs=("swift",)),
    Language("dart", "Dart", (".dart",), "dart", "//",
             run=lambda s, ctx=None: ["dart", "run", s], programs=("dart",)),
    Language("julia", "Julia", (".jl",), "julia", "#",
             run=lambda s, ctx=None: ["julia", s], programs=("julia",)),
    Language("scala", "Scala", (".scala", ".sc"), "scala", "//",
             run=lambda s, ctx=None: ["scala-cli", "run", s], programs=("scala-cli",)),
    Language("elixir", "Elixir", (".ex", ".exs"), "elixir", "#",
             run=lambda s, ctx=None: ["elixir", s], programs=("elixir",)),
    Language("haskell", "Haskell", (".hs",), "haskell", "--",
             run=lambda s, ctx=None: ["runghc", s], programs=("runghc",)),
    Language("sql", "SQL", (".sql",), "sql", "--"),
    Language("html", "HTML", (".html", ".htm"), "html", "<!--", "-->"),
    Language("css", "CSS", (".css", ".scss", ".less"), "css", "/*", "*/"),
    Language("json", "JSON", (".json", ".jsonc"), "json", "//"),
    Language("yaml", "YAML", (".yml", ".yaml"), "yaml", "#"),
    Language("toml", "TOML", (".toml",), "toml", "#"),
    Language("markdown", "Markdown", (".md", ".markdown"), "markdown", "<!--", "-->"),
    Language("xml", "XML", (".xml", ".xsl", ".svg"), "xml", "<!--", "-->"),
    Language("dockerfile", "Dockerfile", (".dockerfile",), "dockerfile", "#"),
    Language("makefile", "Makefile", (".mk",), "makefile", "#"),
    Language("plaintext", "Plain text", (".txt",), "", "#"),
]

BY_ID = {lang.id: lang for lang in LANGUAGES}
BY_EXT = {ext.lower(): lang for lang in LANGUAGES for ext in lang.extensions}

ALIASES = {
    "py": "python", "python3": "python", "js": "javascript", "ts": "typescript", "tsx": "typescript",
    "jsx": "javascript", "node": "javascript", "javascriptreact": "javascript",
    "typescriptreact": "typescript", "sh": "shellscript", "bash": "shellscript",
    "zsh": "shellscript", "shell": "shellscript", "rlang": "r", "rscript": "r", "c++": "cpp",
    "cs": "csharp", "golang": "go", "rb": "ruby", "md": "markdown", "yml": "yaml",
    "jsonc": "json", "ps1": "powershell", "pwsh": "powershell", "kt": "kotlin", "rs": "rust",
    "jl": "julia", "hs": "haskell",
}


def by_id(identifier) -> Language | None:
    key = str(identifier or "").lower().strip()
    return BY_ID.get(key) or BY_ID.get(ALIASES.get(key, ""))


def by_filename(filename) -> Language | None:
    base = os.path.basename(str(filename or ""))
    if base.lower() == "dockerfile":
        return BY_ID["dockerfile"]
    if base.lower() == "makefile":
        return BY_ID["makefile"]
    return BY_EXT.get(os.path.splitext(base)[1].lower())


def resolve(hint, filename=None) -> Language | None:
    direct = by_id(hint)
    if direct:
        return direct
    if hint and str(hint).startswith("."):
        return BY_EXT.get(str(hint).lower())
    if filename:
        return by_filename(filename)
    return None


def fence_of(lang: Language | None) -> str:
    return lang.fence if lang else ""


def comment_line(lang: Language | None, text: str) -> str:
    open_ = lang.comment if lang else "#"
    close = f" {lang.comment_end}" if lang and lang.comment_end else ""
    return f"{open_} {text}{close}"


def runnable() -> list[str]:
    """Languages with a declared runner (not probed)."""
    return [lang.id for lang in LANGUAGES if lang.runnable]


def program_available(lang: Language) -> bool:
    if lang.id == "python":
        return True
    return all(shutil.which(program) is not None for program in lang.programs)


def available() -> list[str]:
    """Languages whose program is on PATH right now - what the model is told it can run."""
    return [lang.id for lang in LANGUAGES if lang.runnable and program_available(lang)]


def summary() -> str:
    return "; ".join(f"{l.label} ({', '.join(l.extensions)})" + ("" if l.runnable else " - edit only")
                     for l in LANGUAGES)


_R_HINTS = ("ggplot", "tidyverse", "dplyr", "rscript", " in r", "r script", "r code",
            "using r", "with r", "lme4", "rstudio", "data.frame(", " r:")


def choose(requested: str | None, task: str = "") -> str:
    """Resolve 'auto' to a concrete runnable language id (DAYA's choose_language)."""
    key = str(requested or "auto").lower().strip()
    if key != "auto":
        lang = by_id(key)
        return lang.id if lang else "python"
    text = str(task or "").lower()
    if any(hint in text for hint in _R_HINTS) and program_available(BY_ID["r"]):
        return "r"
    if any(w in text for w in (" in javascript", " in node", "node.js", " in js ")) \
            and program_available(BY_ID["javascript"]):
        return "javascript"
    return "python"
