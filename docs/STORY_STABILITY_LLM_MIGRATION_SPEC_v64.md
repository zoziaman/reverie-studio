# STORY STABILITY + LLM MIGRATION SPEC v64

## 기능 범위

### 포함

1. 스토리 생성용 LLM provider 설정 추가
2. Claude CLI adapter 추가
3. Gemini adapter 래핑
4. `ScenarioPlanner`가 provider factory를 사용하도록 변경
5. 최소 테스트 추가

### 제외

1. 이미지 생성 LLM 교체
2. 썸네일 검수/번역/SFX 분석 provider 교체
3. GUI 전체 설정화면 리디자인
4. critic evaluator 교체

## 설정 스펙

신규 설정 키:

- `STORY_LLM_PROVIDER`
  - 허용값: `gemini`, `claude_cli`
  - 기본값: `gemini`

- `STORY_LLM_MODEL`
  - provider 공통 모델 힌트
  - 비어 있으면 provider 기본값 사용

- `STORY_LLM_TIMEOUT_SEC`
  - 기본값: `180`

- `CLAUDE_CLI_PATH`
  - 기본값: `claude`

- `CLAUDE_CLI_MODEL`
  - 기본값: `sonnet`

- `CLAUDE_CLI_EXTRA_ARGS`
  - 공백 구분 문자열

## 코드 구조

신규 패키지:

- `src/llm/__init__.py`
- `src/llm/base.py`
- `src/llm/gemini_adapter.py`
- `src/llm/claude_cli_adapter.py`
- `src/llm/factory.py`

## 인터페이스 스펙

### `LLMTextResponse`

- `text: str`
- `raw: Any | None`

### Provider 공통 메서드

- `generate_content(prompt, timeout=None, generation_config=None, **kwargs)`

동작 규칙:

1. 반드시 `.text` 속성을 가진 응답 객체를 반환한다.
2. 프롬프트는 문자열을 기본으로 받는다.
3. `generation_config`는 provider별로 가능한 범위에서만 반영한다.
4. 지원하지 않는 옵션은 무시하되 치명 실패로 만들지 않는다.

## Claude CLI adapter 스펙

### 명령 형태

기본 호출:

`claude -p <prompt> --output-format text --model <model>`

옵션:

- `timeout`
- `extra args`

### 실패 조건

1. `claude` 명령을 찾을 수 없음
2. 종료 코드 비정상
3. stdout이 비어 있음

### 성공 조건

- stdout을 그대로 `LLMTextResponse.text`로 반환

## ScenarioPlanner 변경 스펙

### 이전

- `GEMINI_API_KEY` 없으면 즉시 실패
- `google.generativeai` 없으면 즉시 실패

### 이후

- provider factory에서 모델 초기화
- `gemini`인 경우에만 Gemini 키 필요
- `claude_cli`인 경우 Gemini 키 불필요

## 테스트 스펙

### 단위 테스트

1. `claude_cli` provider 선택 시 Claude adapter 반환
2. `gemini` provider 선택 시 Gemini adapter 경로 사용
3. Claude adapter가 올바른 subprocess 명령을 구성
4. Claude adapter가 빈 응답/명령 부재를 실패 처리

### 회귀 보장

기존 스토리 생성 테스트와 충돌하지 않아야 한다.

## 후속 확장 스펙

2차 구현에서 아래를 추가한다.

1. `PART_QUALITY_GATE_ENABLED`
2. `STORY_CANDIDATE_COUNT`
3. `STORY_JUDGE_PROVIDER`
4. `STORY_PROVIDER_FALLBACK_CHAIN`
