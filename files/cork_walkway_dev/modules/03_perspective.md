# 03. 길 원근 추정

> **v2: 단계별 화면(`python -m app.main --classic`) 전용 모듈.** 기본 간편 화면은 이 모듈 없이 Gemini 자동 변환(07)을 쓴다. 오프라인 대안으로 유지한다.

## 목적
코르크 입자 크기가 가까운 곳은 크고 먼 곳은 작게 보이도록 원근을 맞춘다.

## 방식
1. **자동 초기값**: 마스크에서 4점 추정
   - 마스크 하단 20% 구간의 좌·우 끝 → 좌하, 우하
   - 마스크 상단 20% 구간의 좌·우 끝 → 좌상, 우상
   - 굽은 길은 중앙선을 따라 3~5개 구간으로 나눠 구간별 4점을 만드는 옵션(구간 경계는 블렌딩)
2. **수동 조정**: 사다리꼴 4점을 끌어서 조정, 격자 미리보기 표시
3. **길 폭 입력(선택)**: 실제 길 폭(m)을 넣으면 입자 크기를 실제 축척으로 계산. 없으면 기본 2.0m 가정, 화면에 "가정값" 표시

## 인터페이스 (`app/core/perspective.py`)
```python
def estimate_quad(mask: np.ndarray) -> np.ndarray                    # (4,2) float32
def homography_from_quad(quad: np.ndarray, plane_w: int, plane_h: int) -> np.ndarray
def plane_size_for(quad: np.ndarray, path_width_m: float, px_per_m: int) -> tuple[int,int]
```

## 완료 기준
- [ ] 합성 사다리꼴 마스크에서 4점 오차 5px 이내
- [ ] 4점이 꼬이거나 넓이가 0에 가까우면 경고하고 직전 값 유지
