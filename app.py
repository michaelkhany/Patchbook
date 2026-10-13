# Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
# The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
"""
Start Patchbook:

    python app.py                      http://127.0.0.1:5100 (opens in your browser)

Environment variables:
    PATCHBOOK_PORT=5100                the port
    PATCHBOOK_HOST=127.0.0.1           bind address (0.0.0.0 to reach it from other computers; think first)
    PATCHBOOK_HOME=./data              where configuration, projects and iTailor's home are stored
    PATCHBOOK_NO_BROWSER=1             do not open a browser window

Patchbook imports the copy of the iTailor library in ./itailor (see sync_itailor.py),
never one installed elsewhere, so the folder works wherever it is copied.
"""

from __future__ import annotations

import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from patchbook import APP_NAME, VERSION, create_app  # noqa: E402

app = create_app()


def main() -> int:
    host = os.environ.get("PATCHBOOK_HOST") or "127.0.0.1"
    port = int(os.environ.get("PATCHBOOK_PORT") or 5100)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    import itailor
    from patchbook import config
    print(f"{APP_NAME} {VERSION}")
    print(f"  iTailor library {itailor.__version__} from {os.path.dirname(os.path.abspath(itailor.__file__))}")
    print(f"  data folder     {config.DATA_DIR}")
    print(f"  open            {url}")
    print("  stop            press Ctrl+C in this window")
    if not os.environ.get("PATCHBOOK_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
