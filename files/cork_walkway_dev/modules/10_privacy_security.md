# 10. 사진 유출 방지·보안

## 원칙
**현장 사진은 PC 안에서만 보관·처리한다. 외부 전송은 사용자가 켠 Gemini 고품질 모드에서, 최소 범위만 보낸다.**

## 규칙
1. **기본 오프라인**: 설치 직후 Gemini 꺼짐. 실행 중 Claude API 호출 없음.
2. **최소 전송** (`privacy.prepare_for_send`)
   - 메타데이터(EXIF, GPS, 기기 정보) 제거 후 픽셀만 재인코딩
   - 길 영역 주변만 잘라서 전송(전체 사진 금지)
   - 긴 변 `gemini.max_send_px` 이하로 축소
   - 파일명, 경로, 현장명, 사용자명은 요청에 넣지 않음
3. **Gemini 서버 저장 경로 차단**
   - Files API 업로드 금지 → 인라인 바이트만
   - 컨텍스트 캐싱, 대화 세션, Google 검색·지도 그라운딩 금지
   - **유료 등급 키만 허용**: 설정에서 "Cloud Billing이 연결된 유료 키임을 확인함" 체크 전에는 기능 비활성
   - 화면·README 고지: "유료 등급에서도 Google은 정책 위반 감지를 위해 요청·응답을 일정 기간 기록할 수 있습니다. 완전한 무보관이 필요하면 Vertex AI 무보관(ZDR) 구성을 사용해야 합니다."
4. **전송 전 확인 창**: 보낼 이미지 미리보기, 해상도, 대상(Google Gemini API) 표시 후 [보내기]/[취소]. "이번 실행 동안 묻지 않기" 옵션만 허용(영구 생략 불가)
5. **네트워크 허용 대상**: `generativelanguage.googleapis.com` 한 곳. 텔레메트리, 자동 업데이트, 원격 모델 다운로드 코드 금지
6. **로컬 보관**
   - 임시 파일: `%LOCALAPPDATA%\CorkWalkway\temp\`, 종료 시 삭제
   - 로그: 이미지·base64·API 응답 원문 기록 금지(시각, 단계, 소요 시간, 오류 코드만)
   - 클라우드 업로드·공유 기능 만들지 않음
7. **전송 내역 화면**: 이번 실행의 전송 시각, 대상, 해상도, 영역 크기(이미지 자체는 기록하지 않음)
8. **API 키**: `keyring`으로 Windows 자격 증명 관리자 저장, 화면에는 앞 4자리 외 `****` 마스킹, 로그 출력 금지
9. README 첫머리: "고객 현장 사진을 외부 AI로 보내기 전에 회사 정보보호 규정과 고객 동의 여부를 확인하십시오."

## 인터페이스
```python
# app/security/privacy.py
def prepare_for_send(img: np.ndarray, mask: np.ndarray, max_px: int, margin_ratio: float = 0.1) -> tuple[bytes, tuple[int,int,int,int]]   # (JPEG 바이트, 자른 영역 x,y,w,h)
class TransferLog: ...
def cleanup_temp() -> None
# app/security/secrets.py
def get_key(name: str) -> str | None; def set_key(name: str, value: str) -> None; def mask_key(value: str) -> str
```

## 완료 기준
- [ ] `prepare_for_send` 결과 JPEG에 EXIF 없음, 크기가 잘린 영역·최대 해상도 이하
- [ ] 로그 파일에서 base64 패턴 미검출
- [ ] 종료 후 temp 폴더 비어 있음
- [ ] 키 마스킹 테스트 통과
