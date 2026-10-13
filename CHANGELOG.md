# Changelog

## 3.0260901

First public release of Patchbook as a standalone application on the iTailor library.

- A notebook of patches in plain language; iTailor writes the code, runs it on this computer, reads the real result, repairs what breaks and shows what it found, with the files it produced.
- Startup screen, step-by-step first-run setup, project manager, two looks (Simple and Professional), every panel switchable from the View menu, flat icons only.
- Patch, note and code cells; quick, thorough and ask engines; an effort bar that sets how far Patchbook goes: repair, a different approach that knows what failed, a step-by-step plan, a different plan, and asking you.
- Tasks that need a program (a compiler, LaTeX, a converter) switch to the approach that can locate, install (with your permission) and run it; acceptance checks verify on disk that a run produced what the task asked for.
- Permission questions with a recommendation from iTailor's risk assessment, an option to answer clear cases automatically, and "don't ask again for this kind in this project".
- Live progress in plain language: approach, stage, the program running right now with its output and warnings, every program run, and an Activity record per project for review.
- A shared store on disk for values, parameters and methods between patches and languages, mirrored into iTailor's project knowledge graph.
- Files panel with multi-selection, copy, move, rename, duplicate, delete, an in-app text editor, opening with the default program, zip downloads.
- Export of a Patchbook as Markdown, Jupyter notebook or a self-contained web page.
- Plugins: Environment, Models, Runs, Lessons, Project graph, Shared store, Activity, Export, Example patches.
- Settings with a reset to defaults; everything the user makes stays under `data/`, so the folder can be copied to another computer as it is.
