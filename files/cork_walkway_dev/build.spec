# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 빌드 설정 (모듈 11). 실행: build_windows.bat (사용자가 검토 후 직접 실행)
#
# - onedir(폴더형) 기본: 시작이 빠르고 백신 오탐이 적다.
# - 리소스(models/, materials/, assets/, config.yaml)는 _internal 폴더에 들어간다.
#   exe 옆에 같은 이름의 파일·폴더를 두면 그것이 먼저 쓰인다(app/config.py resolve_resource).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH)
APP_NAME = "CorkWalkway"

datas = [
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "materials"), "materials"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "models"), "models"),              # ONNX 모델(없으면 수동 도구로 동작)
]
datas += collect_data_files("certifi")             # HTTPS 인증서(Gemini 고품질 모드)
datas += collect_data_files("pillow_heif")

binaries = []
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("pillow_heif")

hiddenimports = []
hiddenimports += collect_submodules("onnxruntime.capi")
hiddenimports += collect_submodules("google.genai")
hiddenimports += ["keyring.backends.Windows", "win32ctypes.core",   # Windows 자격 증명 관리자
                  "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNetwork"]

excludes = [
    "tkinter", "matplotlib", "pytest", "IPython",
    # 쓰지 않는 큰 Qt 모듈
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtQuick3D", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
]

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                         # onedir
    name=APP_NAME,
    console=False,                                 # 콘솔 창 없음
    icon=str(ROOT / "assets" / "app.ico"),
    version=str(ROOT / "assets" / "version_info.txt"),
    upx=False,                                     # UPX 압축은 백신 오탐을 늘려 끈다
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

# ---- onefile(단일 exe)로 만들려면: 위 exe·coll 대신 아래를 쓴다(시작이 느리고 백신 오탐이 늘 수 있음) ----
# exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=APP_NAME, console=False,
#           icon=str(ROOT / "assets" / "app.ico"), version=str(ROOT / "assets" / "version_info.txt"),
#           upx=False, runtime_tmpdir=None)
