# Reverie v63 문서 인덱스
최종 갱신: 2026-03-15

이 문서는 현재 기준 문서와 보조 설계 문서를 구분하기 위한 운영 인덱스다.

## 정본 문서

| 문서 | 목적 | 대상 |
| --- | --- | --- |
| `docs/V63_INTEGRATED_DESIGN.md` | 현재 구조, 목표 아키텍처, 병목, 리팩토링 방향 정의 | 개발/아키텍처 |
| `docs/V63_INTEGRATED_SPEC.md` | 기능 요구사항, 품질 기준, 운영 기준, 인수 조건 정의 | 개발/기획/QA |
| `docs/V63_INTEGRATED_PROCESS.md` | 단계별 공정, 실패/재시도 규칙, 테스트/배포 절차 정의 | 개발/운영 |

## 집중 설계 문서

| 문서 | 목적 | 대상 |
| --- | --- | --- |
| `docs/GISHINI_STYLE_MOTIONTOON_DESIGN_v64.md` | 기시니식 제한 애니메이션 영상툰 모드의 구조, 팩 확장, 렌더 변경 설계 | 기획/개발/렌더 |
| `docs/GISHINI_STYLE_MOTIONTOON_IMPLEMENTATION_PLAN_v64.md` | 위 설계의 실제 구현 순서와 1차 마일스톤 정리 | 개발 |

## 최신 문서화 규칙

1. 구조 결정은 `V63_INTEGRATED_DESIGN.md`를 먼저 수정한다.
2. 요구사항이나 인수 조건이 바뀌면 `V63_INTEGRATED_SPEC.md`를 먼저 수정한다.
3. 실제 작업 순서나 운영 절차가 바뀌면 `V63_INTEGRATED_PROCESS.md`를 먼저 수정한다.
4. 특정 기능의 집중 설계는 별도 문서로 두되, 정본 문서와 충돌하면 정본 기준을 우선한다.

## 정리된 구버전 문서

| 문서 | 상태 | 비고 |
| --- | --- | --- |
| `docs/REFACTORING_DESIGN_v60.md` | Superseded | 통합 설계로 이관 |
| `docs/PIPELINE_OPTIMIZATION_v62.md` | Superseded | 통합 설계/공정으로 이관 |

## 운영 규칙

- 중복 문서가 새로 생기면 삭제보다 먼저 `정본 링크 + 용도`를 명시한다.
- 보조 설계 문서는 실제 구현을 밀기 위한 문서로만 유지한다.
- 배포, 보안, 라이선스 규칙은 기존 매뉴얼과 충돌 시 매뉴얼이 우선이다.
