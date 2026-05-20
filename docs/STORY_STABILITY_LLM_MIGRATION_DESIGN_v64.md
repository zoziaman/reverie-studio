# STORY STABILITY + LLM MIGRATION DESIGN v64

## 목적

레베리의 스토리 산출 안정성을 `운`이 아니라 `시스템 품질`로 끌어올리고, 현재 Gemini 중심 구조를 `교체 가능한 LLM provider 구조`로 전환한다.

이번 설계의 1차 목표는 두 가지다.

1. 스토리 생성 경로를 Gemini 하드 의존에서 분리한다.
2. Claude CLI를 스토리 생성 백엔드로 연결 가능한 상태로 만든다.

## 현재 구조 진단

현재 스토리 생성 핵심 경로는 아래와 같다.

1. `ScenarioPlanner`가 topic, story_bible, outline, metadata를 생성한다.
2. `ScriptWriter` 3명이 Part 1/2/3을 순차 집필한다.
3. `scenario_planner._execute_plan_with_bible()`이 fallback 대본을 차단한다.
4. `script_quality_gate`가 최종 full script를 검사한다.

문제는 아래 4개다.

1. `ScenarioPlanner`가 `GEMINI_API_KEY`와 `google.generativeai`를 전제로 시작한다.
2. 모델 호출 계층이 통합되지 않아 Claude/OpenAI 등으로 갈아타려면 파일 곳곳을 수정해야 한다.
3. 품질 게이트가 최종 결과 중심이라 파트 단위 불량을 초기에 덜 잡는다.
4. 한 번 생성해서 통과시키는 구조라 후보 비교 선택이 없다.

## 목표 아키텍처

### 1. Provider 분리

스토리 생성은 아래 인터페이스를 따르는 provider만 사용한다.

- `generate_content(prompt, timeout=None, generation_config=None, **kwargs)`
- 응답 객체는 최소 `text` 속성을 가진다.
- provider는 `model_name`을 노출한다.

### 2. 1차 provider 범위

1차 구현 범위:

- `gemini`: 기존 경로 유지
- `claude_cli`: 신규

보류:

- `openai_api`
- `codex_cli`
- `anthropic_api`

이유:

- 지금 가장 큰 pain point는 Gemini 탈피다.
- Claude CLI는 이미 사용 의도가 명확하다.
- Codex CLI는 코드 에이전트 성격이 강해 스토리 생성의 기본 provider로는 우선순위가 낮다.

### 3. 책임 분리

`ScenarioPlanner`는 이제:

- 어떤 provider를 쓰는지 모른다.
- provider factory에서 모델 객체만 받아 쓴다.
- `GEMINI_API_KEY` 존재 여부를 직접 검사하지 않는다.

`llm factory`는:

- 설정값을 보고 provider를 선택한다.
- provider 초기화 실패 시 명확한 예외를 던진다.

### 4. 안정성 상향 로드맵

1차:

- provider 분리
- Claude CLI 연결
- Gemini 강제 의존 제거

2차:

- 파트별 품질 게이트
- 후보 2개 생성 후 선택
- critic model 분리

3차:

- 회귀셋 대량화
- 결과 메트릭 저장
- provider별 품질 비교 대시보드

## Claude CLI 선택 이유

Claude CLI는 텍스트 기반 장문 생성과 비대화형 호출에 적합하고, 스토리 생성처럼 긴 구조화 출력이 필요한 작업에 맞다.

운영 방향은 다음과 같다.

- 모델: `sonnet` 계열 기본
- 호출 방식: `claude -p`
- 출력: 텍스트
- JSON 강제는 기존 프롬프트가 담당

## 스토리 산출 안정성 최적화 방향

최상의 결과물을 목표로 할 때 권장 구조는 아래다.

1. `Blueprint` 후보 2개 생성
2. 로컬 rubric로 1차 점수화
3. 최고 blueprint 선택
4. 각 Part를 2회 후보 생성
5. 파트 게이트로 선택
6. 최종 full script 게이트
7. 실패 시 fallback이 아니라 `재시도/실패 종료`

즉, 최종형은 `단일 생성`이 아니라 `후보 생성 + 자동 선별` 구조다.

## 이번 1차 구현의 범위 한계

이번 변경은 아래까지만 직접 구현한다.

- LLM 추상화의 최소 골격
- Claude CLI adapter
- ScenarioPlanner provider 전환
- 설정 추가

아래는 문서화만 하고 후속 공정으로 넘긴다.

- ScriptWriter 파트별 다중 후보 선택
- critic provider 분리
- GUI 설정화면 개편
- 평가 메트릭 저장/대시보드

## 성공 기준

1. Gemini API 키가 없어도 `claude_cli` provider로 ScenarioPlanner가 초기화된다.
2. 기존 Gemini 경로는 유지된다.
3. Story generation 경로가 provider abstraction 위에서 동작한다.
4. 향후 `openai_api` 또는 `anthropic_api`를 같은 방식으로 추가할 수 있다.
