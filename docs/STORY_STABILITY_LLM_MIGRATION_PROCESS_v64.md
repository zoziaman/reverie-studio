# STORY STABILITY + LLM MIGRATION PROCESS v64

## 공정 목표

Gemini 중심 스토리 생성 경로를 Claude CLI 기반으로 전환 가능한 구조로 바꾸고, 이후 스토리 산출 안정성 극대화 공정을 위한 기반을 마련한다.

## 1차 공정

### 공정 1. 문서화

산출물:

- 설계서
- 시방서
- 공정서

완료 기준:

- 개발 범위, 비범위, 성공 기준이 문서화되어 있어야 한다.

### 공정 2. LLM provider 계층 도입

작업:

1. `llm` 패키지 생성
2. 공통 응답 타입 정의
3. Gemini adapter 래핑
4. Claude CLI adapter 추가
5. provider factory 구현

완료 기준:

- story generation이 provider factory를 통해 모델을 받는다.

### 공정 3. ScenarioPlanner 전환

작업:

1. Gemini 하드 체크 제거
2. provider 기반 초기화 적용
3. 현재 로깅 유지

완료 기준:

- `STORY_LLM_PROVIDER=claude_cli` 환경에서 초기화 가능

### 공정 4. 설정 추가

작업:

1. settings에 provider 관련 키 추가
2. 기본값 지정
3. 추후 GUI 연결 가능 상태 유지

완료 기준:

- `.env`만으로 story provider를 바꿀 수 있다.

### 공정 5. 테스트

작업:

1. provider 선택 테스트
2. Claude CLI subprocess 테스트
3. 최소 회귀 확인

완료 기준:

- 새 테스트 통과

## 2차 공정

### 공정 6. 파트 게이트

작업:

1. Part 1/2/3 각각에 로컬 품질 게이트 추가
2. 실패 시 해당 파트만 재생성

예상 효과:

- 중후반부 붕괴 감소

### 공정 7. 후보 생성 + 선택

작업:

1. blueprint 후보 2개
2. Part별 후보 2개
3. 로컬 점수 + critic 점수로 선택

예상 효과:

- 평균 품질보다 하한선이 크게 개선됨

### 공정 8. critic 분리

작업:

1. writer provider와 critic provider 분리
2. critic prompt 표준화

예상 효과:

- 생성 모델 편향을 평가 모델이 상쇄

## 3차 공정

### 공정 9. 회귀셋 운영

작업:

1. 고정 topic 세트 운영
2. provider별 결과 저장
3. 점수와 실패 유형 집계

예상 효과:

- 감이 아니라 데이터로 안정성 개선 가능

## 권장 운영값

Claude CLI 도입 직후 권장값:

- `STORY_LLM_PROVIDER=claude_cli`
- `CLAUDE_CLI_MODEL=sonnet`
- `STORY_LLM_TIMEOUT_SEC=180`

초기 운영 원칙:

1. fallback 결과 업로드 금지
2. 실패는 재시도 UX로 넘길 것
3. 고정 토픽 회귀셋을 주기적으로 돌릴 것
