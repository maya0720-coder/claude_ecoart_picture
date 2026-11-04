# 02. 흙길 영역 지정 (마스크)

## 목적
현장에서 **터치 1~2회**로 흙길 마스크를 만들고, 필요하면 손으로 다듬는다.

## 방식
1. **SAM 계열 경량 ONNX 모델**(예: MobileSAM, EfficientSAM)
   - 사진을 불러오면 바로 이미지 인코더를 백그라운드로 실행(임베딩 캐시)
   - 사용자가 길을 터치 → 포함 점, 길 밖을 길게 누름/우클릭 → 제외 점
   - 디코더 출력 중 점수가 가장 높은 마스크 채택
   - 모델 라이선스가 상업적 사용을 허용하는지 확인하고 README에 출처·라이선스를 적는다
2. **수동 보정 도구**: 브러시(추가), 지우개, 다각형, 브러시 크기 조절, 실행 취소/다시 실행(20단계)
3. **모델 파일이 없을 때**: 수동 도구만으로 동작, 안내 표시

## 후처리
- 작은 구멍 채우기, 작은 조각 제거(면적 기준)
- 길 위의 사람·물체는 사용자가 제외 점으로 빼면 원본 유지
- 경계 페더: 기본 3px(1~10 조절), 합성용 알파 생성

## 인터페이스 (`app/core/segmentation.py`)
```python
class PathSegmenter:
    def __init__(self, model_dir: str): ...
    def available(self) -> bool
    def set_image(self, img_bgr: np.ndarray) -> None        # 인코더 실행·캐시
    def predict(self, pos_pts: list[tuple[int,int]], neg_pts: list[tuple[int,int]]) -> np.ndarray  # uint8 0/255
def clean_mask(mask: np.ndarray, min_area_ratio: float = 0.002) -> np.ndarray
def feather_alpha(mask: np.ndarray, px: int) -> np.ndarray   # float32 0~1
```

## 화면 표시
- 마스크를 반투명 주황색으로 덮어 보여주고, 경계선을 굵게 표시
- 좌표는 미리보기 배율을 고려해 원본 좌표로 변환

## 완료 기준
- [ ] 모델 있음/없음 두 경우 모두 동작
- [ ] 합성 테스트 이미지(가운데 갈색 사다리꼴 길)에서 점 1개로 IoU 0.8 이상
- [ ] `feather_alpha` 결과가 마스크 밖 `px` 이상 떨어진 곳에서 정확히 0
