---
name: cork-render
description: 코르크 산책로 시공 예상도 앱의 파이프라인·전역 규칙·모듈 인터페이스 요약(v2: 사진 → Gemini API 자동 변환). 이 프로젝트의 app/ 코드를 고치거나 디버깅할 때 사용.
---

# cork-render

**Ponytail 규칙 적용, 단 MAIN.md 규칙 우선.** 검증·보안·테스트·오류 처리·한글 경로 처리는 줄이지 않는다.

## 파이프라인 (v2)
**간편 화면(기본, `ui/quick_window.py`)**: 사진(`image_io`) → [전송 확인] → `ai/gemini_convert.GeminiConvert.convert`
(사진 전체 축소본 + 자재 참고 사진 → Gemini API) → `merge_edited`(`align` 정렬 → `change_mask` 바뀐 영역 → `compositor.composite_verified`)
→ 전·후 비교 → 내보내기(`export`).

**단계별 화면(보조, `ui/main_window.py`, `--classic`)**: 마스크(`segmentation`) → 원근 4점(`perspective`) → 텍스처(`cork_material`)
→ 로컬 렌더(`render_local`) → 합성·검증(`compositor`) → [선택] Gemini 다듬기(`ai/gemini_hq` + `ai/align`) → 내보내기.

모든 단계는 `app/models.py`의 `WorkSession`을 주고받는다. 간편 화면 결과는 `session.result_hq`, `session.mask`, `session.verified`.

## 전역 규칙
1. 길 마스크 밖 픽셀은 원본과 100% 같아야 한다. Gemini 결과도 `merge_edited`/`composite_verified`를 거치고, 검증 실패 결과는 버린다.
2. 원본 파일을 덮어쓰지 않는다. 원본에 없는 사물을 만들지 않는다.
3. "가상 시공 예상도 — 실제 시공 결과와 다를 수 있음" 표기를 기본으로 넣는다.
4. API 키는 `keyring`에만 저장하고 화면에서는 마스킹하며 로그에 남기지 않는다(`AIza…`·`AQ.…` 모두 로그 필터 대상).
5. 외부 전송은 설정에서 켜고 전송 확인 창에서 승인한 Gemini API 호출만. `privacy.prepare_for_send`를 거친 인라인 바이트, `store=False`. Files API·캐싱·세션·그라운딩 금지. `app/` 코드에 다른 URL·네트워크 모듈 import 금지(정적 검사).
6. 존재가 불확실한 API는 쓰지 않는다. 필요하면 `# 확인 필요:` 주석과 대안을 적는다.
7. 테스트는 실제 Gemini를 호출하지 않는다(`httpx.MockTransport`). Gemini 앱(구독) 자동화·브라우저 자동 조작은 하지 않는다.

## 모듈 인터페이스
| 모듈 | 파일 | 핵심 인터페이스 |
|---|---|---|
| 01 | core/image_io.py | `load_image`, `save_image`, `make_preview`, `qimage_to_bgr` |
| 02 | core/segmentation.py (단계별) | `PathSegmenter(available/set_image/predict)`, `clean_mask`, `feather_alpha` |
| 03 | core/perspective.py (단계별) | `estimate_quad`, `homography_from_quad`, `plane_size_for` |
| 04 | core/cork_material.py | `CorkPreset`, `load_presets`, `make_tile`, `make_plane_texture` / 참고 사진 `materials/cork/<id>/reference.jpg` |
| 05 | core/render_local.py (단계별) | `render_local(session, preset, preview=False)` |
| 06 | core/compositor.py | `composite`, `composite_verified`, `verify_outside_unchanged` |
| 07 | ai/gemini_convert.py | `GeminiConvert(available/prepare_full/convert)`, `merge_edited`, `change_mask`, `build_prompt`, `reference_path` |
| 07 | ai/gemini_hq.py, ai/align.py | `GeminiHQ(available/prepare/refine)`, `HQError`, `SendPackage`, `_api_reason(code, message)`, `align_to_original` |
| 08 | ui/quick_window.py, ui/main_window.py | `QuickWindow(config, runner=None, converter=None)`, `MainWindow` |
| 09 | core/export.py | `export_result` |
| 10 | security/privacy.py, secrets.py | `prepare_for_send`, `TransferLog`, `SendConsent`, `cleanup_temp`, `RedactFilter`, `get_key/set_key/mask_key` |

## 자주 틀리는 점
- 한글 경로: `cv2.imread`/`imwrite`는 금지. `np.fromfile + cv2.imdecode`, `cv2.imencode + tofile`을 쓴다.
- 합성은 원본 해상도에서 한다. Gemini 결과·미리보기 좌표는 배율을 맞춰 원본 크기로 되돌린다.
- 화면의 전송 확인·전송 내역은 변환기(`GeminiConvert`)가 가진 `consent`·`transfer_log`를 쓴다(따로 만들면 어긋남).
- 무료 등급 키는 `429 … free_tier … limit: 0` → `_api_reason`이 "결제 연결" 안내로 분류한다. 자동 재시도하지 않는다(요금).
- `quad` 점 순서는 좌하, 우하, 우상, 좌상이다(단계별 화면).
- 무거운 작업은 `ui/workers.Runner`로 돌린다. UI 스레드에서 실행하지 않는다.
