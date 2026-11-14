# J.A.R.V.I.S — 프로젝트 지침

Windows 음성 AI 비서. Python 3 + PySide6(QML HUD), 테스트는 `python -m pytest -q`. 구조는 README.md 의 "구성" 절 참고.
`data/` 에는 API 키·기억·목소리 지문이 있다 — 내용을 읽어 옮기거나 외부로 보내지 않는다.

## 메인 에이전트 = Chief Architect & Orchestrator

메인 Claude 는 직접 모든 코드를 쓰기보다 요청을 분석해 전문 에이전트(`.claude/agents/`)에게 나눠 맡기고, 결과를 조정·검토·통합 테스트한다.

1. 요청 분석 → 아래 담당표로 영역을 가른다. 두 영역 이상이거나 app.py·brain.py·tools.py·config.py 구조를 바꾸면 먼저 `system-architect`.
2. 영역별 구현을 담당 에이전트에게 위임한다. 서로 다른 파일을 건드리는 분석·구현은 병렬로 돌린다. 같은 파일을 두 에이전트가 동시에 고치지 않게 한다.
3. 에이전트 의견이 충돌하면(예: 음성 지연 vs 보안 승인 강화) 근거를 비교해 메인이 결정하고, 보안 치명·높음 항목은 기능보다 우선한다.
4. 통합 후 `qa-engineer` 로 전체 회귀 테스트, 아래 "보안 검토 조건" 에 해당하면 `security-engineer`.
5. 마지막으로 전역 규칙대로 `reviewer` 검토 후 보고.

## 담당표 (파일 → 담당)

| 에이전트 | 담당 파일 | 쓰기 |
|---|---|---|
| `system-architect` | 전체 구조·의존성·통합 설계 (코드 소유 없음) | 읽기 전용 |
| `ui-ux-engineer` | `ui/*.qml`, `ui/assets/`, `hud_feed.py`, `demo.py`, `counter_view.py`·`defense_view.py`(그리기), app.py 의 QML 연결부 | 가능 |
| `voice-engineer` | `listener`, `frontend`(마이크 앞단), `noise`, `local_stt`, `hearing`, `voiceid`, `barge`, `speech`, `approval`, `local_router`, `local_ai`, `claude_session`, `persona`, brain.py 라우팅·대화 모드 | 가능 |
| `desktop-integration-engineer` | `winutil`, `hotkey`, `control`, `uia`, `vision`, `files`, `tools.py`, `toolserver`, `mcp_bridge`, `main.py`, `selftest`, `sentinel`, `guard`·`counter`·`defense`(로직) | 가능 |
| `memory-context-engineer` | 기억(`config.load/save_memory`, `remember`), brain.py 대화 기록, `todos`, `routines`, `proactive`, `agenda`, `classroom` | 가능 |
| `security-engineer` | 승인 체계·비밀정보·개인정보·프롬프트 인젝션 점검 | 읽기 전용 |
| `qa-engineer` | pytest 회귀·기능 검증·재현 보고·테스트 공백 명세 | 소스 수정 불가 (Edit/Write 없음. 실행용 셸은 있어 지시로 금지) |

전문 담당 없는 영역 → 메인이 전역 `coder` 에게: 결과물(`office`, `deck`, `report`, `hwpx` + `hwpx_template/`, `design`, `icons`, `writers`)과 그 테스트(test_office·deck·design·hwpx·team), `jarvis/__init__.py`, app.py 의 QML 연결부·승인 처리 밖 일반 흐름.

### 공유 파일 규칙
`app.py`, `brain.py`, `tools.py`, `config.py`(그리고 `counter_view.py`·`defense_view.py`)는 여러 담당이 나눠 쓴다. 이 파일들을 건드리는 작업은 **병렬 금지, 한 번에 한 에이전트씩 순차 위임**한다. 경계: brain.py 대화 기록(history·chat_history·초기화 조건)=memory, 라우팅·프롬프트·대화 모드=voice / tools.py `t_remember`=memory, 나머지=desktop / config.py `DEFAULTS` 새 키는 그 기능 담당이 추가하되 기본값은 기존 동작 유지 / app.py 승인 처리(`_on_confirm`·`answer_confirm`)를 바꾸면 보안 검토 필수.

### 위임할 때 넘길 것
읽기 전용 에이전트(`system-architect`, `security-engineer`)는 git 을 못 쓴다 — 변경 검토를 맡길 때는 변경 파일 목록(필요하면 diff 요약)을 프롬프트에 넣는다.

## 자동 위임 조건

- QML·HUD·액티브 모드·애니메이션·승인 카드 모양 → `ui-ux-engineer`
- 인식 실패·오인식·호출어·목소리·TTS·말 끊기·명령 해석·자비스 말투 → `voice-engineer`
- 창·키 입력·클릭·단축키·트레이·파일 정리·새 PC 도구·MCP/도구 서버 → `desktop-integration-engineer`
- 기억·대화 기록·할 일·루틴·브리핑·일정·메일·클래스룸 → `memory-context-engineer`
- 여러 영역에 걸친 기능, 새 모듈 추가, 의존성 정리 → 먼저 `system-architect`
- 코드 변경 후 검증 → `qa-engineer` (이 프로젝트에서는 범용 `tester` 대신). 새 테스트 코드 작성은 qa-engineer 의 명세를 받아 전역 `simulator` 가.

### 보안 검토 조건 (해당하면 반드시 `security-engineer`)
`approval.py`·`voiceid.py`·`tools.py`의 `_confirm`·`app.py`의 승인 처리·`ConfirmCard.qml` 변경, 새 위험 도구(실행·삭제·전송·종료·PowerShell·클릭), API 키·비밀번호·토큰 처리, `toolserver`/`mcp_bridge`, 외부 내용(웹·메일·클래스룸·화면 글자)을 Claude 에게 넘기는 경로.

## 전역 에이전트와의 관계

전역 흐름(thinker → planner → researcher → designer → coder → tester/simulator → optimizer → critic/reviewer)은 유지하되, 이 프로젝트에서는:
- 아키텍처 설계는 `designer` 대신 `system-architect`(UI 시각 설계가 필요하면 `ui-ux-engineer`).
- 담당 파일이 분명한 구현은 `coder` 대신 해당 전문 에이전트.
- 실행 검증은 `tester` 대신 `qa-engineer`.
- `optimizer` 는 전역 커밋 규칙(시작 전 커밋, 결과는 별도 커밋)을 따르고, 공유 파일 규칙도 지킨다. 함수 안에서 늦게 하는 import(office↔deck/report, counter↔counter_view, defense↔defense_view)는 순환 방지용이니 최상단으로 올리지 않는다.
- `thinker`·`planner`·`researcher`·`critic` 은 코드를 고치지 않으므로 그대로 쓴다.
- 자동 위임은 description·이 문서를 보고 모델이 판단하는 방식이라 강제력은 없다. 애매하면 메인이 에이전트를 직접 지정한다.

## 공통 규칙 (모든 에이전트)
- 담당 밖 파일은 고치지 않고 보고서의 "다른 영역 요청" 으로 넘긴다.
- 기존 기능을 임의로 삭제·변경하지 않는다. 근거 없이 새 프레임워크·패키지를 들이지 않는다.
- 작업 트리에 사용자의 커밋 안 된 변경이 있을 수 있다 — 되돌리거나 덮어쓰지 않는다.
