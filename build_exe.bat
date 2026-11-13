@echo off
REM Crea PCAnalyzer.exe nella cartella dist\PCAnalyzer
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name PCAnalyzer --icon assets\icon.ico --add-data "data;data" --add-data "assets;assets" --collect-all customtkinter main.py
echo.
echo Fatto: dist\PCAnalyzer\PCAnalyzer.exe
pause
