# 캐릭터 턴어라운드(다각도) 확장 설계도

> 목적: 현재 `actor_model`(단일 각도 + 표정/포즈/파츠 + 레이어 합성)을 **다각도(앞/좌/우/뒤) 턴어라운드 세트**로 확장하여, 사장님이 보는 채널처럼 캐릭터가 서로 마주보고/옆을 보고/돌아서는 장면 연출을 자동화한다.
>
> 성격: **제거(위험)가 아니라 확장(안전)**. 기존 단일 각도 동작은 그대로 두고 angle 차원을 얹는다.
> 상태: 설계(Design) — 승인 후 단계별 구현.

---

## 1. 현재 구조 (코드 확인 완료)

| 구성 | 위치 | 내용 |
|---|---|---|
| 배우 모델 패키지 | `assets/actor_models/<actor_id>/` | golden-cast 기준 + 변형 에셋 |
| 변형 키 | `variant_key = "표정_포즈"` (예: `neutral_standing`) | actor_model.py `_variant_parts` |
| 코어 표정 | `neutral / talking / blink` (+ 감정 표정) | actor_model.py `_variant_groups` |
| 포즈 | standing/sitting/walking/running | character_library_manager `DEFAULT_POSES` |
| 얼굴 파츠 | eye_shapes(eyes_open/blink) · mouth_shapes(mouth_closed/talking) | layering_contract |
| 레이어 계약 | `layering_contract`: canvas, anchor_points{actor_root, mouth_center, eye_center}, layer_order[variant_base, eye_layer, mouth_layer], naming_policy | actor_model.py |
| 합성 | layered_cutout + 알파 스프라이트 → 배경 위 합성 | `motiontoon_asset_pipeline`, `layered_cutout.py` |
| 장면 계약 | 필수 필드 `[scene_id, role_id, actor_id, emotion, shot_type]` | videotoon_contract.py |
| 포즈 제어 | **ControlNet OpenPose** (`control_v11p_sd15_openpose`, `pose_reference_path`) | videotoon_local.py |

**빠진 것 = `angle`(시선 방향/각도).** actor_model 생성 프롬프트는 일부러 "head angle consistent"로 단일 각도 고정. flip/turnaround 없음.

---

## 2. 확장 목표

- 캐릭터당 **각도 세트**: `front`(정면), `left`(좌측), `right`(우측), `back`(뒷모습). 최소 셋: front + left + right.
- 장면별로 캐릭터 **facing**(어디를 보는지)을 정하고, 그에 맞는 각도 스프라이트를 합성.
- 기존 표정/포즈/파츠 시스템과 **곱(matrix)으로 결합**: `표정 × 포즈 × 각도`.

---

## 3. 데이터 모델 변경 (구체)

### 3.1 변형 키에 angle 추가
- 현재: `variant_key = "{expression}_{pose}"`
- 변경: `variant_key = "{expression}_{pose}_{angle}"` (예: `neutral_standing_front`, `talking_standing_left`)
- `_variant_parts()` 확장: `(expression, pose, angle)` 3-튜플 반환. **angle 누락 시 기본값 `front`** → 기존 2-파트 키 하위호환.
- `_variant_groups()`에 `angles` 그룹 추가.

```python
# actor_model.py _variant_parts (확장 예시)
def _variant_parts(variant_key: str) -> tuple[str, str, str]:
    parts = variant_key.split("_")
    expression = parts[0] if parts else variant_key
    pose = parts[1] if len(parts) > 1 else "standing"
    angle = parts[2] if len(parts) > 2 else "front"   # 하위호환 기본값
    return expression, pose, angle
```

### 3.2 angle 상수 + naming_policy
```python
DEFAULT_ANGLES = {
    "front": {"prompt": "facing forward, front view, looking at viewer", "flip_of": None},
    "left":  {"prompt": "facing left, left three-quarter / profile view", "flip_of": None},
    "right": {"prompt": "facing right, right three-quarter / profile view", "flip_of": "left"},  # 좌 flip으로 대체 가능
    "back":  {"prompt": "back view, seen from behind, back of head", "flip_of": None},
}
```
- `flip_of`: `right`는 `left`를 좌우 반전해 싸게 생성(1단계). 머리 가르마/액세서리 비대칭이 심하면 별도 생성으로 승격(2단계).

### 3.3 layering_contract: 각도별 앵커
- 문제: 측면/후면은 `mouth_center`/`eye_center`가 정면과 다른 위치 → 같은 앵커로 입/눈 레이어 합성하면 어긋남.
- 변경: `anchor_points`를 **각도별로** 보관.
```jsonc
"anchor_points": {
  "front": { "actor_root": {...}, "mouth_center": {...}, "eye_center": {...} },
  "left":  { "actor_root": {...}, "mouth_center": {...}, "eye_center": {...} },
  "right": { ... },   // left flip 시 x 미러링으로 자동 산출 가능
  "back":  { "actor_root": {...} }   // back은 눈/입 레이어 없음
}
```
- 하위호환: 기존 평면 `anchor_points`(각도 무관)는 `front`로 승격해 읽기.
- `back` 각도: 얼굴 파츠(blink/talking) **비활성** → layer_order에서 eye/mouth 레이어 스킵.

### 3.4 장면 계약(videotoon_contract)에 facing 추가
- 현재 필수 필드: `[scene_id, role_id, actor_id, emotion, shot_type]`
- 추가: `facing` (값: `front|left|right|back`, 기본 `front`) — **선택 필드로 추가**(누락 시 front, 기존 팩 안 깨짐).
- `build_scene_specs_from_production`의 캐릭터 스펙에 `facing` 전달 → 합성 입력까지 흐르게.

---

## 4. 생성 파이프라인 (각도 에셋 만들기)

### 4.1 1단계 (싸게 시작) — flip + 정면 베이스
- 각 캐릭터: `front` 생성(기존 방식) + `left` 생성 → `right = left를 좌우 flip`. `back`은 생략 가능(필요 채널만).
- 구현: character_library_manager의 시트 생성에 angle 루프 추가, right는 PIL `transpose(FLIP_LEFT_RIGHT)`.
- 장점: 추가 SD 호출 최소, 즉시 좌/우 마주보기 가능.

### 4.2 2단계 (정밀) — ControlNet OpenPose 기반 턴어라운드
- 이미 OpenPose 인프라 보유(`control_v11p_sd15_openpose`).
- 각도별 **OpenPose 스켈레톤 레퍼런스**(front/left/right/back 포즈 뼈대)를 두고, golden-cast 정체성(IP-Adapter/reference)을 유지한 채 각 각도 생성 → 일관성 높은 진짜 턴어라운드.
- right도 별도 생성(비대칭 정확). back도 생성.

### 4.3 커버리지/검증
- actor_model 검증기에 "필수 각도 커버리지" 추가(예: front 필수, left/right 권장).
- 누락 각도 요청 시 fallback: `right→left flip→front` 순.

---

## 5. 합성 로직 (compositing)

- 스프라이트 선택 키: `(actor_id, expression, pose, angle)`.
- `motiontoon_asset_pipeline` / layered_cutout 의 스프라이트 조회에 angle 파라미터 추가.
- `right`가 flip 파생이면 합성 시 base를 미러링하고 angle별 앵커(미러 x)로 눈/입 레이어 배치.
- `back`: 얼굴 파츠 레이어 생략, base만 합성.

---

## 6. 장면 블로킹 로직 (누가 어디를 보는가) — 자동화의 핵심

- **위치**: `scenario_planner` / `visual_storytelling_director`가 장면 생성 시 결정.
- 규칙(초안):
  - 대화 2인: 화자/청자 마주보게 → 한 명 `right`, 다른 한 명 `left`. 화자 전환 시 facing 유지(180도 규칙).
  - 독백/나레이션 대상: `front`.
  - 이동/퇴장: 진행 방향 따라 `left`/`right`, 돌아섬은 `back`.
  - shot_type(클로즈업 등)과 결합: 클로즈업은 front/3-4 우선.
- 출력: 각 장면 캐릭터 스펙에 `facing` 기록 → videotoon_contract → 합성.

---

## 7. 단계별 구현 계획 (안전, 확장형)

| 단계 | 내용 | 검증 |
|---|---|---|
| **T1** | 데이터 모델: `_variant_parts` 3-파트화 + `DEFAULT_ANGLES` + naming_policy(angle) + 하위호환 기본 front | 기존 팩 로드/859 테스트 그대로 통과 |
| **T2** | layering_contract 각도별 anchor + back 파츠 스킵 + 검증기 angle 커버리지 | actor_model 검증 테스트 |
| **T3** | 생성 1단계(front+left+flip right) character_library_manager에 angle 루프 | 샘플 캐릭터로 4각도 에셋 생성 확인 |
| **T4** | 장면 계약 `facing` 추가 + 합성 angle 파라미터 연결 | 단위 테스트(장면→스프라이트 선택) |
| **T5** | 블로킹 로직(대화 마주보기 규칙) scenario/visual_director | 플랜 JSON에 facing 정상 기록 |
| **T6** | 생성 2단계(OpenPose 턴어라운드)로 품질 승격 (선택) | 실렌더 비교 (사장님 확인) |
| 전 구간 | 각 단계 후 import + 859 테스트, 기존(front-only) 동작 회귀 없음 확인 | |

> 헤드리스 한계: 최종 영상 합성 결과(특히 T4~T6 합성 품질)는 사장님이 실렌더로 확인 필요.

---

## 8. 리스크 / 주의

- **앵커 정합**: 각도별 눈/입 중심이 달라 정밀 좌표 필요. 잘못되면 입/눈이 떠 보임 → T2에서 각도별 앵커 필수.
- **flip 비대칭**: 가르마·점·액세서리 좌우 비대칭 캐릭터는 flip이 어색 → 2단계(별도 생성)로 승격.
- **back 처리**: 뒷모습은 표정/립싱크 불가 → 합성에서 파츠 레이어 끄기.
- **기존 팩 호환**: angle 누락 = front로 동작해야 함(전 구간 기본값 보장).
- **데이터량 증가**: 표정×포즈×각도 곱 → 에셋 수 증가. 커버리지를 "필요한 조합만" 생성하도록 lazy 생성 권장.

---

## 9. 결론
- 현재 시스템은 **2D 퍼펫 합성 방법론을 이미 구현**(golden-cast + 표정/포즈/파츠 + 레이어). 채널들과 같은 방식.
- 유일한 빠진 축 = **각도(turnaround)**. 이를 variant 키·앵커·장면 facing·블로킹에 더하면 "캐릭터가 서로 마주보는" 연출이 자동화됨.
- OpenPose 인프라가 이미 있어 2단계 정밀 생성까지 무리 없음.
