# Third-party components shipped with Patchbook

Patchbook's own code is MIT licensed (see LICENSE). The browser user interface
ships these open-source libraries unchanged, under `static/vendor/`, so the
application works without an internet connection:

| Component | Version | License | Used for |
| --- | --- | --- | --- |
| [CodeMirror 5](https://codemirror.net/5/) | 5.65.16 | MIT | the code editor, read-only code views and syntax highlighting (Python, R, JavaScript, shell, Markdown, YAML, SQL, Julia); the `material-darker` theme for dark mode |
| [marked](https://marked.js.org/) | 12.0.2 | MIT | rendering Markdown (answers, notes, reports) |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.1.6 | Apache-2.0 OR MPL-2.0 | sanitising rendered Markdown before it is put on the page |

The icons in `static/js/icons.js` are simple flat stroke icons; their shapes follow the style of, and are partly adapted from, [Feather](https://feathericons.com/) (MIT, Copyright (c) 2013-2023 Cole Bemis).

The iTailor library in `./itailor` is Michael Bidollahkhani's work (MIT). It has
no runtime dependencies. Flask (BSD-3-Clause) is the only Python package Patchbook needs.
