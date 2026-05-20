# Gishini-Style Motiontoon Design v64
Last updated: 2026-03-15

## 1. 목적

이 문서는 Reverie를 `정적 이미지 + 카메라 효과` 중심 파이프라인에서 `제한 애니메이션 영상툰 파이프라인`으로 확장하기 위한 설계를 정의한다.

목표는 풀애니메이션이 아니다.

목표는 다음과 같다.
- 단순하고 읽기 쉬운 그림체
- 장면 단위 컷아웃 모션
- 감정 타이밍에 맞는 패널 연출
- 소품 중심 강조 연출
- 팩이 장르별 모션 문법을 통제하는 구조

즉 Reverie는 `정적 슬라이드 생성기`가 아니라 `팩 기반 motiontoon 엔진`으로 가야 한다.

## 2. 문제 정의

현재 Reverie의 강점:
- 대본 생성
- 훅/콜드오픈 생성
- 썸네일/제목 생성
- 정적 일러스트 기반 장면 연출
- 자막, SFX, BGM, 최종 렌더 자동화

현재 Reverie의 약점:
- 장면 내부의 캐릭터 움직임
- 눈깜빡임, 입모양, 고개/몸 미세 움직임
- 핸드폰, 문, 서류, 송금내역 같은 소품 애니메이션
- 영상툰식 컷 분할과 강조 리듬

그래서 지금 결과물은 `강한 정적 드라마 영상`에 가깝고, 목표는 `제한 애니메이션 영상툰`이다.

이 차이는 줌/패닝만으로는 메울 수 없다.

## 3. 목표 상태

모션툰 모드는 아래를 만족해야 한다.

1. 현재 팩 우선 구조를 유지한다.
2. Python 코드에 장르별 조건문을 추가하지 않는다.
3. 단순한 그림체여도 살아 있는 영상처럼 보이게 한다.
4. 풀애니 없이도 명확한 장면 모션을 만든다.
5. 팩이 장르별 모션 문법을 결정한다.
6. 장편과 숏츠를 같은 플랜에서 뽑는다.

## 4. 비목표

이번 설계의 비목표:
- TV 애니 수준의 프레임 애니메이션
- phoneme 단위 정교한 립싱크
- Spine/Live2D 급 리깅
- 모션캡처
- 복잡한 물리 시뮬레이션

우리가 필요한 것은 `제한 애니메이션 문법이 살아 있는 영상툰`이다.

## 5. 품질 기준

목표 기준은 다음과 같다.

- 일반적인 정적 AI 슬라이드 영상보다 확실히 살아 있어야 한다.
- 프리미엄 스튜디오 애니 수준은 요구하지 않는다.
- 단순한 그림체라도 타이밍과 움직임으로 몰입을 만들어야 한다.

핵심 품질 요소:
- 컷 타이밍
- 감정에 맞는 모션 선택
- 소품 강조
- 패널 리듬
- 충격 순간의 카메라 문법

즉 그림 퀄리티보다 `모션 선택과 타이밍`이 더 중요하다.

## 6. 핵심 원칙

시스템은 `이미지 생성`이 아니라 `모션 문법`을 생각해야 한다.

각 장면은 최소 아래 유형 중 하나로 분류된다.
- 정지 강조 장면
- 대사 중심 장면
- 대치 장면
- 충격 진입 장면
- 소품 폭로 장면
- 리액션 장면
- 숏츠 추출 장면

모션은 장면 유형에 따라 선택되고, 장르별 성격은 팩이 정한다.

## 7. 출력 티어 정의

### Tier 0: Static Story Video
- 현재 기본형
- 정적 이미지
- Ken Burns
- 전환
- 자막

### Tier 1: Limited Motion Story Video
- 정적 이미지 + 선택적 레이어 모션
- 눈깜빡임
- 입 플랩
- 고개/몸 미세 이동
- 소품 강조
- 충격 줌/쉐이크

### Tier 2: Motiontoon Video
- 레이어드 씬 그래프
- 표정 스왑
- 포즈 스왑
- 소품 애니메이션
- 컷 분할
- 숏츠용 세로 프레이밍

1차 목표는 Tier 1.5에서 Tier 2-lite다.

## 8. 필수 모션 프리미티브

### 8.1 캐릭터 프리미티브
- eye blink
- mouth flap
- idle breathing drift
- head nod
- head turn micro-shift
- shoulder recoil
- hand raise / lower
- tremble
- freeze hold

### 8.2 감정 프리미티브
- anger pulse
- fear tremble
- sadness collapse
- hesitation pause
- late realization stillness
- shame look-away

### 8.3 소품 프리미티브
- phone screen popup
- text message highlight
- bank alert zoom-in
- paper reveal
- envelope drop
- door open crack
- light flicker
- object shake
- portrait/photo zoom

### 8.4 카메라/패널 프리미티브
- snap zoom
- slow push-in
- whip cut
- impact shake
- split-panel layout
- insert cutaway
- freeze emphasis frame
- silhouette hold

## 9. 팩 우선 규칙

이 기능도 반드시 팩이 통제해야 한다.

Python 코드에서 아래와 같은 분기는 금지한다.
- `if genre == "scam_alert": use phone animation`
- `if genre == "horror": blink faster`

대신 팩이 정의해야 할 것:
- motion profiles
- expression sets
- prop tags
- scene emphasis rules
- shorts extraction bias

## 10. 팩 스키마 확장

### 10.1 새 설정 블록

```json
{
  "motiontoon": {
    "enabled": true,
    "mode": "limited_animation",
    "default_scene_type": "dialogue",
    "blink_enabled": true,
    "mouth_flap_enabled": true,
    "shorts_vertical_ready": true
  }
}
```

### 10.2 캐릭터 모션 프로필

```json
{
  "characters": {
    "young_woman": {
      "expressions": ["neutral", "sad", "angry", "scared", "shocked"],
      "poses": ["front", "side", "hand_up", "slumped"],
      "motion_profile": {
        "idle": "soft_breathing",
        "anger": "sharp_pulse",
        "fear": "micro_tremble",
        "sad": "slow_collapse"
      }
    }
  }
}
```

### 10.3 소품 애니메이션 규칙

```json
{
  "motion_props": {
    "phone": ["popup", "message_flash", "screen_zoom"],
    "document": ["slow_reveal", "impact_drop"],
    "door": ["crack_open", "slam_shake"]
  }
}
```

### 10.4 장면 모션 규칙

```json
{
  "scene_motion_rules": {
    "confrontation": ["mouth_flap", "impact_shake", "snap_zoom"],
    "reveal": ["prop_zoom", "freeze_hold", "reaction_cut"],
    "suspense": ["blink_pause", "slow_push", "negative_space_hold"]
  }
}
```

## 11. 플래너 계층 변경

플래너는 더 이상 대본과 이미지 프롬프트만 뱉어서는 안 된다.

반드시 `motion beats`를 출력해야 한다.

### 11.1 새 출력 필드
- `scene_type`
- `dominant_emotion`
- `motion_priority`
- `speaker_focus`
- `prop_focus`
- `camera_punctuation`
- `shorts_candidate`

### 11.2 예시

```json
{
  "scene_type": "reveal",
  "dominant_emotion": "shock",
  "speaker_focus": "young_woman",
  "prop_focus": "document",
  "camera_punctuation": "snap_zoom",
  "motion_priority": "high",
  "shorts_candidate": true
}
```

### 11.3 장면 분류 기본 집합
- `idle_dialogue`
- `accusation`
- `reveal`
- `memory_object`
- `panic_call`
- `shock_entry`
- `closing_stillness`

분류 이름은 장르 중립이어야 하고, 해석은 팩이 한다.

## 12. 에셋 생성 전략

현재는 비트당 최종 이미지 1장을 만든다.

모션툰 모드에서는 레이어 단위 에셋이 필요하다.

### 12.1 최소 레이어 구성
- background
- character foreground
- optional prop overlay
- optional effect layer

### 12.2 캐릭터 변형

중요 캐릭터마다 최소:
- 기본 얼굴
- 표정 3~5종
- 포즈 2~4종
- mouth-open 변형
- eyes-closed 변형

이 정도면 제한 애니메이션 체감이 나온다.

### 12.3 생성 원칙

처음부터 정교한 리깅으로 가지 않는다.

우선순위는:
- expression swap sheet
- pose swap sheet
- alpha-cut 레이어

가장 적은 복잡도로 가장 큰 체감 상승을 주는 경로다.

## 13. 새 런타임 모듈

### 13.1 `motiontoon_director`
역할:
- planner scene beat를 motion directive로 변환
- pack motion rules 적용
- 장면별 프리미티브 결정

### 13.2 `layered_asset_builder`
역할:
- background / character / prop layer 준비
- 표정/포즈 variants 생성
- 캐릭터 variants 재사용 관리

### 13.3 `scene_graph_builder`
역할:
- 렌더 가능한 scene graph 구성
- 레이어 깊이와 타이밍 배치
- 모션 커브 부여

### 13.4 `motion_preset_library`
역할:
- blink, drift, shake, prop popup, impact zoom 같은 재사용 프리셋 제공

### 13.5 `shorts_cut_extractor`
역할:
- shorts_candidate와 shorts_plan을 받아 세로형 cut package로 변환

## 14. 렌더 아키텍처

현재 Remotion 기반은 유지하는 편이 맞다.

교체가 아니라 확장이다.

### 14.1 현재 입력
- scene list
- image path
- subtitle timing
- hook
- BGM/SFX

### 14.2 필요한 미래 입력
- scene graph
- 다중 레이어 이미지
- 레이어별 transform curve
- 표정 스왑 타이밍
- prop insert timing
- 16:9 / 9:16 프레이밍 프리셋

### 14.3 씬 구성 단위

각 씬은 최소 아래를 가져야 한다.
- background layer
- character layer(s)
- prop layer(s)
- effect layer
- camera track
- subtitle track

## 15. 숏츠 동시 설계

숏츠는 사후 변환이 아니라 초반부터 설계되어야 한다.

플래너와 모션 시스템은 의도적으로:
- `shorts_candidate` 비트 생성
- 세로 프레임에서 읽히는 focal composition
- 한 줄 대사 + 한 개 소품/표정 중심 연출

을 만들어야 한다.

### 15.1 숏츠 조건

숏츠 적합 장면의 조건:
- 감정 비트가 하나로 명확함
- 화자 또는 소품 포커스가 뚜렷함
- 한 줄 대사가 강함
- 좁은 프레임에서도 읽힘

### 15.2 팩별 숏츠 편향 예시
- horror: 침입 순간, 이상한 한마디, 실루엣
- scam alert: 문자/전화/송금 인지 순간
- life saguk: 공개 망신, 봉투/장부/혼서 공개, 맹세나 폭로

## 16. 구현 단계

### Stage 1: Motiontoon MVP
- planner에 `scene_type`, `shorts_candidate` 추가
- blink, mouth flap, drift, shake, snap zoom만 도입
- 숏츠 세로 프레이밍 연결
- 포즈 리깅은 아직 안 함

예상 결과:
- 현재 정적 슬라이드 대비 체감 상승
- 사용자 반응 검증 가능

### Stage 2: Character Variant System
- expression sets
- pose swap
- prop animation presets
- reaction insert cuts
- pack-level motion profiles

예상 결과:
- 영상툰 감각이 명확해짐

### Stage 3: Full Pack Motion Grammar
- scene graph runtime
- pack-defined motion rules
- per-pack prop libraries
- vertical-first shorts composition
- automated best-cut extraction

예상 결과:
- 일반 AI 슬라이드 채널과 차별화 가능

## 17. 리스크

### 17.1 에셋 폭증
표정/포즈를 과도하게 늘리면 생성 시간과 저장량이 급증한다.

대응:
- 주연 화자 중심으로만 variants 생성
- 표정/포즈 상한 고정
- 캐시 적극 사용

### 17.2 값싼 모션처럼 보일 위험
모션이 장면과 무관하면 오히려 정적 영상보다 못하다.

대응:
- 허용된 프리미티브만 사용
- 장면 유형에 따라 모션 선택
- 필요한 곳에서는 정지와 정적을 유지

### 17.3 렌더 비용 증가
씬 그래프와 레이어 합성으로 렌더 비용이 올라간다.

대응:
- Tier 0 / Tier 1 fallback 유지
- 선택된 팩이나 작업에만 motiontoon 적용
- 에셋 재사용 강화

### 17.4 팩 작성 난이도 증가

대응:
- 템플릿 기본값 제공
- 모션 프로필 3종 기본 탑재
  - soft drama
  - hard confrontation
  - suspense

## 18. 현실성 판단

이 설계가 현실적인 이유는 풀애니를 요구하지 않기 때문이다.

필요한 것은:
- planner 출력 강화
- 재사용 모션 프리셋
- 레이어 렌더 지원
- 팩 스키마 확장

즉 어렵지만 공상적인 수준은 아니다.

## 19. 1차 적용 추천 팩

우선 적용 대상:
- `senior_scam_alert`
- `horror_v59`
- `senior_life_saguk`

이유:
- 세 팩 모두 소품 강조와 선택적 캐릭터 모션 효과가 큼
- 숏츠 비트가 명확함
- 그림 디테일보다 컷 리듬 효과가 크게 먹힘

## 20. 결론

Reverie는 `기시니식 제한 애니메이션 영상툰 모드`를 추진하는 것이 맞다.

단순한 효과 레이어 추가가 아니라, 새로운 시각 런타임 티어로 봐야 한다.

정확한 1차 목표는:
- 풀애니 아님
- Live2D 아님
- 프레임 애니 아님

정확한 1차 목표는:
- `팩 기반 제한 애니메이션 motiontoon`

이 경로가 Reverie 결과물을 `정적 AI 슬라이드`에서 `살아 있는 영상툰`으로 끌어올리는 가장 현실적인 길이다.
