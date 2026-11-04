# 11. Windows 배포 패키지 (작성만, 실행 금지)

## 배포 형태
1. **포터블(설치 없음)**: PyInstaller onedir 결과 폴더를 zip으로 묶음. 압축 풀고 `CorkWalkway.exe` 실행
2. **설치본(간단 설치)**: Inno Setup 스크립트(`installer.iss`)
   - 사용자 단위 설치(`PrivilegesRequired=lowest`, 관리자 권한 불필요)
   - 바탕화면·시작 메뉴 바로가기, 제거 프로그램 등록

## PyInstaller (`build.spec`)
- onedir 기본(onefile은 주석으로만): 시작이 빠르고 백신 오탐이 적음
- `console=False`, 아이콘 `assets/app.ico`, 버전 정보 `assets/version_info.txt`
- 포함 데이터: `models/`, `materials/`, `assets/`, `config.yaml`
- onnxruntime·OpenCV·PySide6 플러그인(멀티미디어 포함) 누락 여부를 `hiddenimports`/`collect_*`로 처리
- 실행 시 리소스 경로: `sys._MEIPASS`와 exe 폴더 모두 확인

## `build_windows.bat` (내용만 작성)
1. Python 3.11 확인 → 2. 가상환경 생성 → 3. `pip install -r requirements.txt` → 4. `pytest` → 5. `pyinstaller build.spec` → 6. zip 생성 → 7. (Inno Setup 설치 시) `iscc installer.iss`

## README에 넣을 빌드 후 확인 목록
- [ ] exe 더블클릭 실행, 콘솔 창 없음
- [ ] 파이썬이 없는 다른 PC에서 실행
- [ ] 카메라 촬영 동작(카메라 있는 기기)
- [ ] `models/` 인식(자동 마스크 동작)
- [ ] 한글 사용자명·한글 경로 PC에서 실행
- [ ] 서명되지 않은 exe는 Windows SmartScreen 경고가 뜰 수 있음 → 코드 서명 인증서 적용 방법 안내

## 완료 기준
- [ ] spec, bat, iss 파일 작성(실행하지 않음)
- [ ] README 빌드 절차·확인 목록 작성
