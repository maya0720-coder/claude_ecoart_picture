@echo off
rem ============================================================
rem  CorkWalkway Windows build script (module 11)
rem  Review before running. Steps:
rem   1) check Python 3.11  2) create venv  3) install requirements
rem   4) run tests (stop on failure)  5) PyInstaller (onedir)
rem   6) portable zip  7) Inno Setup installer (only if iscc is installed)
rem  Messages are in English on purpose: cmd.exe can garble UTF-8 text.
rem ============================================================
setlocal
cd /d "%~dp0"

set APP=CorkWalkway
set VENV=.venv-build
set DIST=dist\%APP%

rem ---- 1. Python 3.11 ----
set PY=
where py >nul 2>nul && (py -3.11 -c "import sys" >nul 2>nul && set PY=py -3.11)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>nul && set PY=python
)
if not defined PY (
  echo [ERROR] Python 3.11 was not found. Install it from python.org or: winget install -e --id Python.Python.3.11
  exit /b 1
)
echo [1/7] Python: %PY%

rem ---- 2. venv ----
if not exist "%VENV%\Scripts\python.exe" (
  %PY% -m venv "%VENV%" || (echo [ERROR] venv creation failed & exit /b 1)
)
set VPY=%VENV%\Scripts\python.exe
echo [2/7] venv: %VENV%

rem ---- 3. requirements ----
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt || (echo [ERROR] pip install failed & exit /b 1)
echo [3/7] requirements installed

rem ---- 4. tests ----
"%VPY%" -m pytest -q || (echo [ERROR] tests failed - build stopped & exit /b 1)
echo [4/7] tests passed

rem ---- model check (warning only) ----
if not exist "models\mobile_sam_image_encoder.onnx" (
  echo [WARN] models\*.onnx not found. The app will work with manual brush tools only. See models\README.md
)

rem ---- 5. PyInstaller ----
"%VPY%" -m PyInstaller build.spec --noconfirm --clean || (echo [ERROR] PyInstaller failed & exit /b 1)
if not exist "%DIST%\%APP%.exe" (echo [ERROR] %DIST%\%APP%.exe not created & exit /b 1)
echo [5/7] built: %DIST%\%APP%.exe

rem ---- 6. portable zip ----
for /f %%v in ('"%VPY%" -c "import app;print(app.__version__)"') do set VER=%%v
if not defined VER set VER=0.0.0
powershell -NoProfile -Command "Compress-Archive -Path '%DIST%' -DestinationPath 'dist\%APP%-%VER%-portable.zip' -Force" || (echo [ERROR] zip failed & exit /b 1)
echo [6/7] portable: dist\%APP%-%VER%-portable.zip

rem ---- 7. Inno Setup (optional) ----
set ISCC=
where iscc >nul 2>nul && set ISCC=iscc
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
  %ISCC% /DAppVersion=%VER% installer.iss || (echo [ERROR] Inno Setup failed & exit /b 1)
  echo [7/7] installer: dist\%APP%-%VER%-setup.exe
) else (
  echo [7/7] Inno Setup not installed - installer skipped. https://jrsoftware.org/isinfo.php
)

echo Done. Check the post-build checklist in README.md.
endlocal
