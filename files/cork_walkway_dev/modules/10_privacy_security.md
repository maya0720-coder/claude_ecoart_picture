# 10. 사진 유출 방지·보안 (v2)

## 원칙
**현장 사진은 PC 안에서 보관·처리한다. 외부 전송은 사용자가 설정에서 켜고 전송 확인 창에서 승인한 Gemini API 호출 한 가지뿐이며, 필요한 최소 형태(축소·메타데이터 제거)로만 보낸다.**

> v2 변경: 간편 화면은 길 주변 크롭이 아니라 **사진 전체의 축소본**을 보낸다(길 위치를 모르는 상태에서 Gemini가 길을 찾아야 하므로). 그만큼 사람 얼굴·차량 번호판·간판 등이 함께 전송될 수 있음을 확인 창·README에 알린다.

## 규칙
1. **설치 직후 전송 꺼짐**: `config.yaml`의 `gemini.enabled: false`, 사용자 설정 `gemini_enabled`·`gemini_paid_key_confirmed`가 모두 켜지고 키가 있어야 `available()`이 참. 실행 중 Claude API 호출 없음.
2. **최소 전송** (`privacy.prepare_for_send`)
   - 메타데이터(EXIF, GPS, 기기 정보) 제거 후 픽셀만 재인코딩(`cv2.imencode`)
   - 간편 화면: 사진 전체(크롭 여백 0) / 단계별 화면 고품질: 길 주변만 크롭
   - 긴 변 `gemini.max_send_px` 이하로 축소
   - 파일명, 경로, 현장명, 사용자명은 요청에 넣지 않음
   - 자재 참고 사진은 포장면만 잘라낸 회사 사진으로, 사람·전화번호·현수막이 없어야 한다
3. **Gemini 서버 저장 경로 차단**
   - Files API 업로드 금지 → 인라인 바이트만
   - 컨텍스트 캐싱, 대화 세션, Google 검색·지도 그라운딩, 도구 호출 금지
   - 요청마다 `store=False`
   - **유료 등급 키만 허용**: 설정의 "결제(Billing)가 연결된 유료 프로젝트의 키임을 확인함" 체크 전에는 기능 비활성. 무료 등급 키는 이미지 모델 할당량이 0이므로 실패 사유로 안내
   - 화면·README 고지: "유료 등급에서도 Google은 정책 위반 감지를 위해 요청·응답을 일정 기간 기록할 수 있습니다. 완전한 무보관이 필요하면 Vertex AI 무보관(ZDR) 구성을 사용해야 합니다."
4. **전송 전 확인 창**: 보낼 이미지 미리보기, 해상도, 대상(Google Gemini API), 보낼 이미지 설명(사진 전체 축소본 + 참고 사진 여부) 후 [보내기]/[취소]. "이번 실행 동안 묻지 않기"만 허용(저장하지 않음 → 다음 실행에 다시 묻는다)
5. **네트워크 허용 대상**: `generativelanguage.googleapis.com` 한 곳. 텔레메트리, 자동 업데이트, 원격 모델 다운로드, 브라우저 자동 조작 코드 금지. 정적 검사 테스트:
   - `app/` 코드의 URL 문자열은 허용 호스트만
   - `requests`, `urllib`, `http`, `socket`, `httpx`, `aiohttp`, `websockets`, `ftplib`, `smtplib` 직접 import 금지(SDK 내부 사용은 허용)
6. **로컬 보관**
   - 임시 파일: `%LOCALAPPDATA%\CorkWalkway\temp\`, 시작·종료 시 삭제
   - 로그: 이미지·base64·API 응답 원문 기록 금지(시각, 단계, 소요 시간, 오류 종류·코드, 변경 영역 비율만). `RedactFilter`가 base64와 API 키(`AIza…`, `AQ.…`)를 지운다
   - 화면 실패 사유는 응답 원문이 아니라 분류된 한 줄 문구만
   - 클라우드 업로드·공유 기능 만들지 않음
7. **전송 내역 화면**: 이번 실행의 전송 시각, 대상, 보낸 해상도·장수, 원본 영역 크기(이미지 자체는 기록하지 않음). 전송 **직전에** 기록(실패한 요청도 사진은 나갔을 수 있음)
8. **API 키**: `keyring`으로 Windows 자격 증명 관리자 저장, 화면에는 `앞 4자리…뒤 4자리`로 마스킹(새 형식 `AQ.…` 키는 앞부분이 같아 뒤 4자리로 구분, 16자 미만은 앞 4자리 + `****`). 저장 후 다시 읽어 확인하고 마스킹된 값으로 저장 완료를 알린다. 입력 후 저장하지 않고 닫으면 저장 여부를 묻는다. 로그·설정 파일·코드에 넣지 않음. 키가 화면 캡처 등으로 노출되면 즉시 폐기·재발급하도록 README에 안내
9. README 첫머리: "고객 현장 사진을 외부 AI로 보내기 전에 회사 정보보호 규정과 고객 동의 여부를 확인하십시오."

## 인터페이스
```python
# app/security/privacy.py
def prepare_for_send(img, mask, max_px, margin_ratio=0.1) -> tuple[bytes, tuple[int, int, int, int]]   # (JPEG, 영역 x,y,w,h)
def crop_box(mask, margin_ratio=0.1) -> tuple[int, int, int, int]
class TransferLog: add(sent_size, region, images=1); entries()
class SendConsent: needs_confirmation(); skip_for_this_run()
def cleanup_temp() -> None; def setup_logging(level=logging.INFO) -> Path; class RedactFilter(logging.Filter)
# app/security/secrets.py
def get_key(name) -> str | None; def set_key(name, value) -> None; def delete_key(name) -> None; def mask_key(value) -> str
```

## 완료 기준
- [ ] 전송 JPEG에 EXIF 없음, 크기가 최대 해상도 이하(간편: 사진 비율 유지, 단계별: 잘린 영역)
- [ ] 로그 파일에서 base64·`AIza…`·`AQ.…` 키 패턴 미검출
- [ ] 종료 후 temp 폴더 비어 있음
- [ ] 키 마스킹 테스트 통과, 설정 파일에 키가 저장되지 않음
- [ ] 허용 호스트·금지 모듈 정적 검사 통과
- [ ] 설정 꺼짐·확인 취소 시 요청 0건
