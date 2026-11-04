# 01. 사진 입력 (불러오기·촬영)

## 목적
현장 사진을 빠르게 앱에 넣고, 원본 해상도·올바른 방향으로 보관한다.

## 입력 경로
1. **파일 열기 / 끌어놓기**: JPG, PNG, HEIC(휴대폰 사진)
2. **PC·태블릿 카메라 촬영**: Qt Multimedia(`QCamera`, `QImageCapture`)로 미리보기·촬영. 후면 카메라 우선 선택, 카메라가 없으면 버튼 숨김
3. **최근 폴더 빠른 열기**: 마지막으로 연 폴더의 최신 사진 썸네일 6장 표시(휴대폰을 USB로 연결해 가져온 경우 대비)

## 인터페이스 (`app/core/image_io.py`)
```python
def load_image(path: str) -> np.ndarray          # BGR uint8, EXIF 회전 적용, 한글 경로 지원
def save_image(path: str, img: np.ndarray, quality: int = 92, strip_meta: bool = True) -> None
def make_preview(img: np.ndarray, max_px: int) -> tuple[np.ndarray, float]   # (축소본, 배율)
def qimage_to_bgr(qimg) -> np.ndarray
```

## 요구 사항
- EXIF 방향은 `PIL.ImageOps.exif_transpose`로 보정 후 NumPy 변환
- HEIC는 `pillow_heif.register_heif_opener()` 사용
- 16비트·알파 채널 이미지는 8비트 BGR로 변환
- 원본이 매우 클 때(예: 50MP 초과) 경고 후 긴 변 8000px로 축소 옵션 제공
- 화면 표시는 미리보기 축소본, 최종 합성은 원본 해상도

## 완료 기준
- [ ] 한글 경로 JPG·PNG 읽기/쓰기 테스트 통과
- [ ] EXIF 회전(6, 8) 테스트 이미지 정상 방향
- [ ] 저장 시 `strip_meta=True`면 EXIF가 없음
- [ ] 카메라 없는 PC에서 오류 없이 실행
