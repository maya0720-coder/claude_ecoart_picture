# 04. 코르크 자재 (v2)

## 목적
코르크 색상 프리셋을 관리하고, (v2) Gemini 자동 변환에 쓸 **자재 참고 사진**과 프롬프트용 색을 제공한다.
단계별 화면(--classic)의 로컬 렌더용 텍스처도 만든다.

## Gemini 참고 사진 (v2)
- 위치: `materials/cork/<프리셋 id>/reference.jpg` (없으면 지시문의 색 설명만으로 변환)
- 내용: 실제 시공된 코르크 포장면만 보이게 자른 사진. **사람·현수막·전화번호·로고·QR이 없어야 한다**(외부로 전송됨)
- 현재: `natural_brown/reference.jpg` = 에코코르크 시공 사진(2026-11 영업 제공)의 포장면 크롭
- 다크 브라운·컬러도 실제 시공 사진을 받아 같은 방식으로 넣는다(사용자 확인 필요)
- 프롬프트 색: `base_colors` 평균을 `#RRGGBB`로 지시문에 넣는다(`gemini_convert.build_prompt`)

## 텍스처 출처 (우선순위)
1. **회사 제품 사진**: `materials/cork/<프리셋>/sample.jpg` — 사용자가 실제 시공 표면을 정면에 가깝게 찍어 넣는다. 가장 사실적이다.
2. **절차적 생성(대체)**: 제품 사진이 없을 때 코드로 생성
   - 무작위 크기의 입자(원·불규칙 다각형)를 촘촘히 배치(Poisson disk 등)
   - 큰 칩 + 작은 칩 두 층, 주기 노이즈로 좌표를 비틀어 불규칙한 모양
   - 칩별 색을 `base_colors`에서 고름, 낮은 대비(밝기 표준편차 ±9%), 칩 무리 단위 얼룩, 입자 사이 틈은 얕게(18%)
   - 미세 노이즈와 약한 하이라이트로 결합재 질감 표현

## 프리셋 (`materials/cork/presets.yaml`)
```yaml
- id: natural_brown
  name: 내추럴 브라운
  sample: natural_brown/sample.jpg   # 없으면 절차적 생성
  base_colors: ["#C9A27F", "#C9A27F", "#B88F6C", ...]   # 시공 사진에서 측정한 칩 색. 같은 색을 반복하면 그 비율이 커짐
  granule_mm: 3.0                                  # 예시값, 실제 제품 규격으로 교체
```
- 프리셋 3개(내추럴 브라운, 다크 브라운, 컬러). 내추럴 브라운 색은 시공 사진 측정값, 나머지 색과 입자 크기는 **예시값**임을 주석으로 명시한다. 실제 값은 사용자가 제품 자료로 채운다.

## 처리
- 샘플 사진: 중앙 정사각 영역 추출 → 조명 평탄화(큰 블러로 나눔) → 이음매 없는 타일화(오프셋 + 경계 블렌딩)
- 반복 티 완화: 타일 배치 시 무작위 90° 회전·반전, 저주파 밝기 변화
- 출력: 평면 텍스처(실제 축척: `px_per_m` 기준)

## 인터페이스 (`app/core/cork_material.py`)
```python
@dataclass
class CorkPreset: id: str; name: str; sample: str | None; base_colors: list[str]; granule_mm: float
def load_presets(path: str) -> list[CorkPreset]
def make_tile(preset: CorkPreset, px_per_m: int, size_px: int = 1024, seed: int = 0) -> np.ndarray
def make_plane_texture(tile: np.ndarray, w: int, h: int, seed: int = 0) -> np.ndarray
```

## 완료 기준
- [ ] 샘플 사진 있음/없음 두 경우 모두 텍스처 생성
- [ ] (v2) 참고 사진이 있으면 Gemini 요청에 2번째 이미지로 포함, 없으면 1장만
- [ ] 타일 경계 이음매: 타일 4장을 붙인 이미지의 경계선 그래디언트가 내부 평균의 1.5배 이하
- [ ] 같은 seed면 같은 결과(재현성)
