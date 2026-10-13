# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Web tools: DuckDuckGo search (no API key, no account) and page fetch, used to
look up an API or an error message rather than guessing. From DAYA's
``agent_tools.web_search`` and Patch Code's ``web.js``.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; iTailor/0.1; +https://github.com/)"
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?', re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", text or ""))).strip()


def _unwrap_redirect(url: str) -> str:
    if "duckduckgo.com/l/" not in url:
        return url
    query = urllib.parse.urlparse(url if not url.startswith("//") else "https:" + url).query
    target = urllib.parse.parse_qs(query).get("uddg", [])
    return urllib.parse.unquote(target[0]) if target else url


def fetch_text(url: str, *, data: bytes | None = None, timeout: float = 20.0, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "identity", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        content_type = str(response.headers.get("content-type") or "")
        status = response.status
    try:
        text = raw.decode(charset, "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
    return {"status": status, "ok": 200 <= status < 300, "text": text, "contentType": content_type}


def search(query: str, *, max_results: int = 6, timeout: float = 20.0) -> dict:
    text = str(query or "").strip()
    if not text:
        return {"success": False, "query": "", "results": [], "error": "No search query was given."}
    max_results = max(1, min(int(max_results or 6), 10))
    results, error = [], None
    try:
        body = urllib.parse.urlencode({"q": text}).encode("utf-8")
        page = fetch_text("https://html.duckduckgo.com/html/", data=body, timeout=timeout,
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        for match in _RESULT_RE.finditer(page["text"]):
            url = _unwrap_redirect(html.unescape(match.group("url") or ""))
            if url.startswith("//"):
                url = "https:" + url
            title = _clean(match.group("title"))
            if not url or not title:
                continue
            results.append({"title": title, "url": url, "snippet": _clean(match.group("snippet") or "")[:400]})
            if len(results) >= max_results:
                break
    except urllib.error.HTTPError as exc:
        error = f"DuckDuckGo returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        error = f"Could not reach DuckDuckGo: {getattr(exc, 'reason', exc)}"
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    abstract = ""
    try:
        instant = fetch_text("https://api.duckduckgo.com/?" + urllib.parse.urlencode(
            {"q": text, "format": "json", "no_html": 1, "skip_disambig": 1}), timeout=min(timeout, 10))
        data = json.loads(instant["text"])
        abstract = str(data.get("AbstractText") or data.get("Answer") or "")[:600]
    except Exception:  # noqa: BLE001
        abstract = ""
    return {"success": bool(results or abstract), "query": text, "abstract": abstract, "results": results,
            "error": None if (results or abstract) else (error or "No results were found.")}


def html_to_text(markup: str) -> str:
    s = str(markup or "")
    s = re.sub(r"<script[\s\S]*?</script>", " ", s, flags=re.I)
    s = re.sub(r"<style[\s\S]*?</style>", " ", s, flags=re.I)
    s = re.sub(r"<!--[\s\S]*?-->", " ", s)
    s = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr|/pre)>", "\n", s, flags=re.I)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    return "\n".join(line for line in (re.sub(r"\s+", " ", l).strip() for l in s.split("\n")) if line)


def fetch_page(url: str, *, max_chars: int = 12000, timeout: float = 20.0) -> dict:
    target = str(url or "").strip()
    if not re.match(r"^https?://", target, re.I):
        return {"success": False, "url": target, "error": "Only http(s) URLs can be fetched."}
    try:
        page = fetch_text(target, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return {"success": False, "url": target, "status": exc.code, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "url": target, "error": f"Could not fetch: {exc}"}
    is_html = "html" in page["contentType"].lower() or page["text"].lstrip().startswith("<")
    text = html_to_text(page["text"]) if is_html else page["text"]
    limit = max(500, min(int(max_chars or 12000), 60000))
    return {"success": True, "url": target, "status": page["status"], "contentType": page["contentType"],
            "truncated": len(text) > limit, "text": text[:limit]}
