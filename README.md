# Patchbook 3.0260901

**Write what you want in plain language. iTailor writes the code, runs it on your computer, reads the real result, repairs what breaks and shows you what it found.**

Patchbook is a local application: a small web server that runs on your own computer and opens in your browser. Nothing is sent anywhere except to the model service you choose. A Patchbook is a notebook of *patches*: each patch is one instruction, for example *"Plot the price distribution of data/products.csv as a histogram and save it as price_hist.png"*.

Copyright (c) 2026 Michael Bidollahkhani. MIT License. The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).

## Download and start

1. Get the folder: `git clone git@github.com:michaelkhany/patchbook.git`, or download the ZIP from GitHub (Code > Download ZIP) and unpack it. On Windows keep it at a short path, for example `C:\Patchbook`.
2. Make sure Python 3.10 or newer is installed (`python --version`; on Windows tick "Add python.exe to PATH" in the installer).
3. Start it:

| | |
| --- | --- |
| **Windows** | double-click `start.bat` |
| **macOS / Linux** | `./start.sh` (or `bash start.sh`) |
| by hand | `python -m pip install -r requirements.txt` then `python app.py` |

The start scripts install Flask, the only package Patchbook needs, if it is missing, and open the browser on `http://127.0.0.1:5100`. Keep the terminal window open while you work; closing it stops Patchbook. Nothing is installed anywhere else on the computer: the folder is the application, and what you make goes into its `data/` subfolder.

The first time, Patchbook asks a few questions (name, look, where projects go, which model, what it may do without asking) and can create a **sample project** with a small dataset and example patches. Everything can be changed later in **Settings**, and Settings has a **Reset** tab that brings everything back to the first start.

## Copying it to another computer

The whole folder is self-contained: copy it, start it. It contains its own copy of the iTailor library (`itailor/`), all browser libraries (`static/vendor/`, no internet needed), the plugins and, under `data/`, everything you made: configuration, the remembered model key, your projects. Copy the folder without `data/` to give someone a fresh Patchbook; copy it with `data/` to move your own work.

`sync_itailor.py` refreshes the library copy from `../itailor/itailor` when the library changes (`python sync_itailor.py --check` only reports).

## The screen

- **Menu bar**: File (projects, Patchbooks, files, settings), Edit (cells), View (look, theme, every panel on or off), Run, Tools (plugins), Help.
- **Left**: **Files**, the project folder. Drop files there to add data. (Professional look: **Outline**, every cell at a glance.)
- **Middle**: the open **Patchbook**. Tabs for every Patchbook of the project; a toolbar with Run all and Stop; the cells.
- **Right**: **Progress**, what iTailor does right now in plain language, with its questions. (Professional look: **Events**, the raw event stream; **Environment**, **Models**, **Runs**, **Lessons**, **Project graph** from plugins.)
- **Status line**: open project, what is happening, which model answers, which look.

Every panel can be hidden with its close button or from the View menu, and the right and left docks remember their panels per look.

### The Files panel

Click selects, `Ctrl`+click adds to the selection, `Shift`+click selects a range, `Ctrl`+`A` selects everything shown. Double-click opens a file (images, tables, Markdown, code, text). Right-click, or the dots at the end of a row, shows what you can do with the selection:

- **Open**, **Edit as text** (an editor inside Patchbook, `Ctrl`+`S` saves), **Open with the default program** of this computer, **Show in folder**
- **Copy path** / **Copy relative path**
- **Rename**, **Duplicate**, **Copy to…** and **Move to…** another folder of the project (a new folder can be named on the spot), **Download** (several items or a folder arrive as a zip), **Delete** (`Delete` key works too)
- on a folder: **Add files here**, **New folder here**, **New text file here**

Patchbook's own files (`patchbook-project.json`, `patchbooks/`, `.itailor/`) are never shown or touched there.

### Two looks

| | Simple | Professional |
| --- | --- | --- |
| for | everyone; new users | people who want to see and control the mechanism |
| cells | patches and notes | plus code cells (run as written, no model) |
| run | one engine (quick, by default) | engines per patch: quick / thorough / ask; language; permission mode |
| panels | Files, Progress | plus Outline, Events, Environment, Models, Runs, Lessons, Project graph |
| settings | general, model, permissions, panels, reset | plus Advanced: sandbox, tool calling, timeouts, budgets |

Switch with the button at the top right or in View > Look.

### Cells

- **Patch**: plain language. **Run** sends it to iTailor. Under the cell: the answer or printed result, the files produced (images shown inline), a "Show the code" link, and what went wrong if it failed.
- **Note**: Markdown text that documents the work. Double-click to edit.
- **Code** (Professional): a script you write yourself, run as it is.

Patches run in order and are told what the earlier patches produced, so a later patch can say *use the merged table from above*. A cell edited after it ran shows "Edited since last run".

Shortcuts: `Ctrl+Enter` run · `Shift+Enter` run and move on · `Ctrl+S` save · `Ctrl+Alt+N` new Patchbook · `Ctrl+,` settings.

### Effort and approaches

iTailor's engines each stop on their own rule: the quick engine stops when the same failure comes back unchanged (a fixed point), the goal loop when its budgets are spent. Patchbook sits above them and decides what to try next. The **Effort** bar in the toolbar (per Patchbook; a default in Settings) sets how far that goes:

| Effort | Approaches, in order | Asks you |
| --- | --- | --- |
| Low | one script with a few repairs | no |
| Normal | the script; then a different approach that is told what failed and why | no |
| High | then a step-by-step plan with verified steps | once, if still stuck |
| Maximum | then a second plan that knows what failed | up to three rounds: you give a hint, it tries the whole chain again |

Every approach gets the evidence of the earlier ones (the error, the error output, the start of the code) and is told not to repeat them. When all approaches at that effort fail, Patchbook asks you inside the cell: type a hint or stop. The result lists every approach tried with its outcome. In the Professional look a cell can also be run with a chosen effort or engine from its menu.

Two rules apply at every effort level:

- **A task that needs a program** (a compiler, LaTeX, a converter, a command-line tool) cannot be done by the one-script approach, whose sandbox cannot start other programs. The script is asked to say so (`NEEDS_EXTERNAL_PROGRAM: <name>`) instead of working around it, and iTailor's own refusal counts as the same signal. Patchbook then switches straight to the step-by-step approach, which can locate the program, install it with your permission (language packages through the Install tool, applications through the platform's package manager via the Shell tool), run it, and verify the output.
- **A clean exit is not proof.** Before a one-script run, the model is asked what files the task must produce (as patterns, for example `*.pdf`); Patchbook verifies on disk that such a file was created or updated by the run. A run that exits cleanly without producing them is repaired, and if repairs stop helping it counts as failed, so the next approach starts. The checks appear in the result.

Nothing in this is specific to a program or a file type. The "needs a program" signal is the script's own marker or the library's classification of the refusal (Patchbook verifies at start-up that the library copy still uses the wording it recognises and warns otherwise); install hints come from the library's own per-system table; the acceptance checks come from the model's reading of the task and are verified by Patchbook. The effort table can be adjusted in `data/config.json` under `effortOverrides`, for example `{"high": {"quickIters": 12, "minutes": 60, "budgets": {"replans": 5}}}`.

### Files: what running code may do

Code runs in the project folder as the working directory. It may read any file there, create new files and change existing ones; the Files panel refreshes after every run and the result lists what was produced or changed. Writes outside the project folder are refused by iTailor's guard (the sandbox setting), and network access is allowed unless the sandbox is set to strict. Patchbook's own files (`patchbook-project.json`, `patchbooks/`, `.itailor/`) are never offered to the model.

### The shared store

Within one script, values live in memory. Between patches, and between languages, they go through the project's `shared/` folder:

```
shared/<name>.csv|json|txt   a value for later patches (tables as CSV, results as JSON, text as .md/.txt)
shared/<name>.meta.json      optional: {"description": "...", "language": "..."}
shared/params.json           small named parameters, one flat JSON object
shared/methods/<name>.<ext>  a reusable function or script; its first lines say how to call it:
                             # call: clean_names(df) -> df
                             # description: lower-cases and de-duplicates column names
```

After every run Patchbook scans the folder and keeps the registry in `shared/state.json` (name, kind, file, language, how to call, description, which patch and run produced it). The registry is mirrored into iTailor's project knowledge graph (`.itailor/graph.yaml`) as `shared` nodes linked to the runs, the **Shared store** panel shows it, and a compact view goes into every prompt, so a later patch in any language knows what exists, where it is and how to use it instead of recomputing it.

### When iTailor asks

Reading your files and running code inside the project are always allowed. Installing a package, a command that changes something, network access: these pause the patch and ask inside the cell and in the Progress panel, with the exact action. **Allow once**, **Always in this run**, or **Don't allow**. No answer within the time limit counts as "Don't allow". The Permissions setting chooses how much is asked.

Every question carries a **recommendation**, for example "Recommended: Allow once, low risk, reversible, inside the project". It is read from iTailor's own risk assessment of the action (likelihood and impact from reversibility, blast radius, data sensitivity, egress and cost) and from your earlier answers to similar questions; the recommended button is the highlighted one. Two ways to be asked less:

- **Answer clear cases for me** (Settings > Permissions, or the Run menu): low-risk actions are allowed and very risky ones refused without asking, and the Progress panel says what was decided and why. You are still asked when the risk is high or unclear, and iTailor's questions about the goal itself always reach you.
- **Don't ask again for this kind in this project**, a box on the question card: adds a standing allow rule in the library's own form (for example `Shell(git:*)`) to the project's `.itailor/settings.json`, so that kind is not asked again there. The Lessons panel shows the rules iTailor would propose from your "always" answers.

### Following what runs, and reviewing it later

While a patch runs, the cell and the Progress panel show the approach in use, the stage (which moves back to "Writing code" during a repair), the program or script running right now with how long it has been going, its last output lines and any warning or error lines, and, below, every program run so far with its outcome. A result left from an earlier run stays visible but dimmed and labelled "Previous result" until the new one replaces it.

After every run Patchbook writes one record to `<project>/.patchbook/activity.jsonl`: when, which cell, model and effort, the approaches tried, every program, script, installation and application used with its outcome, the permission decisions and who made them (you, a rule, or the automatic answer), the files produced, and the warning and error counts. The **Activity** panel lists these records for review; the raw transcripts remain in the Runs panel.

### Engines (Professional)

| Engine | What happens |
| --- | --- |
| **Quick** (default) | one script is written, run, read back and repaired until it works; its printed summary is the result |
| **Thorough** | the goal is understood and planned; each step runs with tools and is verified; a report is written under `.itailor/runs/` |
| **Ask** | one conversational answer; it may read files or run something to answer |

## Models

Any OpenAI-compatible service works: a local server (Ollama, LM Studio, llama.cpp, vLLM, found automatically) or a hosted one (address and key). The key is stored only on this computer, in `data/secrets.json`, if you tick "remember". With no model connected Patchbook uses the **demo model**, which gives no real answers; it only lists the files of the project so every button can be tried.

## Where things are

```
patchbook/
  app.py                 start here (python app.py)
  start.bat, start.sh    one-click start
  patchbook/             the application (Flask): config, projects, runs, plugins, API
  itailor/               the iTailor library copy (sync_itailor.py)
  plugins/               plugins; each folder: plugin.json, optional server.py and client.js
  static/, templates/    the browser user interface; static/vendor holds the open-source libraries
  data/                  created on first start: config.json, secrets.json, itailor-home/, projects/
```

A project folder:

```
<project>/
  patchbook-project.json   name and dates
  patchbooks/*.pbk.json    the Patchbooks (cells and results)
  data/                    your files (any file anywhere in the folder is fine)
  ITAILOR.md               what iTailor is told about the project at the start of every run
  .itailor/                iTailor: runs/ (reports, plans, transcripts), graph.yaml, lessons.jsonl, settings.json
```

Environment variables: `PATCHBOOK_PORT` (5100), `PATCHBOOK_HOST` (127.0.0.1), `PATCHBOOK_HOME` (the data folder), `PATCHBOOK_NO_BROWSER=1`.

**Windows note:** keep the Patchbook folder at a short path (for example `C:\Patchbook`). iTailor creates deep run folders inside each project, and Windows refuses paths longer than 260 characters unless long paths are enabled. Patchbook warns at start when the projects folder path is long.

## Plugins

A plugin is a folder under `plugins/` with a `plugin.json`:

```json
{ "id": "my-panel", "name": "My panel", "version": "1.0", "description": "One sentence shown on the startup screen.",
  "kind": "panel", "icon": "box", "looks": ["professional"], "dock": "right", "order": 80,
  "server": "server.py", "client": "client.js" }
```

- `kind`: `panel` (a dockable panel), `tool` (an entry in the Tools menu) or `section`.
- `server.py` (optional) defines `register(api)`; `api.route("/<pid>")` adds routes under `/api/plugins/<id>/`; `api.projects`, `api.config`, `api.runs` give access to Patchbook's services.
- `client.js` (optional) runs in the browser and calls `Patchbook.plugins.register({ id, panel: { render(body, panel, ctx) }, tool: { label, run(ctx) } })`. `ctx` offers `api`, `ui` (dialogs, toasts, Markdown), `notebook`, `files`, `project()`, `patchbook()`.

The startup screen lists every plugin; a broken one is reported and skipped.

## Development

```
python sync_itailor.py          refresh the library copy
python app.py                   start
```

The backend is plain Flask with JSON and server-sent events; the front end is plain JavaScript (no build step). Third-party components are listed in `THIRD_PARTY_NOTICES.md`.
