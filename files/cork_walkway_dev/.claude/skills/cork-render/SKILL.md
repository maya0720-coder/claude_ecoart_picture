---
name: cork-render
description: 코르크 산책로 시공 예상도 앱의 파이프라인·전역 규칙·모듈 인터페이스 요약. 이 프로젝트의 app/ 코드를 고치거나 디버깅할 때 사용.
---

# cork-render

**Ponytail 규칙 적용, 단 MAIN.md 규칙 우선.** 검증·보안·테스트·오류 처리·한글 경로 처리는 줄이지 않는다.

## 파이프라인
사진(`image_io`) → 마스크(`segmentation`) → 원근 4점(`perspective`) → 코르크 텍스처(`cork_material`)
→ 로컬 렌더(`render_local`) → 합성·검증(`compositor`) → [선택] Gemini(`ai/gemini_hq` + `ai/align`) → 내보내기(`export`).
모든 단계는 `app/models.py`의 `WorkSession`을 주고받는다.

## 전역 규칙
1. 길 마스크 밖 픽셀은 원본과 100% 같아야 한다. `verify_outside_unchanged`가 통과하지 못하면 결과를 버린다.
2. 원본 파일을 덮어쓰지 않는다. 원본에 없는 사물을 만들지 않는다.
3. "가상 시공 예상도 — 실제 시공 결과와 다를 수 있음" 표기를 기본으로 넣는다.
4. API 키는 `keyring`에만 저장하고 화면에서는 마스킹하며 로그에 남기지 않는다.
5. 외부 전송은 Gemini 고품질 모드(기본 꺼짐)에서 `privacy.prepare_for_send`를 거친 인라인 바이트만 허용한다. Files API·캐싱·세션·그라운딩은 금지.
6. 존재가 불확실한 API는 쓰지 않는다. 필요하면 `# 확인 필요:` 주석과 대안을 적는다.

## 모듈 인터페이스
| 모듈 | 파일 | 핵심 인터페이스 |
|---|---|---|
| 01 | core/image_io.py | `load_image`, `save_image`, `make_preview`, `qimage_to_bgr` |
| 02 | core/segmentation.py | `PathSegmenter(available/set_image/predict)`, `clean_mask`, `feather_alpha` |
| 03 | core/perspective.py | `estimate_quad`, `homography_from_quad`, `plane_size_for` |
| 04 | core/cork_material.py | `CorkPreset`, `load_presets`, `make_tile`, `make_plane_texture` |
| 05 | core/render_local.py | `render_local(session, preset, preview=False)` |
| 06 | core/compositor.py | `composite`, `verify_outside_unchanged` |
| 07 | ai/gemini_hq.py, ai/align.py | `GeminiHQ(available/refine)`, `align_to_original` |
| 09 | core/export.py | `export_result` |
| 10 | security/privacy.py, secrets.py | `prepare_for_send`, `TransferLog`, `cleanup_temp`, `get_key/set_key/mask_key` |

## 자주 틀리는 점
- 한글 경로: `cv2.imread`/`imwrite`는 금지. `np.fromfile + cv2.imdecode`, `cv2.imencode + tofile`을 쓴다.
- 합성은 원본 해상도에서 한다. 미리보기 좌표는 배율로 나눠 원본 좌표로 바꾼다.
- `quad` 점 순서는 좌하, 우하, 우상, 좌상이다.
- 무거운 작업은 `QThreadPool`/`QRunnable`로 돌린다. UI 스레드에서 실행하지 않는다.
