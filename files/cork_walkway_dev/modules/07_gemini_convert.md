# 07. Gemini API 자동 변환 (v2: 기본 기능)

> 먼저 `10_privacy_security.md`의 규칙을 반영한 뒤 구현한다.

## 목적
현장 사진 한 장을 Gemini 이미지 모델로 보내 **흙길만 코르크 포장으로 바꾼 사진**을 받고, 로컬에서 정렬·검증해 **길 밖은 원본과 100% 같은** 원본 해상도 결과를 만든다. 사용자 조작 없이 동작한다(전송 확인 창 제외).

## 방식
- Gemini Developer API(`google-genai` SDK), `models.generate_content` 1회성 호출, `response_modalities=["IMAGE"]`, `store=False`
- 모델명은 `config.yaml`의 `gemini.model`(현재 `gemini-nano-banana-2.1`). 공식 문서와 실제 키 호출로 확인한 값만 넣는다
- 클라이언트: `vertexai=False` 고정, `base_url`은 `https://generativelanguage.googleapis.com`, 재시도 1회(자동 재시도 없음), 요청 시간 제한 `gemini.timeout_s`
- **보내는 것**(모두 인라인 바이트, `privacy.prepare_for_send` 통과)
  1. 현장 사진 **전체**의 축소본(긴 변 `gemini.max_send_px` 이하, EXIF·GPS·파일명 없음)
  2. 자재 참고 사진(있으면): `materials/cork/<프리셋 id>/reference.jpg` — 회사 시공 사진에서 **포장면만** 잘라낸 것(현수막·전화번호·로고 제외), 긴 변 1024px 이하로 재인코딩
- **지시문**(`build_prompt`): 영어. 요지
  - "Image 1의 흙길·맨흙 바닥만 코르크 칩 고무 포장으로 다시 포장. 길의 윤곽·곡선·원근을 따르고 연석·잔디와의 경계는 깔끔하게"
  - "실제 조명과 그림자 유지. 그 밖의 모든 것(구도·**비율**·크기·건물·나무·사람·시설물)은 그대로. 추가·삭제·이동 금지, 글자·로고·워터마크 금지"
  - 프리셋 기본색 평균을 `#RRGGBB`로 넣는다. 참고 사진이 있으면 "Image 2는 제품 근접 참고 — 색·입자 크기·질감만 따를 것"

## 결과 처리 (`merge_edited`)
1. **정렬**: `align.align_to_original`(ORB + RANSAC 호모그래피, 사진 전체 기준). 실패하면 가로세로 비율 차이가 2% 이내일 때만 단순 확대로 대신하고, 아니면 실패
2. **바뀐 영역 검출**(`change_mask`): 두 사진을 약하게 흐린 뒤 LAB 색차 > 10 → 열림·닫힘 → **작은 구멍만** 메움(사진 면적 1% 미만, 테두리에 닿지 않은 것) → 가장 큰 조각의 10% 이상이면서 사진 면적 0.5% 이상인 조각만 남김
   - 남은 조각이 없으면 실패("바뀐 길 영역을 찾지 못함"), 사진의 90% 초과면 실패("사진 전체가 바뀜")
   - 순환로 안 잔디처럼 큰 구멍은 메우지 않는다(길 밖으로 간주)
3. 마스크·정렬 결과를 원본 해상도로 확대 → `compositor.composite_verified(original, layer, mask, feather=4)`
4. 검증 실패 시 결과를 버린다. 성공하면 `(결과, 마스크)`를 돌려주고 화면은 `session.result_hq`, `session.mask`, `session.verified=True`로 저장한다
- 이 함수는 Gemini 결과가 어떤 해상도로 오더라도(1024px, 2048px 등) 동작해야 한다

## 실패 처리 (화면에 한 줄 사유, 응답 원문은 표시·로그 금지)
| 상황 | 사유 문구(요지) |
|---|---|
| 429 + `free_tier` + `limit: 0` | 키의 프로젝트가 무료 등급 → AI Studio에서 결제(Billing) 연결 |
| 429 일일 한도 / 기타 | 오늘 한도 소진 / 1분쯤 뒤 재시도 |
| 401·403 / 404 / 400 / 5xx | 키 거부 / 모델 없음(config 확인) / 요청 거부 / 서버 오류 |
| 시간 초과·네트워크 | 시간 초과 / 인터넷 연결 확인 |
| 안전 필터·이미지 없음 | 차단됨 / 응답에 이미지 없음 |
| 정렬·영역 검출·검증 실패 | 구도가 달라 맞출 수 없음 / 바뀐 영역 없음 / 전체가 바뀜 / 길 밖이 바뀜 → [다시 만들기] |
- 취소 버튼 제공. 이미 보낸 요청은 서버에서 처리되어 요금이 나갈 수 있음을 안내한다
- 실패 시 자동 재시도하지 않는다(요금). 사용자가 [다시 만들기]로 재시도

## 인터페이스
```python
# app/ai/gemini_convert.py
class GeminiConvert(GeminiHQ):            # 사용 조건·클라이언트·오류 분류는 GeminiHQ 것을 그대로 쓴다
    def __init__(self, config, consent, transfer_log, materials_dir=None, **kw)
    def available(self) -> tuple[bool, str]
    def prepare_full(self, session: WorkSession, preset: CorkPreset) -> SendPackage     # 확인 창용
    def convert(self, session, package, cancel=None) -> tuple[np.ndarray, np.ndarray]  # (결과, 마스크) 또는 HQError
def merge_edited(original, edited, sent=None) -> tuple[np.ndarray, np.ndarray]
def change_mask(original, edited) -> np.ndarray                                         # 0/255
def build_prompt(preset: CorkPreset | None, has_reference: bool) -> str
def reference_path(materials_dir, preset) -> Path | None
# app/ai/gemini_hq.py (단계별 화면의 '고품질로 다듬기', v1 유지)
class GeminiHQ: available(), prepare(session), refine(session, n, package, cancel)
class HQError(RuntimeError); @dataclass SendPackage(..., description: str = "", preset=None)
def _api_reason(code: int, message: str | None = "") -> str
# app/ai/align.py
def align_to_original(candidate, original_crop, mask_crop) -> tuple[np.ndarray | None, float]
```

## 완료 기준
- [ ] 가짜 서버로: 성공(밀림 포함) 시 바뀐 영역 IoU > 0.85, 길 밖 픽셀 원본과 동일(전체 색 변화 미반영)
- [ ] 결과 해상도가 달라도(1024·2048px) 합성·검증 통과
- [ ] 전혀 다른 사진·전체 변경·비율 다름·변화 없음·할당량·무료 등급 → 각각 사유와 함께 실패
- [ ] 전송 확인 전·설정 꺼짐이면 요청 0건
- [ ] 요청 형식: 대상 호스트 1곳, `generateContent`, 인라인 데이터만(`fileData` 없음), 사진 전체 비율 유지, 참고 사진 유무에 따라 이미지 1~2장
- [ ] 코드 전체에 Files API·캐싱·대화 세션·그라운딩 호출이 없음(정적 검사 테스트)
