@echo off
rem Build local-models-kit.exe from the manager source, in this repo.
rem
rem Run this from anywhere; the script changes to the repo root
rem (the parent of the installer folder it lives in) first.
rem
rem Prerequisite, once:  pip install pyinstaller
rem Python 3.10 or later. The build takes a minute or two.
rem
rem Output: dist\local-models-kit.exe in the repo root. The EXE is the
rem exact manager in installer\manager\local_models_kit_manager.py,
rem compiled; the .py stays the auditable source. The EXE is
rem unsigned, so a downloaded copy can draw a Windows SmartScreen
rem prompt; a copy you build yourself with this script does not
rem carry a download mark. See installer\README.md.

setlocal
cd /d "%~dp0.."

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is not installed for this Python.
    echo Run:  pip install pyinstaller
    exit /b 1
)

python -m PyInstaller --onefile --name local-models-kit --distpath dist installer\manager\local_models_kit_manager.py
if errorlevel 1 (
    echo Build failed; see the PyInstaller output above.
    exit /b 1
)

echo.
echo Built: %CD%\dist\local-models-kit.exe
endlocal
