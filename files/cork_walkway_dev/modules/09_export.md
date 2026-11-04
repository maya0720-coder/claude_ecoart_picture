# 09. 저장·내보내기

## 저장 항목
1. 시공 후 예상도(JPG/PNG, 원본 해상도)
2. **전·후 비교 이미지**(좌우 또는 상하, 각 사진 위에 "시공 전", "시공 후(예상)" 라벨)
3. **1페이지 PDF**(Qt `QPdfWriter`): 현장명(선택 입력), 날짜, 전·후 사진, 코르크 프리셋 이름, 고지 문구
4. 작업 설정 JSON(마스크 PNG 별도 저장 포함) — 같은 결과 재현용

## 규칙
- 워터마크/고지 문구 기본 표시: "가상 시공 예상도 — 실제 시공 결과와 다를 수 있습니다"
- 회사 로고(선택): `assets/logo.png`가 있으면 우측 하단에 작게 표시
- 저장 시 EXIF·GPS 제거 기본
- 파일명 기본값: `현장명_YYYYMMDD_HHMM_전후비교.jpg` (현장명 미입력 시 `현장`)
- 저장 위치는 사용자가 고른 로컬 폴더만

## 인터페이스 (`app/core/export.py`)
```python
def export_result(session, out_dir: str, site_name: str = "", formats: set[str] = {"after","compare","pdf"}) -> list[str]
```

## 완료 기준
- [ ] 한글 현장명·한글 폴더에 저장 성공
- [ ] 저장 파일에 EXIF 없음
- [ ] PDF가 A4 가로 1페이지로 열림
