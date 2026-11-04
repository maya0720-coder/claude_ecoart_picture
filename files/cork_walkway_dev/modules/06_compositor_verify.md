# 06. 합성과 무변경 검증

## 목적
렌더 결과를 원본에 합성하되, **길 밖은 단 1픽셀도 바뀌지 않음**을 보장한다.

## 절차
1. `alpha = feather_alpha(mask, feather_px)`
2. `out = original * (1 - alpha) + layer * alpha` (float32 계산 후 반올림, uint8)
3. **검증**: `outside = dilate(mask, feather_px + 1) == 0` 영역에서 `out`과 `original`이 완전히 같은지 확인
4. 검증 실패 시 결과를 버리고 오류를 표시한다(저장·프레젠테이션 불가)

## 인터페이스 (`app/core/compositor.py`)
```python
def composite(original: np.ndarray, layer: np.ndarray, mask: np.ndarray, feather_px: int) -> np.ndarray
def verify_outside_unchanged(original: np.ndarray, result: np.ndarray, mask: np.ndarray, feather_px: int) -> tuple[bool, int]   # (통과 여부, 바뀐 픽셀 수)
```

## 완료 기준
- [ ] 무작위 이미지·마스크 100회 테스트에서 검증 100% 통과
- [ ] 일부러 바깥 픽셀을 바꾼 결과는 검증 실패로 판정
