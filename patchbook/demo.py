# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
The demo model: a scripted stand-in so a first-time user can press Run before
connecting a real model. It answers every prompt iTailor can send (understand,
plan, write a script, use a tool, report) with a small, honest script that
lists the project's files and writes ``demo_summary.md``. It is labelled as a
demo everywhere it appears and never pretends to analyse anything.
"""

from __future__ import annotations

import json

from itailor.llm.client import FakeClient, tool_call_message

DEMO_SCRIPT = r'''
import csv, os
task = {task!r}
root = os.getcwd()
skip = {{".itailor", "patchbooks", "__pycache__", ".git"}}
files = []
for dirpath, dirs, names in os.walk(root):
    dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
    for name in names:
        if name.startswith(".") or name == "patchbook-project.json":
            continue
        files.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
files.sort()
lines = ["# Demo summary", "", "This was produced by the demo model of Patchbook, not by a real model.",
         "Connect a model in Settings to get real answers.", "", f"Patch: {{task}}", "", f"Files in this project: {{len(files)}}", ""]
print("Demo model: this is a stand-in. Connect a model in Settings to get real answers.")
print(f"The project folder contains {{len(files)}} file(s).")
for path in files[:40]:
    line = f"- {{path}}"
    if path.lower().endswith(".csv"):
        try:
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            if rows:
                line += f"  ({{len(rows) - 1}} rows, {{len(rows[0])}} columns: {{', '.join(rows[0][:8])}})"
        except Exception as exc:
            line += f"  (could not read: {{exc}})"
    print(line)
    lines.append(line)
with open("demo_summary.md", "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
print("Wrote demo_summary.md")
'''.strip("\n")


def demo_client(task: str) -> FakeClient:
    goal = str(task or "").strip()[:200]
    script = DEMO_SCRIPT.format(task=goal)

    def answer(messages, tools):
        system = str(messages[0].get("content") or "") if messages else ""
        if "understanding half" in system:
            return json.dumps({"restatement": f"(demo) {goal}", "unknowns": [],
                               "assumptions": ["the demo model only lists the files of the project"], "tags": ["demo"]})
        if "planning half" in system:
            return json.dumps({"restatement": f"(demo) {goal}", "assumptions": [], "steps": [
                {"id": "s1", "title": "List the project files and write demo_summary.md", "kind": "code",
                 "instruction": "List the files in the project folder and write demo_summary.md.",
                 "outputs": ["demo_summary.md"], "check": {"type": "file_exists", "path": "demo_summary.md"}, "tags": ["demo"]}]})
        if "findings section" in system:
            return ("Demo model: the files of the project were listed and demo_summary.md was written. "
                    "Connect a real model in Settings to have your patches answered for real.")
        if "iTailor, an autonomous coding agent" in system:
            return "```python\n" + script + "\n```"
        had_tool_result = any(m.get("role") == "tool" or str(m.get("content") or "").startswith("<tool_result") for m in messages)
        if tools and not had_tool_result:
            return tool_call_message("RunCode", {"language": "python", "code": script, "reason": "demo model"})
        return ("Demo model: I listed the files of the project and wrote demo_summary.md. "
                "Connect a real model in Settings to get real answers.")

    return FakeClient(answer, model="demo-model")
