# 00. 프로젝트 기본 구성 (v2)

## 목적
폴더 구조, 의존성, 설정 파일, 모듈 간 공통 데이터 구조를 만든다.

## 폴더 구조
```
cork_walkway/
├─ CLAUDE.md                     # "MAIN.md를 읽고 따를 것"
├─ MAIN.md
├─ modules/                      # 개발 지시 MD
├─ app/
│  ├─ main.py                    # 기본 간편 화면, --classic 이면 단계별 화면
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
│  │  ├─ gemini_convert.py        # (v2) 사진 전체 → Gemini 자동 변환, 바뀐 영역 검출·합성
│  │  ├─ gemini_hq.py             # 공통 클라이언트·오류 분류, 단계별 화면의 고품질 다듬기
│  │  └─ align.py
│  ├─ security/
│  │  ├─ privacy.py
│  │  └─ secrets.py
│  └─ ui/
│     ├─ quick_window.py         # (v2) 간편 화면(기본)
│     ├─ main_window.py          # 단계별 화면(--classic)
│     ├─ workers.py              # 작업 스레드
│     ├─ canvas.py
│     ├─ compare_view.py
│     ├─ presentation.py
│     └─ settings_dialog.py
├─ materials/cork/               # 코르크 프리셋, 사용자 제품 사진
│  ├─ presets.yaml
│  └─ <프리셋 id>/reference.jpg  # (v2) Gemini 참고 사진: 포장면만 잘라낸 회사 시공 사진
├─ models/                       # ONNX 모델(README에 다운로드 안내)
├─ assets/ (app.ico, version_info.txt, fonts/)
├─ tests/
├─ .claude/settings.json         # Ponytail 플러그인 프로젝트 등록 (S0)
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
PySide6, opencv-python, numpy, Pillow, pillow-heif, onnxruntime, PyYAML, keyring, google-genai(**v2: 기본 기능**), pytest, pyinstaller

## 설정 (`config.yaml`)
- `paths.models`, `paths.materials`, `paths.output_default`
- `segmentation.model`(모델 파일명)
- `render.max_preview_px`(미리보기 긴 변, 기본 1600)
- `gemini.enabled: false`(외부 전송 동의 전 꺼짐, 사용자가 [설정]에서 켬), `gemini.model`(공식 문서·실제 키로 확인한 값, 현재 `gemini-nano-banana-2.1`), `gemini.max_send_px: 1536`, `gemini.timeout_s: 60`
- `export.watermark: true`, `export.jpeg_quality: 92`
- 사용자 설정·로그: `%APPDATA%\CorkWalkway\`

## 프로젝트 스킬 (`.claude/skills/cork-render/SKILL.md`)
- 첫 줄에 "Ponytail 규칙 적용, 단 MAIN.md 규칙 우선"을 명시한다.
- 파이프라인 요약, 전역 규칙, 모듈 인터페이스 표, 자주 틀리는 점(한글 경로, 원본 해상도 합성, 스레드)을 정리한다.

## 완료 기준
- [ ] 폴더·빈 모듈 파일 생성, `python -m app.main`으로 간편 화면, `--classic`으로 단계별 화면이 뜸
- [ ] `config.yaml` 로드 테스트 통과
- [ ] `WorkSession` 생성·복사 테스트 통과
