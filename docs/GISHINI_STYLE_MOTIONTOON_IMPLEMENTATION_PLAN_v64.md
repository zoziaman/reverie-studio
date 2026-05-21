# Gishini-Style Motiontoon Implementation Plan v64
Last updated: 2026-03-15

> Superseded note, 2026-05-22: For video-toon character consistency, follow
> `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md` first. The active direction is
> pack-level actor pools, episode role casting, and scene-level actor
> references before renderer feature expansion.

## 1. 즉시 구현 순서

1. planner 출력에 `scene_type`, `motion_priority`, `shorts_candidate` 추가
2. pack schema에 `motiontoon`, `motion_props`, `scene_motion_rules` 추가
3. `motiontoon_director` 추가
4. Remotion 입력을 단일 이미지에서 layered scene graph로 확장
5. 아래 5개 프리미티브를 먼저 붙임
   - blink
   - mouth flap
   - idle drift
   - impact shake
   - snap zoom
6. 같은 scene graph에서 9:16 숏츠 프레이밍 지원

## 2. 1차 마일스톤 정의

Definition of done:
- 한 캐릭터가 blink 가능
- 화자 캐릭터가 입 플랩 가능
- 한 소품 강조 애니메이션 가능
- 충격 순간 shake 또는 snap zoom 가능
- 하나의 generated plan에서 shorts-ready beat 표시 가능

이 단계만 성공해도 카테고리 체감이 바뀐다.

## 3. 1차 적용 팩 순서

적용 순서:
- `senior_scam_alert`
- `horror_v59`
- `senior_life_saguk`

처음부터 전 팩에 일괄 적용하지 않는다.

## 4. 하드 룰

다음 방식으로 만들면 안 된다.
- 공포 전용 하드코딩
- 사기팩 전용 하드코딩
- 렌더러 안의 임시 애니메이션 예외처리 누적

반드시 `팩이 통제하는 공용 motiontoon layer`로 만든다.
