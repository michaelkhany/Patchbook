# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The knowledge graph of a file: imports and aliases, functions with
signatures, classes, top-level variables, files it touches. Read before
adding to a file so the model reuses instead of redefining (DAYA's
``patch_symbols``; regex rules for other languages as in Patch Code).
"""

from __future__ import annotations

import ast
import re

_FILE_RE = re.compile(r"[\"']([^\"'\n]{1,200}\.(?:csv|tsv|xlsx|xls|json|parquet|txt|png|pdf|html|md|sav|dta|h5|pkl|npy|sqlite|db))[\"']", re.I)

_RULES = {
    "javascript": [(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", "function"),
                   (r"^\s*(?:export\s+)?class\s+(\w+)", "class"),
                   (r"^\s*(?:const|let|var)\s+(\w+)\s*=", "variable"),
                   (r"^\s*(?:import\s+.*?from\s+['\"]([^'\"]+)['\"]|const\s+\w+\s*=\s*require\(['\"]([^'\"]+)['\"]\))", "import")],
    "r": [(r"^\s*(\w[\w.]*)\s*(?:<-|=)\s*function\s*\(([^)]*)\)", "function"),
          (r"^\s*(?:library|require)\(([\w.]+)\)", "import"),
          (r"^\s*(\w[\w.]*)\s*<-", "variable")],
    "go": [(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)", "function"), (r"^\s*type\s+(\w+)\s+struct", "class"),
           (r"^\s*import\s+\"([^\"]+)\"", "import")],
    "default": [(r"^\s*(?:def|function|fn|func|sub)\s+(\w+)\s*\(([^)]*)\)", "function"),
                (r"^\s*(?:class|struct|interface)\s+(\w+)", "class")],
}
_RULES["typescript"] = _RULES["javascript"]


def analyse_python(source: str) -> dict:
    graph = {"imports": [], "functions": [], "classes": [], "variables": [], "files": sorted(set(_FILE_RE.findall(source)))}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        graph["error"] = f"SyntaxError: {exc}"
        return graph
    for node in tree.body:
        if isinstance(node, ast.Import):
            graph["imports"].extend(f"{a.name}" + (f" as {a.asname}" if a.asname else "") for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            graph["imports"].extend(f"from {node.module} import {a.name}" + (f" as {a.asname}" if a.asname else "") for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            graph["functions"].append(f"{node.name}({', '.join(args)})")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            graph["classes"].append(f"{node.name}" + (f" [{', '.join(methods[:8])}]" if methods else ""))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    graph["variables"].append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            graph["variables"].append(node.target.id)
    graph["variables"] = list(dict.fromkeys(graph["variables"]))
    return graph


def analyse(source: str, language: str = "plaintext") -> dict:
    if language == "python":
        return analyse_python(source)
    rules = _RULES.get(language) or _RULES["default"]
    graph = {"imports": [], "functions": [], "classes": [], "variables": [], "files": sorted(set(_FILE_RE.findall(source)))}
    for line in str(source or "").split("\n"):
        for pattern, kind in rules:
            match = re.match(pattern, line)
            if not match:
                continue
            groups = [g for g in match.groups() if g]
            if kind == "function":
                graph["functions"].append(f"{groups[0]}({groups[1].strip() if len(groups) > 1 else ''})")
            elif kind == "class":
                graph["classes"].append(groups[0])
            elif kind == "variable":
                graph["variables"].append(groups[0])
            elif kind == "import":
                graph["imports"].append(groups[0])
            break
    graph["variables"] = list(dict.fromkeys(graph["variables"]))
    return graph


def graph_prompt(graph: dict) -> str:
    parts = []
    if graph.get("imports"):
        parts.append("imports: " + "; ".join(graph["imports"][:40]))
    if graph.get("functions"):
        parts.append("functions: " + "; ".join(graph["functions"][:40]))
    if graph.get("classes"):
        parts.append("classes: " + "; ".join(graph["classes"][:20]))
    if graph.get("variables"):
        parts.append("variables: " + ", ".join(graph["variables"][:60]))
    if graph.get("files"):
        parts.append("files touched: " + ", ".join(graph["files"][:20]))
    if graph.get("error"):
        parts.append(graph["error"])
    return "\n".join(parts) or "(nothing defined)"
