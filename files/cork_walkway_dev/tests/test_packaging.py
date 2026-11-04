"""배포 스크립트 정적 점검(모듈 11). 빌드는 실행하지 않는다."""
from pathlib import Path

import app

ROOT = Path(__file__).resolve().parent.parent


def test_spec_valid_and_complete():
    src = (ROOT / "build.spec").read_text(encoding="utf-8")
    compile(src, "build.spec", "exec")
    assert "console=False" in src
    assert "exclude_binaries=True" in src                          # onedir 기본
    assert "# exe = EXE(pyz, a.scripts, a.binaries" in src        # onefile은 주석으로만
    for d in ('"config.yaml"', '"materials"', '"assets"', '"models"'):
        assert d in src, d
    for h in ("onnxruntime", "keyring.backends.Windows", "PySide6.QtMultimedia", "certifi"):
        assert h in src, h
    assert (ROOT / "assets" / "app.ico").is_file()
    assert (ROOT / "assets" / "version_info.txt").is_file()


def test_version_consistent():
    v = app.__version__
    txt = (ROOT / "assets" / "version_info.txt").read_text(encoding="utf-8")
    nums = tuple(int(x) for x in v.split("."))
    assert f"filevers=({nums[0]}, {nums[1]}, {nums[2]}, 0)" in txt
    assert f"prodvers=({nums[0]}, {nums[1]}, {nums[2]}, 0)" in txt
    assert txt.count(f"'{v}'") == 2
    iss = (ROOT / "installer.iss").read_text(encoding="utf-8-sig")
    assert f'#define AppVersion "{v}"' in iss


def test_bat_steps_in_order():
    raw = (ROOT / "build_windows.bat").read_bytes()
    assert raw.isascii()                                           # cmd.exe에서 글자 깨짐 방지
    assert raw.count(b"\n") == raw.count(b"\r\n")                  # CRLF 줄바꿈
    s = raw.decode()
    order = ["3.11", "-m venv", "pip install -r requirements.txt", "-m pytest", "PyInstaller build.spec",
             "Compress-Archive", "installer.iss"]
    pos = [s.index(k) for k in order]
    assert pos == sorted(pos)
    assert "exit /b 1" in s[s.index("-m pytest"):s.index("PyInstaller build.spec")]   # 테스트 실패 시 중단


def test_installer_user_level():
    raw = (ROOT / "installer.iss").read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"                             # UTF-8 BOM(한글)
    lines = raw.decode("utf-8-sig").splitlines()
    assert "PrivilegesRequired=lowest" in lines                    # 관리자 권한 불필요
    s = "\n".join(lines)
    assert "{autopf}" in s and "{autodesktop}" in s and "{group}" in s
    assert 'Source: "dist\\CorkWalkway\\*"' in s
    assert "UninstallDisplayName" in s


def test_readme_covers_required_sections():
    r = (ROOT / "README.md").read_text(encoding="utf-8")
    first = r.split("\n\n")[1]
    assert "회사 정보보호 규정과 고객 동의" in first                  # 첫머리 고지(모듈 10)
    for k in ("설치", "사용 방법", "빌드", "빌드 후 확인 목록", "데이터 처리", "알려진 한계", "사용 도구",
              "SmartScreen", "현장 점검표", "Vertex AI 무보관"):
        assert k in r, k
