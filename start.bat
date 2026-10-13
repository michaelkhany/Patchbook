@echo off
rem Patchbook - start on Windows. Double-click this file.
rem It uses the Python on this computer (3.10 or newer), installs Flask if it is
rem missing, makes sure the iTailor library copy is present, and starts Patchbook.
setlocal
cd /d "%~dp0"
title Patchbook

set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" (
  where py >nul 2>nul && set PY=py -3
)
if "%PY%"=="" (
  where python >nul 2>nul && set PY=python
)
if "%PY%"=="" (
  echo Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer, then run this file again.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
  echo Patchbook needs Python 3.10 or newer. The Python found here is older.
  %PY% --version
  pause
  exit /b 1
)

%PY% -c "import flask" 2>nul
if errorlevel 1 (
  echo Installing Flask, the only package Patchbook needs...
  %PY% -m pip install --user -q -r requirements.txt
  if errorlevel 1 (
    %PY% -m pip install -q -r requirements.txt
  )
)

if not exist "itailor\__init__.py" (
  echo The iTailor library copy is missing; copying it from ..\itailor ...
  %PY% sync_itailor.py
)

echo.
echo Starting Patchbook. Keep this window open while you use it; close it to stop.
echo.
%PY% app.py
if errorlevel 1 pause
endlocal
