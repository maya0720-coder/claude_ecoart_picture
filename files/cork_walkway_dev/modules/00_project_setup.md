# 00. 프로젝트 기본 구성

## 목적
폴더 구조, 의존성, 설정 파일, 모듈 간 공통 데이터 구조를 만든다.

## 폴더 구조
```
cork_walkway/
├─ CLAUDE.md                     # "MAIN.md를 읽고 따를 것"
├─ MAIN.md
├─ modules/                      # 개발 지시 MD
├─ app/
│  ├─ main.py
│  ├─ config.py                  # config.yaml 로드, 경로 계산
│  ├─ models.py                  # 공통 데이터 구조
│  ├─ core/
│  │  ├─ image_io.py
│  │  ├─ segmentation.py
│  │  ├─ perspective.py
│  │  ├─ cork_material.py
│  │  ├─ render_local.py
│  │  ├─ compositor.py
│  │  └─ export.py
│  ├─ ai/
│  │  ├─ gemini_hq.py
│  │  └─ align.py
│  ├─ security/
│  │  ├─ privacy.py
│  │  └─ secrets.py
│  └─ ui/
│     ├─ main_window.py
│     ├─ canvas.py
│     ├─ compare_view.py
│     ├─ presentation.py
│     └─ settings_dialog.py
├─ materials/cork/               # 코르크 프리셋, 사용자 제품 사진
│  └─ presets.yaml
├─ models/                       # ONNX 모델(README에 다운로드 안내)
├─ assets/ (app.ico, version_info.txt, fonts/)
├─ tests/
├─ .claude/skills/cork-render/SKILL.md
├─ config.yaml
├─ requirements.txt              # 버전 고정
├─ build.spec / build_windows.bat / installer.iss
└─ README.md
```

## 공통 데이터 구조 (`app/models.py`)
```python
@dataclass
class WorkSession:
    original: np.ndarray            # BGR uint8, EXIF 회전 보정 완료, 원본 해상도
    source_name: str                # 표시용 파일명(전송 금지)
    mask: np.ndarray | None         # uint8 0/255, 원본과 같은 크기
    mask_feather_px: int = 3
    quad: np.ndarray | None         # (4,2) float32, 길 원근 4점 (좌하, 우하, 우상, 좌상)
    preset_id: str = "natural_brown"
    render_params: RenderParams = field(default_factory=RenderParams)
    result_local: np.ndarray | None = None
    result_hq: np.ndarray | None = None
    verified: bool = False
```
`RenderParams`: `shading_strength`(0~1, 기본 0.8), `color_match`(0~1, 기본 0.3), `granule_scale`(기본 1.0), `edge_band`(bool), `edge_band_px`(int)

## 의존성 (`requirements.txt`, 개발 시점 안정 버전으로 고정)
PySide6, opencv-python, numpy, Pillow, pillow-heif, onnxruntime, PyYAML, keyring, google-genai(선택 기능), pytest, pyinstaller

## 설정 (`config.yaml`)
- `paths.models`, `paths.materials`, `paths.output_default`
- `segmentation.model`(모델 파일명)
- `render.max_preview_px`(미리보기 긴 변, 기본 1600)
- `gemini.enabled: false`, `gemini.model: ""`(개발 시 공식 문서 확인 후 입력), `gemini.max_send_px: 1536`
- `export.watermark: true`, `export.jpeg_quality: 92`
- 사용자 설정·로그: `%APPDATA%\CorkWalkway\`

## 프로젝트 스킬 (`.claude/skills/cork-render/SKILL.md`)
- 파이프라인 요약, 전역 규칙, 모듈 인터페이스 표, 자주 틀리는 점(한글 경로, 원본 해상도 합성, 스레드)을 정리한다.

## 완료 기준
- [ ] 폴더·빈 모듈 파일 생성, `python -m app.main`으로 빈 창이 뜸
- [ ] `config.yaml` 로드 테스트 통과
- [ ] `WorkSession` 생성·복사 테스트 통과
