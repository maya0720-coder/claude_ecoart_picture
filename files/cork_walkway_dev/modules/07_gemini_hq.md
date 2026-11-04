# 07. 고품질 모드 (Gemini, 선택 기능)

> 먼저 `10_privacy_security.md`의 규칙을 반영한 뒤 구현한다.

## 목적
로컬 렌더 결과를 Gemini 이미지 모델로 더 사진처럼 다듬는다. **기본 꺼짐.** 인터넷이 없거나 실패하면 로컬 결과를 그대로 쓴다.

## 방식
- Gemini Developer API(`google-genai` SDK), `generate_content` 1회성 호출
- 모델명은 `config.yaml`의 `gemini.model`. 개발 시점에 ai.google.dev 공식 문서에서 이미지 편집 지원 모델을 확인해 넣는다
- 보내는 것(모두 `privacy.prepare_for_send` 통과 후):
  1. 길 영역 주변만 잘라낸 원본(축소, 메타데이터 제거)
  2. 같은 영역의 **로컬 렌더 결과**(안내 이미지)
- 지시문 요지: "두 번째 이미지의 코르크 포장 질감·색을 첫 번째 사진의 흙길 영역에만 사실적으로 적용. 원근·그림자·조명 유지. 길 밖은 변경하지 말고 새 사물 추가 금지."

## 결과 처리
1. 결과를 잘라낸 영역 크기로 리사이즈
2. `align.py`: 마스크 바깥 영역 기준 ORB 특징점 + RANSAC 또는 ECC로 정렬. 정렬 오차가 기준(예: 평균 2px)을 넘으면 실패 처리
3. 원본 해상도로 되돌려 `compositor.composite`로 **마스크 안쪽만** 합성 → `verify_outside_unchanged` 통과 시 채택
4. 후보 1~3장 생성 옵션, 사용자가 비교 후 선택

## 실패 처리
- 네트워크 오류, 할당량 초과, 안전 필터 차단, 정렬 실패, 검증 실패 → 로컬 결과 유지, 사유를 한 줄로 표시
- 시간 제한: 요청당 60초(설정 가능), 취소 버튼 제공

## 인터페이스
```python
# app/ai/gemini_hq.py
class GeminiHQ:
    def available(self) -> tuple[bool, str]          # (사용 가능, 불가 사유)
    def refine(self, session: WorkSession, n: int = 1) -> list[np.ndarray]   # 합성·검증 완료된 결과들
# app/ai/align.py
def align_to_original(candidate: np.ndarray, original_crop: np.ndarray, mask_crop: np.ndarray) -> tuple[np.ndarray | None, float]
```

## 완료 기준
- [ ] API 키 없음·오프라인에서 버튼 비활성 + 사유 표시
- [ ] 가짜 응답(모의 객체)으로 정렬·합성·검증 경로 테스트 통과
- [ ] 코드 전체에 Files API·캐싱·대화 세션·그라운딩 호출이 없음(정적 검사 테스트)
