# iTailor - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
"""Install hints per OS for programs iTailor knows, and documented headless modes of applications."""

from __future__ import annotations

import platform
import re

# program -> {os: command}
INSTALL_HINTS = {
    "python": {"windows": "winget install Python.Python.3.12", "darwin": "brew install python", "linux": "sudo apt install python3 python3-pip"},
    "pip": {"windows": "python -m ensurepip --upgrade", "darwin": "python3 -m ensurepip --upgrade", "linux": "sudo apt install python3-pip"},
    "uv": {"windows": "winget install astral-sh.uv", "darwin": "brew install uv", "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh"},
    "conda": {"windows": "winget install Anaconda.Miniconda3", "darwin": "brew install --cask miniconda", "linux": "see https://docs.conda.io/en/latest/miniconda.html"},
    "Rscript": {"windows": "winget install RProject.R", "darwin": "brew install r", "linux": "sudo apt install r-base"},
    "R": {"windows": "winget install RProject.R", "darwin": "brew install r", "linux": "sudo apt install r-base"},
    "node": {"windows": "winget install OpenJS.NodeJS.LTS", "darwin": "brew install node", "linux": "sudo apt install nodejs npm"},
    "npm": {"windows": "winget install OpenJS.NodeJS.LTS", "darwin": "brew install node", "linux": "sudo apt install npm"},
    "java": {"windows": "winget install EclipseAdoptium.Temurin.21.JDK", "darwin": "brew install openjdk", "linux": "sudo apt install default-jdk"},
    "julia": {"windows": "winget install Julialang.Julia", "darwin": "brew install julia", "linux": "curl -fsSL https://install.julialang.org | sh"},
    "go": {"windows": "winget install GoLang.Go", "darwin": "brew install go", "linux": "sudo apt install golang-go"},
    "cargo": {"windows": "winget install Rustlang.Rustup", "darwin": "brew install rustup", "linux": "curl https://sh.rustup.rs -sSf | sh"},
    "rustc": {"windows": "winget install Rustlang.Rustup", "darwin": "brew install rustup", "linux": "curl https://sh.rustup.rs -sSf | sh"},
    "dotnet": {"windows": "winget install Microsoft.DotNet.SDK.8", "darwin": "brew install dotnet", "linux": "sudo apt install dotnet-sdk-8.0"},
    "ruby": {"windows": "winget install RubyInstallerTeam.Ruby.3.3", "darwin": "brew install ruby", "linux": "sudo apt install ruby-full"},
    "perl": {"windows": "winget install StrawberryPerl.StrawberryPerl", "darwin": "brew install perl", "linux": "sudo apt install perl"},
    "lua": {"windows": "winget install DEVCOM.Lua", "darwin": "brew install lua", "linux": "sudo apt install lua5.4"},
    "dart": {"windows": "winget install Google.DartSDK", "darwin": "brew install dart", "linux": "sudo apt install dart"},
    "gcc": {"windows": "winget install MSYS2.MSYS2 (then pacman -S mingw-w64-ucrt-x86_64-gcc)", "darwin": "xcode-select --install", "linux": "sudo apt install build-essential"},
    "g++": {"windows": "winget install MSYS2.MSYS2", "darwin": "xcode-select --install", "linux": "sudo apt install build-essential"},
    "git": {"windows": "winget install Git.Git", "darwin": "brew install git", "linux": "sudo apt install git"},
    "docker": {"windows": "winget install Docker.DockerDesktop", "darwin": "brew install --cask docker", "linux": "sudo apt install docker.io"},
    "apptainer": {"windows": "use WSL2: sudo apt install apptainer", "darwin": "not available natively", "linux": "sudo apt install apptainer"},
    "ssh": {"windows": "Settings > Optional features > OpenSSH Client", "darwin": "included", "linux": "sudo apt install openssh-client"},
    "rsync": {"windows": "winget install cwRsync (or use WSL)", "darwin": "included", "linux": "sudo apt install rsync"},
    "make": {"windows": "winget install GnuWin32.Make", "darwin": "xcode-select --install", "linux": "sudo apt install make"},
    "cmake": {"windows": "winget install Kitware.CMake", "darwin": "brew install cmake", "linux": "sudo apt install cmake"},
    "pandoc": {"windows": "winget install JohnMacFarlane.Pandoc", "darwin": "brew install pandoc", "linux": "sudo apt install pandoc"},
    "quarto": {"windows": "winget install Posit.Quarto", "darwin": "brew install --cask quarto", "linux": "see https://quarto.org/docs/get-started/"},
    "pdflatex": {"windows": "winget install MiKTeX.MiKTeX", "darwin": "brew install --cask mactex-no-gui", "linux": "sudo apt install texlive-latex-base"},
    "soffice": {"windows": "winget install TheDocumentFoundation.LibreOffice", "darwin": "brew install --cask libreoffice", "linux": "sudo apt install libreoffice"},
    "ffmpeg": {"windows": "winget install Gyan.FFmpeg", "darwin": "brew install ffmpeg", "linux": "sudo apt install ffmpeg"},
    "magick": {"windows": "winget install ImageMagick.ImageMagick", "darwin": "brew install imagemagick", "linux": "sudo apt install imagemagick"},
    "gs": {"windows": "winget install ArtifexSoftware.GhostScript", "darwin": "brew install ghostscript", "linux": "sudo apt install ghostscript"},
    "jupyter": {"windows": "python -m pip install jupyter", "darwin": "python3 -m pip install jupyter", "linux": "python3 -m pip install jupyter"},
    "code": {"windows": "winget install Microsoft.VisualStudioCode", "darwin": "brew install --cask visual-studio-code", "linux": "sudo snap install code --classic"},
    "sbatch": {"windows": "Slurm is a cluster scheduler; connect to the cluster with ssh", "darwin": "same", "linux": "same"},
}

# Applications with a documented headless / batch mode: name pattern -> how to drive it.
HEADLESS_MODES = [
    (re.compile(r"libreoffice|soffice|openoffice", re.I),
     "soffice --headless --convert-to pdf <file> (also docx, xlsx, csv, html); --outdir <dir>"),
    (re.compile(r"\bmatlab\b", re.I), "matlab -batch \"script_name\" (no GUI; exit code propagates)"),
    (re.compile(r"\brstudio\b|\bR for Windows\b|^R\b", re.I), "Rscript script.R  /  R -e \"expr\""),
    (re.compile(r"visual studio code|vscode|\bcode\b", re.I), "code --diff a b  /  code --wait file  /  code --list-extensions"),
    (re.compile(r"\bspss\b", re.I), "stats -f syntax.sps -o out.spv (IBM SPSS Statistics batch; path varies)"),
    (re.compile(r"\bstata\b", re.I), "stata -b do script.do  (StataMP: stata-mp -b do)"),
    (re.compile(r"\bsas\b", re.I), "sas -sysin program.sas -log out.log -print out.lst"),
    (re.compile(r"\bexcel\b", re.I), "no headless mode; read/write .xlsx with openpyxl/pandas, or convert with soffice --headless"),
    (re.compile(r"\bword\b|microsoft office", re.I), "no headless mode; use python-docx, or soffice --headless --convert-to"),
    (re.compile(r"\bpowerpoint\b", re.I), "no headless mode; use python-pptx, or soffice --headless --convert-to pdf"),
    (re.compile(r"\binkscape\b", re.I), "inkscape --export-type=png --export-filename=out.png in.svg"),
    (re.compile(r"\bgimp\b", re.I), "gimp -i -b '(script)' -b '(gimp-quit 0)'"),
    (re.compile(r"\bblender\b", re.I), "blender -b scene.blend -P script.py"),
    (re.compile(r"\bimagej\b|\bfiji\b", re.I), "ImageJ --headless -macro macro.ijm"),
    (re.compile(r"\bzotero\b", re.I), "no batch mode; export via the Zotero connector or the local API on port 23119"),
    (re.compile(r"\bgnuplot\b", re.I), "gnuplot -e \"set terminal png; set output 'out.png'; plot ...\""),
    (re.compile(r"\boctave\b", re.I), "octave --no-gui --eval \"...\"  /  octave script.m"),
    (re.compile(r"\bparaview\b", re.I), "pvpython script.py"),
    (re.compile(r"\bchrome\b|\bchromium\b|\bedge\b", re.I), "<browser> --headless --print-to-pdf=out.pdf <url>  /  --screenshot"),
    (re.compile(r"\bffmpeg\b", re.I), "ffmpeg -i in.mp4 -vf scale=... out.mp4"),
    (re.compile(r"\bpandoc\b", re.I), "pandoc in.md -o out.docx"),
    (re.compile(r"\bquarto\b", re.I), "quarto render document.qmd"),
    (re.compile(r"\bjupyter\b", re.I), "jupyter nbconvert --to notebook --execute nb.ipynb"),
    (re.compile(r"\bdocker\b", re.I), "docker run --rm -v \"$PWD\":/work -w /work image cmd"),
]


def os_key() -> str:
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "darwin"
    return "linux"


def install_hint(program: str) -> str:
    table = INSTALL_HINTS.get(program) or INSTALL_HINTS.get(program.lower())
    if not table:
        key = os_key()
        generic = {"windows": f"winget search {program}", "darwin": f"brew search {program}", "linux": f"apt search {program}"}
        return generic[key]
    return table.get(os_key(), "")


def headless_mode(app_name: str) -> str:
    for pattern, how in HEADLESS_MODES:
        if pattern.search(str(app_name or "")):
            return how
    return ""
