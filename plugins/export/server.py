# Patchbook plugin: Export - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
"""Export a Patchbook as Markdown, as a Jupyter notebook (.ipynb) or as a self-contained web page."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re

from flask import Response, request


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text or "patchbook")).strip("-") or "patchbook"


def _read_bytes(project: str, rel: str) -> bytes | None:
    full = os.path.abspath(os.path.join(project, rel))
    if os.path.commonpath([project, full]) != project or not os.path.isfile(full):
        return None
    with open(full, "rb") as handle:
        return handle.read()


def _data_uri(project: str, rel: str) -> str:
    data = _read_bytes(project, rel)
    if data is None:
        return ""
    mime = mimetypes.guess_type(rel)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _tiny_markdown(text: str) -> str:
    """Enough Markdown for notes and answers: headings, lists, fenced code, bold, italic, inline code, links."""
    out: list[str] = []
    lines = str(text or "").splitlines()
    i = 0
    in_list = False

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
        elif re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(re.sub(r"^\s*[-*]\s+", "", line)) + "</li>")
        elif not line.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<p>" + inline(line) + "</p>")
        i += 1
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def to_markdown(book: dict, project: str) -> str:
    lines = [f"# {book.get('name', 'Patchbook')}", "", f"_Exported from Patchbook. Project folder: {os.path.basename(project)}_", ""]
    for index, cell in enumerate(book.get("cells") or [], 1):
        kind, text, result = cell.get("kind"), str(cell.get("text") or "").strip(), cell.get("result") or {}
        if kind == "note":
            lines += [text, ""]
            continue
        if not text and not result:
            continue
        lines.append(f"## {index}. {'Code cell' if kind == 'code' else 'Patch'}")
        lines.append("")
        if kind == "patch":
            lines += ["> " + text.replace("\n", "\n> "), ""]
        if result.get("code"):
            lines += [f"```{result.get('language') or ''}", str(result["code"]).rstrip(), "```", ""]
        summary = str(result.get("summary") or "").strip()
        if summary:
            if result.get("engine") in ("thorough", "ask"):
                lines += ["**Answer**", "", summary, ""]
            else:
                lines += ["**Output**", "", "```", summary, "```", ""]
        if result.get("error") and cell.get("status") != "done":
            lines += ["**Problem**", "", "```", str(result["error"]), "```", ""]
        files = [f for f in (result.get("files") or []) if isinstance(f, dict)]
        if files:
            lines.append("**Files**")
            lines.append("")
            for f in files:
                if f.get("kind") == "image":
                    lines.append(f"![{f.get('name')}]({f.get('path')})")
                else:
                    lines.append(f"- [{f.get('name')}]({f.get('path')})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_ipynb(book: dict, project: str) -> dict:
    cells = []

    def md(source: str) -> dict:
        return {"cell_type": "markdown", "metadata": {}, "source": source}

    cells.append(md(f"# {book.get('name', 'Patchbook')}\n\nExported from Patchbook."))
    for index, cell in enumerate(book.get("cells") or [], 1):
        kind, text, result = cell.get("kind"), str(cell.get("text") or "").strip(), cell.get("result") or {}
        if kind == "note":
            cells.append(md(text))
            continue
        if not text and not result:
            continue
        if kind == "patch":
            cells.append(md(f"**Patch {index}:** {text}"))
        outputs = []
        if result.get("summary") and result.get("engine") in ("quick", "code"):
            outputs.append({"output_type": "stream", "name": "stdout", "text": str(result["summary"]) + "\n"})
        elif result.get("summary"):
            cells.append(md(str(result["summary"])))
        for f in result.get("files") or []:
            if isinstance(f, dict) and f.get("kind") == "image" and str(f.get("path", "")).lower().endswith(".png"):
                data = _read_bytes(project, f["path"])
                if data:
                    outputs.append({"output_type": "display_data", "metadata": {}, "data": {"image/png": base64.b64encode(data).decode("ascii"), "text/plain": f["path"]}})
        if result.get("error") and cell.get("status") != "done":
            outputs.append({"output_type": "stream", "name": "stderr", "text": str(result["error"]) + "\n"})
        code = result.get("code") or (text if kind == "code" else "")
        if code:
            cells.append({"cell_type": "code", "metadata": {"patchbook": {"kind": kind, "language": result.get("language") or cell.get("language")}},
                          "execution_count": cell.get("executionCount"), "source": str(code).rstrip() + "\n", "outputs": outputs})
        elif outputs:
            cells.append({"cell_type": "code", "metadata": {}, "execution_count": cell.get("executionCount"), "source": "# (no code: this patch ran as a thorough or ask run)\n", "outputs": outputs})
    return {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
            "language_info": {"name": "python"}, "patchbook": {"name": book.get("name"), "exported": True}}, "cells": cells}


def to_html(book: dict, project: str) -> str:
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
             f"<title>{html.escape(book.get('name', 'Patchbook'))}</title><style>",
             "body{font:15px/1.5 system-ui,sans-serif;max-width:900px;margin:30px auto;padding:0 20px;color:#1c2230;background:#fff}",
             "h1{font-size:26px}h2{font-size:18px;margin-top:34px;border-top:1px solid #e2e5ea;padding-top:16px}",
             "blockquote{margin:0 0 12px;padding:10px 14px;border-left:4px solid #2456c8;background:#f1f4fb;font-size:16px}",
             "pre{background:#f4f5f7;border:1px solid #e2e5ea;border-radius:6px;padding:10px 12px;overflow:auto;font-size:13px}",
             "code{font-family:ui-monospace,Menlo,Consolas,monospace}.label{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:#6b7280;margin:12px 0 4px}",
             "img{max-width:100%;border:1px solid #e2e5ea;border-radius:6px}.err{color:#c0392b}.files li{margin:2px 0}.note{background:#fbfbfc;padding:2px 0}",
             "footer{margin-top:40px;color:#6b7280;font-size:12px}</style></head><body>",
             f"<h1>{html.escape(book.get('name', 'Patchbook'))}</h1><p style='color:#6b7280'>Exported from Patchbook {html.escape(str(book.get('updated') or ''))}</p>"]
    for index, cell in enumerate(book.get("cells") or [], 1):
        kind, text, result = cell.get("kind"), str(cell.get("text") or "").strip(), cell.get("result") or {}
        if kind == "note":
            parts.append("<div class='note'>" + _tiny_markdown(text) + "</div>")
            continue
        if not text and not result:
            continue
        parts.append(f"<h2>{index}. {'Code cell' if kind == 'code' else 'Patch'}</h2>")
        if kind == "patch":
            parts.append("<blockquote>" + html.escape(text) + "</blockquote>")
        summary = str(result.get("summary") or "").strip()
        if summary:
            if result.get("engine") in ("thorough", "ask"):
                parts.append("<div class='label'>Answer</div>" + _tiny_markdown(summary))
            else:
                parts.append("<div class='label'>Output</div><pre>" + html.escape(summary) + "</pre>")
        if result.get("error") and cell.get("status") != "done":
            parts.append("<div class='label'>Problem</div><pre class='err'>" + html.escape(str(result["error"])) + "</pre>")
        files = [f for f in (result.get("files") or []) if isinstance(f, dict)]
        if files:
            parts.append("<div class='label'>Files</div><ul class='files'>")
            for f in files:
                if f.get("kind") == "image":
                    uri = _data_uri(project, f["path"])
                    parts.append(f"<li>{html.escape(f.get('path', ''))}<br><img src='{uri}' alt='{html.escape(f.get('name', ''))}'></li>" if uri else f"<li>{html.escape(f.get('path', ''))} (missing)</li>")
                else:
                    parts.append(f"<li>{html.escape(f.get('path', ''))}</li>")
            parts.append("</ul>")
        code = result.get("code") or (text if kind == "code" else "")
        if code:
            parts.append(f"<details><summary class='label' style='cursor:pointer'>Code ({html.escape(str(result.get('language') or cell.get('language') or ''))})</summary><pre><code>" + html.escape(str(code)) + "</code></pre></details>")
    parts.append("<footer>Patchbook. The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).</footer></body></html>")
    return "\n".join(parts)


def register(api):
    @api.route("/<pid>/<nid>", methods=["GET"])
    def export(pid, nid):
        fmt = request.args.get("format", "md")
        project = api.project_path(pid)
        book = api.projects.get_patchbook(pid, nid)
        name = _slug(book.get("name"))
        if fmt == "ipynb":
            body = json.dumps(to_ipynb(book, project), indent=1, ensure_ascii=False)
            mime, ext = "application/x-ipynb+json", "ipynb"
        elif fmt == "html":
            body, mime, ext = to_html(book, project), "text/html; charset=utf-8", "html"
        else:
            body, mime, ext = to_markdown(book, project), "text/markdown; charset=utf-8", "md"
        if request.args.get("save") == "1":
            target = os.path.join(project, f"{name}.{ext}")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(body)
            from flask import jsonify
            return jsonify({"ok": True, "path": os.path.relpath(target, project).replace(os.sep, "/")})
        return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})
