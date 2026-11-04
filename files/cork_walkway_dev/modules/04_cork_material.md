# 04. 코르크 자재 텍스처

## 목적
코르크 포장 표면 텍스처를 준비하고, 색상 프리셋을 빠르게 바꿀 수 있게 한다.

## 텍스처 출처 (우선순위)
1. **회사 제품 사진**: `materials/cork/<프리셋>/sample.jpg` — 사용자가 실제 시공 표면을 정면에 가깝게 찍어 넣는다. 가장 사실적이다.
2. **절차적 생성(대체)**: 제품 사진이 없을 때 코드로 생성
   - 무작위 크기의 입자(원·불규칙 다각형)를 촘촘히 배치(Poisson disk 등)
   - 입자별 색상을 프리셋 기본색 주변에서 변화, 입자 사이 어두운 틈
   - 미세 노이즈와 약한 하이라이트로 결합재 질감 표현

## 프리셋 (`materials/cork/presets.yaml`)
```yaml
- id: natural_brown
  name: 내추럴 브라운
  sample: natural_brown/sample.jpg   # 없으면 절차적 생성
  base_colors: ["#8B5A2B", "#A0522D", "#6B4423"]   # 예시값, 실제 제품 색으로 교체
  granule_mm: 3.0                                  # 예시값, 실제 제품 규격으로 교체
```
- 예시 프리셋 3개(내추럴 브라운, 다크 브라운, 컬러)를 넣되 **색상·입자 크기는 예시값**임을 주석으로 명시한다. 실제 값은 사용자가 제품 자료로 채운다.

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
- [ ] 타일 경계 이음매: 타일 4장을 붙인 이미지의 경계선 그래디언트가 내부 평균의 1.5배 이하
- [ ] 같은 seed면 같은 결과(재현성)
