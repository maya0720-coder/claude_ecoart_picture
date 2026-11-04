# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 현재 상태

아직 소스 코드는 없고 **개발 지시서(스펙)만** 있다. 만들 프로그램은 "코르크 산책로 시공 예상도" Windows 데스크톱 앱이다. 영업 담당자가 현장 흙길 사진을 찍으면 흙길만 코르크 포장으로 바꾼 예상도를 만든다.

- `files/cork_walkway_dev/`가 실제 프로젝트 루트다. 코드는 이 폴더 안에 `00_project_setup.md`의 폴더 구조대로 만든다(`app/`, `tests/`, `config.yaml` 등).
  - 이 폴더에는 자체 `CLAUDE.md`(MAIN.md를 읽으라는 지시만 있음)와 `.claude/settings.json`(Ponytail 플러그인 등록)이 있다. 명령은 이 폴더에서 실행한다.
- `files.zip`, `files/cork_walkway_dev.zip`, `files/S0_ponytail_skill.md`는 같은 스펙의 사본이다. 이 파일들은 고치지 않는다. 정본은 `files/cork_walkway_dev/` 안의 파일이다.

## 작업 방식 (스펙에서 정한 규칙)

1. `files/cork_walkway_dev/MAIN.md`(총괄 지시서)를 먼저 읽는다.
2. 구현 순서는 **S0 → 0 → 1 → 2 → 3 → 4 → 5 → 6 → 10 → 7 → 8 → 9 → 11 → 12**로 고정이다. 번호순과 다르다: 보안(10)을 Gemini(7)보다 먼저 한다.
3. 모듈마다 MD를 끝까지 읽는다. "인터페이스"에 적힌 이름과 시그니처를 그대로 따른다. 구현한 뒤 pytest를 돌리고 MAIN.md 5장 형식으로 `[모듈 n 완료 보고]`를 낸다. 테스트가 실패하거나 완료 기준을 못 채우면 다음 모듈로 넘어가지 않는다.
4. S0: Ponytail 스킬(`DietrichGebert/ponytail`)의 설치를 확인하고 훅·스크립트를 보안 점검한다. 설치 명령은 사용자 승인을 받은 뒤에 실행한다. 모든 설치 방법이 실패하면 Ponytail 없이 진행할지 사용자에게 묻는다.
5. 규칙 우선순위: MAIN.md·모듈 MD > Ponytail. 검증·보안·테스트·오류 처리·한글 경로 처리는 Ponytail을 이유로 줄이지 않는다. 의존성을 새로 추가하면 필요한 이유를 완료 보고에 한 줄로 적는다.

## 명령 (구현 후, `files/cork_walkway_dev/`에서)

- 앱 실행: `python -m app.main`
- 전체 테스트: `pytest` / 단일 테스트: `pytest tests/test_compositor.py::test_name`
- 성능 측정: `python tests/bench.py` (12MP 합성 이미지로 단계별 시간을 재고 MAIN.md 6장 목표와 비교)
- **빌드 금지**: `build.spec`, `build_windows.bat`, `installer.iss`는 작성만 한다. `pyinstaller`, `iscc`, bat 파일은 실행하지 않는다. 빌드는 사용자가 직접 한다.

## 아키텍처 개요

Python 3.11 + PySide6, 오프라인 우선 파이프라인. 모든 단계가 `app/models.py`의 `WorkSession` dataclass 하나를 주고받는다.

```
image_io(EXIF 보정) → segmentation(SAM 계열 ONNX, 터치 점 → mask)
  → perspective(길 4점 quad) → cork_material(프리셋 텍스처)
  → render_local(원근 투영 + LAB 명암 유지 + 색 맞춤 → 길 영역 레이어)
  → compositor(feather 알파 합성 + 마스크 밖 무변경 검증)
  → [선택] ai/gemini_hq(크롭 전송 → align.py로 정렬 → compositor로 재합성·재검증)
  → export(비교 이미지·PDF, 워터마크)
```

- **핵심 불변식**: 길 마스크 바깥 픽셀은 원본과 100% 같아야 한다. `verify_outside_unchanged`가 통과하지 못한 결과는 버린다(저장·프레젠테이션 불가). Gemini 결과도 반드시 같은 compositor를 거친다. 최종 합성은 원본 해상도에서 하고, 미리보기는 축소본으로 렌더한다.
- **Gemini는 기본 꺼짐**이고 실패하면 로컬 결과로 돌아간다. 실행 중에는 Claude API를 쓰지 않는다. 전송은 `security/privacy.prepare_for_send`(EXIF 제거, 길 주변 크롭, 축소)를 거친 인라인 바이트만 허용한다. Files API·컨텍스트 캐싱·대화 세션·그라운딩은 금지이고, 정적 검사 테스트로 확인한다. 네트워크 대상은 `generativelanguage.googleapis.com` 하나뿐이다.
- **모델 파일이 없어도** 동작해야 한다. segmentation은 수동 브러시·다각형 도구로 대신하고, Gemini는 버튼을 비활성화하고 사유를 표시한다.
- 무거운 작업(인코더, 렌더, Gemini 호출)은 `QThreadPool`/`QRunnable`로 돌리고 UI 스레드를 막지 않는다. 프리셋을 바꿀 때 2초 안에 반영되도록 remap 좌표맵을 캐시한다.

## 자주 틀리는 전역 규칙

- 한글 경로: `cv2.imread`/`imwrite` 대신 `np.fromfile + cv2.imdecode`, `cv2.imencode + tofile`을 쓴다.
- 원본 사진 파일을 덮어쓰지 않는다. 원본에 없는 사물을 만들지 않는다.
- 결과물에는 "가상 시공 예상도 — 실제 시공 결과와 다를 수 있음" 표기를 기본으로 넣는다.
- API 키는 `keyring`(Windows 자격 증명 관리자)에만 저장한다. 화면에서는 마스킹하고 로그에 남기지 않는다. 로그에 이미지, base64, API 응답 원문을 넣지 않는다.
- 존재가 불확실한 라이브러리·함수·모델은 쓰지 않는다. 확실하지 않으면 `# 확인 필요:` 주석을 달고 대안을 적는다. Gemini 모델명은 공식 문서에서 확인한 뒤 `config.yaml`에 넣는다.
- 테스트 이미지는 코드로 만든다: 초록 배경 + 갈색 사다리꼴 길 + 그림자 띠 + 길 위 회색 원형 물체.
