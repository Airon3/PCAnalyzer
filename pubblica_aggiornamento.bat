@echo off
REM Pubblica una nuova versione su GitHub (serve Git installato)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python non trovato: installalo da python.org spuntando "Add python.exe to PATH".
  pause
  exit /b 1
)
python tools\pubblica.py
if errorlevel 1 pause
