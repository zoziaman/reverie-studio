# Reverie v63 통합 설계서

최종 갱신: 2026-03-10

## 1. 목적

이 문서는 Reverie Studio의 현재 구조를 코드 기준으로 재정의하고,  
리팩토링, 성능 최적화, 실패 복구, 경쟁력 강화를 한 문서 안에서 정렬하기 위한 기준 설계서다.

핵심 원칙은 기존 팩 매뉴얼을 그대로 따른다.

- 코드에 장르별 하드코딩 조건문을 추가하지 않는다.
- 프롬프트와 스타일 자산은 `get_prompt("key")` 또는 팩 로더를 통해 로딩한다.
- 새 장르는 새 팩으로 확장하고, 코드 수정은 0줄을 목표로 한다.
- 톤/트위스트/카메라워크/스타일 풀은 코드가 아니라 팩 데이터에서 읽는다.

## 2. 현재 구조 요약

현재 실제 제품은 다음 5개 축으로 움직인다.

1. GUI: `src/gui`
2. 제작 파이프라인: `src/pipeline`, `src/modules_pro`
3. 설정/팩 로딩: `src/config`, `src/utils`
4. 렌더링: Remotion 기반 조합
5. 외부 연동: Gemini, SD WebUI, GPT-SoVITS, YouTube, Firebase

2026-03-10 기준 즉시 반영된 구조 개선은 다음과 같다.

- `modules_pro -> pipeline` 역방향 의존을 공용 런타임 유틸로 분리했다.
- `src/utils/runtime_utils.py`를 도입해 경로/출력/ffprobe 보조 함수를 공통 계층으로 이동했다.
- `pipeline`에 있던 공용 유틸 의존 때문에 생기던 구조 꼬임을 줄였다.
- 파이프라인의 체크포인트 재개 기능을 GUI 경로까지 연결했다.

## 3. 현재 강점

- 팩 중심 구조가 이미 존재한다.
- 썸네일, 시나리오, TTS, 이미지, Remotion 렌더링이 하나의 생성 체인으로 묶여 있다.
- `ProductionCheckpoint` 기반 단계별 재개 구조가 이미 파이프라인에 있다.
- GUI, 배치 큐, 팩 시스템, 라이선스 시스템이 분리되어 있어 상용화 기반은 갖춰져 있다.

## 4. 현재 구조적 문제

### 4.1 큰 단일 파일

다음 파일들은 분해 우선순위가 높다.

- `src/modules_pro/scenario_planner.py`
- `src/modules_pro/script_writers.py`
- `src/pipeline/image_pipeline.py`
- `src/pipeline/orchestrator.py`
- `src/pipeline/tts_manager.py`
- `src/gui/auto_optimizer_dialog.py`
- `src/gui/license_generator_gui.py`

### 4.2 예외 처리 품질 저하

- `except Exception`와 `pass`가 많아 장애 원인 추적이 약하다.
- 결과적으로 GUI에서는 “실패했다”만 보이고 어느 단계에서 왜 멈췄는지 찾기 어렵다.

### 4.3 부트스트랩 오염

- `sys.path.append(...)` 사용 지점이 많다.
- 개발 환경, 배포 환경, 테스트 환경이 import 우연성에 기대고 있다.

### 4.4 생성물과 소스 트리 혼재

- `src/data` 아래 대용량 생성물이 섞여 있다.
- 테스트, 백업, 리뷰, 배포 패키징 모두 느려진다.

## 5. 목표 아키텍처

목표는 “팩 중심 런타임 + 얇은 GUI + 재시작 가능한 파이프라인”이다.

```text
GUI
  -> Application Services
    -> Pipeline Orchestrator
      -> Stage Services
        -> External Adapters
          -> Local/Cloud Engines

Pack Runtime
  -> prompts / styles / voices / visual rules / policy

State & Ops
  -> checkpoint / queue / logs / metrics / cache / temp cleanup
```

### 5.1 계층 정의

- GUI 계층
  - 상태 입력, 진행률, 작업 승인, 실패 재시작만 담당
  - 생성 규칙을 직접 가지지 않음

- Application Service 계층
  - 작업 단위 실행, 배치 실행, 재시작, 취소, 검증 담당

- Pipeline Stage 계층
  - `thumbnail`, `tts`, `images`, `assemble`, `finalize`를 개별 단계 서비스로 유지

- Adapter 계층
  - Gemini, SD WebUI, SoVITS, ComfyUI, YouTube, Firebase를 어댑터로 격리

- Pack Runtime 계층
  - 장르/채널/스타일/카메라/프롬프트/품질 정책을 모두 팩에서 제공

## 6. 실패 복구 설계

### 6.1 현재 상태

파이프라인에는 이미 체크포인트 기반 재개 구조가 있다.

- 체크포인트 저장 객체: `ProductionCheckpoint`
- 저장 시점:
  - 썸네일 완료 후
  - TTS 완료 후
  - 이미지 완료 후
  - 예외 발생 직전
- 성공 시 체크포인트 파일 삭제

### 6.2 2026-03-10 즉시 보강

이번 작업에서 아래가 실제 코드에 반영됐다.

- GUI 옵션에 `실패 시 체크포인트부터 재개` 추가
- 직접 생성 경로에 재개 플래그 연결
- 미리보기 승인 후 생성 경로에 재개 플래그 연결
- 배치 큐 저장/실행 경로에 재개 플래그 연결
- 8GB VRAM 보호용 SD 해상도/step/Remotion 동시성 안전 한계 추가

### 6.3 목표 동작

- 사용자가 재개 옵션을 켜면, 같은 프로젝트 JSON 재실행 시 마지막 완료 단계부터 이어간다.
- 체크포인트는 성공 시 자동 삭제한다.
- 재개 시 현재 단계, 재개 여부, 이전 산출물 재사용 여부를 로그에 남긴다.
- 체크포인트가 손상되면 새로 시작하되, 손상 원인을 로그에 남긴다.

### 6.4 다음 개선

- 실패한 마지막 JSON 경로를 GUI에서 “재시도” 버튼으로 바로 재실행
- 체크포인트 파일 무결성 해시 저장
- 단계별 산출물 캐시 정책 명문화

## 7. 리팩토링 우선순위

### P0

- 큰 파일 분해
- 체크포인트 재개를 모든 GUI 경로에 일관 적용
- 공용 유틸의 계층 역전 제거

### P1

- `except Exception/pass`를 명시적 예외 + 구조화 로그로 전환
- `sys.path.append(...)` 제거
- `src/data`를 런타임 작업 디렉터리로 분리

### P2

- 단계 서비스 공통 인터페이스화
- Job/Result/Checkpoint 스키마 통합
- GUI 상태와 파이프라인 상태의 모델 분리

## 8. 생성 병목 분석

| 병목 | 원인 | 영향 | 해결 방향 |
| --- | --- | --- | --- |
| 시나리오 생성 | LLM 호출 직렬화 | 초기 대기시간 증가 | 프롬프트 캐시, 주제 생성/플랜 생성 분리, 실패 재시도 정책 분리 |
| TTS 생성 | 문장 수만큼 직렬 처리 | 긴 영상에서 가장 오래 걸림 | 문장 배치화, 캐릭터별 워커 풀, 이미 생성한 음성 해시 캐시 |
| 이미지 생성 | SD 모델 재로딩과 VRAM 압박 | 중간 정지와 처리량 저하 | persistent worker, VRAM 정책 고정, image prompt dedupe |
| Remotion 렌더 | Node 시작 비용 + temp I/O | 마지막 단계 지연 | 렌더 워커 상주, temp 디렉터리 정리, render props 최소화 |
| 파일 I/O | 생성물과 소스 혼재, copy2 중심 | SSD 사용량 증가 | 런타임 작업 디렉터리 분리, hash 기반 재사용 |
| 배치 큐 | 실패 시 동일 작업 재사용 약함 | 운영 회복력 저하 | last failed job resume, retry policy, failed artifact registry |

8GB VRAM 기준 현재 즉시 적용된 안전값:

- 이미지 SD 입력 최대: 768x432
- 썸네일 SD 입력 최대: 1280x720
- 일반 이미지 step cap: 18
- 썸네일 step cap: 20
- Remotion concurrency cap: 2

## 9. 경쟁력 강화를 위한 추가 기능

### 9.1 반드시 추가할 것

- 팩 검증기
  - 새 팩 등록 시 JSON 스키마, 프롬프트 placeholder, 필수 자산을 자동 검사

- 생성 비용/시간 대시보드
  - 프로젝트별 LLM 호출 수, 이미지 장수, TTS 시간, 렌더 시간, 실패 단계 기록

- 실패한 작업 즉시 재시도
  - GUI에서 마지막 실패 작업을 동일 JSON 기준으로 바로 재개

- 에셋 중복 제거 캐시
  - 같은 문장 TTS, 같은 프롬프트 이미지, 같은 썸네일 조합은 재사용

### 9.2 경쟁 제품 대비 우위를 만들 기능

- 로컬/클라우드 하이브리드 라우팅
  - SD/SoVITS가 느리거나 죽으면 클라우드 대체 경로로 전환

- 트렌드 수집기 + 자동 기획 후보군
  - 유입 키워드, 댓글, 검색 트렌드, 기존 성과를 조합해 주제 후보 제안

- A/B 썸네일/제목 실험 패키지
  - 업로드 전 후보 2안 생성, 내부 점수화 또는 운영자 선택 지원

- 팩 마켓/팩 배포 워크플로우
  - 팩을 제품 자산으로 관리할 수 있어야 확장성과 수익성이 생긴다

## 10. 설계 결론

Reverie의 핵심 경쟁력은 “팩 중심 자동 생성기”다.  
따라서 코드 경쟁력은 장르별 기능 추가가 아니라 다음에서 나온다.

- 팩 추가만으로 새 채널을 열 수 있는 구조
- 실패해도 이어서 가는 안정성
- 생성 시간을 줄이는 캐시와 워커 구조
- 운영자가 통제할 수 있는 GUI와 로그

이 설계서는 `docs/V63_INTEGRATED_SPEC.md`와 `docs/V63_INTEGRATED_PROCESS.md`를 함께 봐야 완성된다.
