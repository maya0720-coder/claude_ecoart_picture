# S0. Ponytail 스킬 설치·적용 (가장 먼저 실행)

## 목적
외부 공개 스킬 **Ponytail**(GitHub `DietrichGebert/ponytail`, MIT 라이선스)을 설치해, 코드를 필요한 만큼만 작성하도록 한다.
- Ponytail의 원칙: 새 코드를 쓰기 전에 기존 코드, 표준 라이브러리, 이미 설치된 의존성으로 해결되는지 먼저 확인한다.
- 이 프로젝트에서는 불필요한 래퍼·추상화·의존성을 줄이는 용도로 쓴다.

## 우선순위 규칙 (중요)
1. **MAIN.md의 전역 규칙과 각 모듈의 완료 기준이 Ponytail보다 우선한다.**
2. Ponytail을 이유로 아래 항목을 빼거나 줄이지 않는다.
   - 입력 검증, 오류 처리, 마스크 밖 무변경 검증(06), 사진 유출 방지(10), API 키 보호, 테스트(12), 한글 경로 처리
3. Ponytail 제안과 모듈 지시가 충돌하면 모듈 지시를 따르고, 충돌 내용을 완료 보고에 적는다.

## 1단계. 설치 상태 확인
- `/plugin` 목록 또는 사용 가능한 스킬 목록에서 `ponytail`이 보이는지 확인한다.
- 이미 설치·활성화되어 있으면 3단계로 간다.

## 2단계. 설치 (위에서부터 순서대로 시도, 성공하면 중단)
| 순서 | 방법 | 실행 주체 |
|---|---|---|
| A | 프로젝트 `.claude/settings.json`에 이미 등록됨 → 폴더 신뢰(trust) 시 자동 설치 | 자동 |
| B | 터미널에서 `claude plugin marketplace add DietrichGebert/ponytail --scope project` 실행 후 `claude plugin install ponytail@ponytail --scope project` 실행 | Claude Code가 Bash로 실행(사용자 승인 후) |
| C | 대화창에 `/plugin marketplace add DietrichGebert/ponytail` 입력, 다음 메시지로 `/plugin install ponytail@ponytail` 입력 | 사용자 |
| D | 터미널에서 `npx -y skills add DietrichGebert/ponytail --skill ponytail --agent claude-code` (프로젝트 `.claude/skills`에 설치) | Claude Code가 Bash로 실행(사용자 승인 후) |

- B·D를 실행하기 전에 사용자에게 명령어 전체를 보여주고 승인을 받는다.
- C는 슬래시 명령이라 Claude Code가 대신 입력할 수 없다. 필요하면 사용자에게 입력을 요청한다.
- 설치 후에는 **Claude Code를 재시작**(`/exit` 후 `claude` 다시 실행)하라고 안내하고, 재시작 뒤 1단계로 확인한다.
- Ponytail의 상시 동작 훅은 **Node.js가 PATH에 있어야** 동작한다. `node --version`이 실패하면 Node.js LTS 설치를 안내한다.

## 3단계. 보안 점검 (활성화 전 필수)
- 설치된 플러그인 폴더에서 `hooks`, 스크립트 파일(.js, .sh, .ps1 등)을 읽고 아래를 보고한다.
  - 실행되는 명령, 외부 네트워크 접속 여부, 프로젝트 밖 파일 접근 여부
- 외부 전송이나 의심스러운 동작이 있으면 **사용을 멈추고** 사용자 판단을 받는다.
- 설치된 버전(태그 또는 커밋)을 README의 "사용 도구" 항목에 기록한다.

## 4단계. 개발 중 활용 방식
| 시점 | 활용 |
|---|---|
| 모든 모듈 구현 | Ponytail 규칙(기존 코드·표준 라이브러리·설치된 의존성 우선)을 적용 |
| 각 모듈 완료 직전 | `ponytail-review` 스킬(또는 사용자의 `/ponytail-review`)로 해당 모듈 변경분 검토, 불필요한 코드 정리 |
| 전체 완료 후(12번 이후) | `ponytail-audit` 스킬(또는 `/ponytail-audit`)로 프로젝트 전체 점검, 결과를 최종 보고에 포함 |

- 새 의존성을 추가하려면 "표준 라이브러리·기존 의존성으로 안 되는 이유"를 완료 보고에 한 줄로 적는다.

## 실패 시
- 모든 설치 방법이 실패하면 원인(네트워크, Node 미설치, 권한 등)을 보고하고, **Ponytail 없이 0번 모듈부터 진행할지 사용자에게 묻는다.** 임의로 진행하지 않는다.

## 완료 기준
- [ ] Ponytail 설치·활성 상태 확인(또는 사용자 결정으로 생략)
- [ ] 훅·스크립트 보안 점검 결과 보고
- [ ] 설치 버전 기록
