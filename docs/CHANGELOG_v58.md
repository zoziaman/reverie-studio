# Reverie Studio v58 Changelog

> 완전 팩화 (Complete Pack System)
> 릴리즈: 2026-02-06

---

## 개요

v58은 **완전 팩화** 업데이트입니다. 기존에 코드에 하드코딩되어 있던 모든 채널별 설정이 `.revpack` 파일로 이동되어, 코드 수정 없이 팩만 교체하면 완전히 다른 채널을 운영할 수 있습니다.

### 핵심 변경사항

- **Pack = Channel = YouTube Channel**: 하나의 팩이 하나의 YouTube 채널을 완전히 정의
- **하드코딩 제거**: TTS, SD, Hook 스타일, 시나리오 풀 등 모든 설정이 팩에서 로드
- **배포 친화적**: 기존 환경의 TTS/SD 모델을 그대로 사용, 팩은 설정값만 지정

---

## 새로운 .revpack 구조

```
*.revpack (ZIP)
├── manifest.json          # pack_name, pack_id, version, author, genre
├── settings.json          # 전체 설정 (v58 확장)
│   ├── style              # 기존
│   ├── content            # 기존
│   ├── characters         # 기존
│   ├── assets             # 기존
│   ├── tts                # v58 신규
│   ├── visual             # v58 신규
│   ├── hook_style         # v58 신규
│   ├── sd                 # v58 신규
│   ├── thumbnail          # v58 신규
│   └── video              # v58 신규
├── topics.json            # templates, tags, scenario (v58 확장)
│   └── scenario           # v58 신규: 시나리오 풀
└── prompts/
    ├── pd_system.txt
    ├── writer_system.txt
    └── sd_prompts.json
```

---

## v58 신규 필드

### 1. TTS 설정 (`settings.json > tts`)

```json
{
  "narrator": "narrator_female",
  "character_mapping": {
    "할머니": "grandma",
    "할아버지": "grandpa"
  },
  "default_emotion": "calm",
  "allowed_emotions": ["sad", "happy", "calm", "angry"],
  "emotion_weights": {"sad": 4, "happy": 3, "calm": 5}
}
```

### 2. Visual 설정 (`settings.json > visual`)

```json
{
  "character_system_enabled": false,
  "forced_style": {
    "force_positive": "flat vector illustration, dramatic pastel tones...",
    "force_negative": "realistic face, detailed face, photograph..."
  },
  "thumbnail_backgrounds": ["dramatic scene...", "emotional moment..."],
  "safe_fallbacks": ["empty room...", "rain on window..."]
}
```

### 3. Hook 스타일 (`settings.json > hook_style`)

```json
{
  "top_label": "【 막 장 】",
  "top_color": "#FFD700",
  "main_color": "#FFFFFF",
  "bg_color": [10, 10, 20],
  "duration": 4.0
}
```

### 4. SD 설정 (`settings.json > sd`)

```json
{
  "positive": "masterpiece, best quality...",
  "negative": "(worst quality:1.4)...",
  "cfg_scale": 6.0,
  "steps": 28,
  "model": ""
}
```

### 5. 썸네일 설정 (`settings.json > thumbnail`)

```json
{
  "text_default": "충격적인 결말",
  "style_guide": "dramatic, emotional"
}
```

### 6. 비디오 설정 (`settings.json > video`)

```json
{
  "pause_duration": 0.4,
  "zoom_speed": 1.0
}
```

### 7. 시나리오 풀 (`topics.json > scenario`)

```json
{
  "safe_templates": ["torn contract on desk...", "rain drops on window..."],
  "tone_pool": ["회한과 후회", "분노와 복수"],
  "relationship_pool": ["고부 갈등", "형제 갈등"],
  "twist_pool": ["오해가 진실로 드러남", "문서가 모든 것을 뒤집음"],
  "conflict_pool": ["재산/유산 분쟁", "출생의 비밀"]
}
```

---

## 수정된 파일

### 1. `src/config/pack_config.py`

- 신규 데이터클래스 추가:
  - `PackTTS`: narrator, character_mapping, emotions
  - `PackVisual`: forced_style, safe_fallbacks, thumbnail_backgrounds
  - `PackHookStyle`: top_label, colors, duration
  - `PackSD`: cfg_scale, steps, model
  - `PackThumbnail`: text_default, style_guide
  - `PackVideo`: pause_duration, zoom_speed
  - `PackScenario`: tone_pool, twist_pool, conflict_pool 등
- `load_pack()` 함수에서 모든 신규 필드 로드
- getter 함수 추가: `get_tts_settings()`, `get_visual_settings()`, `get_hook_style()`, `get_sd_settings()`, `get_video_settings()`, `get_scenario_pools()`, `get_safe_templates()`, `get_narrator()` 등

### 2. `src/modules_pro/visual_director.py`

- `_get_pack_config()`: 지연 로드로 순환 import 방지
- `_get_safe_fallbacks()`: 팩 우선, 하드코딩 폴백
- `_get_forced_style()`: 팩 우선, 하드코딩 폴백
- `_get_thumbnail_backgrounds()`: 팩에서 로드
- `_get_characters()`: 팩에서 로드
- `_is_character_system_enabled()`: 팩에서 로드

### 3. `src/modules_pro/scenario_planner.py`

- `get_scenario_pools()` import 추가
- `ChiefProducer.create_topic()`: 팩에서 tone_pool, relationship_pool, twist_pool 로드
- 하드코딩 풀은 폴백으로만 사용

### 4. `src/modules_pro/media_factory.py`

- `get_hook_style()`, `get_sd_settings()`, `get_video_settings()` import 추가
- Hook 장면 생성 시 팩의 hook_style 사용
- SD 이미지 생성 시 팩의 cfg_scale, steps 사용

### 5. `tools/pack_creator_full.py`

- v58 필드들을 `_assemble_pack_data()`에 추가
- `settings.json` 출력 시 tts, visual, hook_style, sd, thumbnail, video 포함
- `topics.json` 출력 시 scenario 섹션 포함

---

## 생성된 팩 (4개)

| 팩 파일 | 장르 | 설명 |
|---------|------|------|
| `horror_default.revpack` | horror | 기본 공포 채널 |
| `horror_mystery.revpack` | horror | 미스터리/괴담 특화 |
| `senior_touching.revpack` | senior | 감동/힐링 채널 |
| `senior_makjang.revpack` | senior | 막장 드라마 채널 |

---

## 호환성

- **하위 호환**: v57 팩도 로드 가능 (신규 필드는 기본값 사용)
- **폴백 패턴**: 팩에 값이 없으면 기존 하드코딩 값 사용
- **배포 환경**: 기존 TTS/SD 모델 그대로 사용, 팩은 설정값만 지정

---

## 마이그레이션 가이드

### 기존 채널을 v58 팩으로 전환

1. `assets/packs/` 폴더에 해당 채널 `.revpack` 파일 배치
2. GUI에서 채널 선택 시 자동으로 팩 로드
3. 또는 `load_pack("path/to/pack.revpack")` 직접 호출

### 새 팩 생성

1. `pack_creator_full.py` 실행
2. 챗봇과 대화하며 설정 수집
3. v58 필드들이 자동으로 포함된 `.revpack` 생성

---

## 알려진 이슈

- Windows 콘솔에서 한글/이모지 출력 시 cp949 인코딩 에러 (기능에는 영향 없음)
- `google.generativeai` deprecated 경고 (추후 `google.genai`로 마이그레이션 예정)

---

## v58.1.0 (2026-02-06)

### AI법 준수 - AI 제작 표기

영상 시작 시 좌측 상단에 "이 영상은 AI로 제작되었습니다" 문구가 3초간 페이드인/아웃으로 표시됩니다.

**Remotion 변경사항:**
```typescript
// RadioDrama.tsx - AiDisclosure 컴포넌트 추가
const AiDisclosure: React.FC<{ durationFrames: number }> = ({ ... }) => {
  // 페이드인 (0~15프레임) → 유지 → 페이드아웃 (마지막 15프레임)
};

// 새 Props
showAiDisclosure?: boolean;      // 기본: true
aiDisclosureDuration?: number;   // 기본: 3초
```

**Python 연동:**
```python
# remotion_assembler.py
assembler = RemotionAssembler(
    show_ai_disclosure=True,
    ai_disclosure_duration=3.0,
)
```

---

### TTS 볼륨 증폭

기존 2.5배에서 3.0배로 증폭하여 음성이 더 명확하게 들립니다.

```typescript
// RadioDrama.tsx
ttsVolume?: number;  // 기본: 3.0 (기존 2.5)

<Audio src={getAssetPath(audio.path)} volume={ttsVolume} />
```

---

### 자막 강조 효과

중요한 대사에 `★★★` 마커를 추가하면 자동으로 강조 처리됩니다.

**효과:**
- 빨간색 텍스트 (`#FF4444`)
- 10% 크게 표시
- 빨간 글로우 효과
- 어두운 빨간 배경 (`rgba(60,0,0,0.8)`)
- 펄스 애니메이션

**사용 예:**
```
대사: "사실... 네 친어머니는..." ★★★
→ 별표 제거 후 "사실... 네 친어머니는..." 으로 강조 표시
```

---

### 유튜브 최적화 프롬프트

PD/작가 시스템 프롬프트가 유튜브 알고리즘에 최적화되었습니다.

**PD 프롬프트 (`pd_system.txt`):**
- 첫 10초 후킹 규칙 필수화
- 3막 구조 강화 (충격 도입 → 반전 → 카타르시스)
- 시청자 유지 장치 배치

**작가 프롬프트 (`writer_system.txt`):**
- 첫 대사 충격/갈등 시작 규칙
- 감정 강조 대사 (★★★) 사용법
- 시청자 유지 대사 패턴

---

### 나레이터 설정 수정

`tts.narrator` 필드를 올바르게 읽도록 수정했습니다.

**수정 전:**
```python
pack_narrator = getattr(ACTIVE_PACK.assets, 'narrator', None)  # ❌ 잘못된 경로
```

**수정 후:**
```python
pack_narrator = getattr(ACTIVE_PACK.tts, 'narrator', None)  # ✅ 올바른 경로
```

---

### 제목 생성 개선

약한 제목을 자동으로 강력한 훅 제목으로 변환합니다.

```python
def _make_compelling_title(base: str, category: str, mode: str) -> str:
    makjang_hooks = ["그 돈의 진실", "숨겨온 비밀", "드러난 정체", ...]
    # 약한 제목 → 강력한 훅 제목으로 변환
```

---

### 수정된 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `remotion-poc/src/RadioDrama.tsx` | AI 제작 표기, 자막 강조, TTS 볼륨 |
| `src/modules_pro/remotion_assembler.py` | 신규 파라미터 추가 |
| `src/modules_pro/media_factory.py` | 나레이터 설정, RemotionAssembler 호출 |
| `src/modules_pro/scenario_planner.py` | 제목 생성 개선 |
| `assets/packs/senior_makjang/prompts/pd_system.txt` | 유튜브 최적화 |
| `assets/packs/senior_makjang/prompts/writer_system.txt` | 유튜브 최적화 |
| `assets/packs/senior_makjang.revpack` | 프롬프트 업데이트 |

---

## v58.2.1 (2026-02-06)

### TTS 볼륨 MoviePy 동기화 (핫픽스)

Remotion에서 TTS 볼륨 3배 증폭이 적용되었지만, MoviePy 오디오 합성 단계에서 원본 오디오로 덮어씌워지는 버그를 수정했습니다.

**문제:**
- Remotion: `ttsVolume: 3.0` 적용됨
- MoviePy: 원본 오디오 사용 → 볼륨 증폭 무효화

**수정:**
```python
# media_factory.py - _assemble_main_remotion()
TTS_VOLUME_MULTIPLIER = 3.0
voice = AudioFileClip(audio_path).volumex(TTS_VOLUME_MULTIPLIER)
```

**수정된 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `src/modules_pro/media_factory.py` | TTS_VOLUME_MULTIPLIER 추가, volumex(3.0) 적용 |

---

## v58.2.2 (2026-02-06)

### 후킹 화면 잘림 수정

후킹 장면이 잘려서 보이던 문제를 수정했습니다.

```python
# _create_hook_clip()
hook_clip = VideoClip(make_frame, duration=duration).set_fps(24)
hook_clip = hook_clip.resize((W, H))  # v58.2.2: 크기 강제 지정
```

---

### 자동 인트로 제거 + 트랜지션 구조 변경

자동 TTS 인트로 생성을 제거하고, 외부 인트로 파일만 사용하도록 변경했습니다.

**기존 구조:**
```
후킹 → 자동인트로(TTS) → pause(1.2초) → 본편
```

**변경된 구조:**
```
후킹(fadeout 1초) → [외부 인트로 있으면] → transition → 본편(fadein 1초)
```

**트랜지션 규칙:**
- 인트로 있음: 인트로 뒤 0.5초 검은 화면
- 인트로 없음: 후킹-본편 사이 1초 검은 화면

**외부 인트로 설정 방법:**
```json
// branding.json 또는 config
{
  "senior": {
    "intro_file": "assets/intros/senior_intro.mp4"
  }
}
```

**수정된 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `src/modules_pro/media_factory.py` | 후킹 resize 추가, 자동 인트로 제거, 트랜지션 구조 변경 |

---

## v58.2.3 (2026-02-06)

### TTS 성별 매핑 개선

"선영", "민영" 등 "영"으로 끝나는 여성 이름이 남자 목소리로 나오던 문제를 수정했습니다.

**변경사항:**
- `female_names`에 "영"으로 끝나는 여성 이름 추가
- `male_endings`에서 "영" 제거 (남녀 공용 글자)
- "영"으로 끝나는 이름은 앞글자로 성별 추론 (선영→여성, 태영→여성)

```python
# "영"으로 끝나는 이름 특별 처리
if last_char == "영":
    female_prefixes = ("선", "민", "수", "은", "미", "혜", ...)
    if first_char in female_prefixes:
        return "woman"
```

---

### 자막 길이 제한 + 분할 개선

한 화면에 너무 긴 자막이 표시되던 문제를 수정했습니다.

**변경사항:**
- 한 자막 최대 40자 제한
- 문장부호(. ? !) 외에 쉼표(,) 기준 추가 분할
- 15자 미만 짧은 조각은 이전 자막과 합침

**예시:**
```
[기존] 한 화면에 4-5줄 자막
"민우의 발걸음이 빨라질수록 뒤에서 들려오는 기차 소리의 박자도 기괴하게 속도를 높입니다.
안개는 이미 그의 시야를 완전히 가려버렸고, 차가운 철길의 감촉만이 유일한 이정표가 되어줍니다."

[변경] 적절히 분할
자막1: "민우의 발걸음이 빨라질수록 뒤에서 들려오는 기차 소리의 박자도 기괴하게 속도를 높입니다."
자막2: "안개는 이미 그의 시야를 완전히 가려버렸고"
자막3: "차가운 철길의 감촉만이 유일한 이정표가 되어줍니다."
```

**수정된 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `src/modules_pro/media_factory.py` | `_role_key_normalize()` 성별 매핑, `_split_into_sentences()` 자막 분할 |

---

## v58.2.4 (2026-02-06)

### 작가가 voice_type 직접 지정

작가가 대본 작성 시 `voice_type` 필드를 명시하면, 이름 기반 추론 없이 해당 목소리를 직접 사용합니다.

**작가 프롬프트 추가 내용:**
```
■ voice_type 필드 (v58.2.4 필수!)
각 대사에 voice_type을 반드시 지정하세요:
- narrator: 나레이션 (해설) - 팩에 따라 남/여 자동 결정
- grandma: 할머니 (연세 드신 여성)
- grandpa: 할아버지 (연세 드신 남성)
- woman: 중년 여성
- man: 중년 남성

예시:
{"role": "순자", "voice_type": "grandma", "emotion": "sad", "text": "내가 뭘 잘못했길래..."}
{"role": "철수", "voice_type": "man", "emotion": "angry", "text": "엄마는 맨날 그렇잖아요!"}
```

**사용 가능한 voice_type (모델 폴더 기준):**
| voice_type | 설명 | 감정 지원 |
|------------|------|----------|
| `narrator` | 나레이터 (팩별 자동: 시니어=여성, 공포=남성) | calm, fear |
| `grandma` | 할머니 | angry, calm, desperate, happy, sad, scared, whisper, worried |
| `grandpa` | 할아버지 | angry, calm, happy, sad, scared |
| `woman` | 중년 여성 | angry, calm, desperate, happy, sad, scared, whisper, worried |
| `man` | 중년 남성 | angry, calm, desperate, happy, sad, scared, whisper, worried |

**TTS 매핑 우선순위:**
1. `voice_type` 필드가 명시됨 → **그대로 사용** (추론 없음)
2. `voice_type` 없음 → 기존 `_role_key_normalize()` 로직으로 추론

**수정된 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `assets/packs/*/prompts/writer_system.txt` | voice_type 필드 사용 가이드 추가 |
| `src/modules_pro/media_factory.py` | `_resolve_tts_assets()` voice_type 파라미터 추가 |

---

## v58.3.0 (2026-02-06)

### GUI 멀티팩 큐 시스템

GUI에서 여러 팩을 순차적으로 작업할 수 있는 큐 시스템입니다.

**기존 문제:**
- 팩 하나 선택 → 완료까지 대기 → 다음 팩 선택
- 다른 팩 추가하려면 이전 작업이 끝날 때까지 기다려야 함

**해결:**
```
[새 워크플로우]
1. 팩 선택 + 수량 → "➕ 큐에 추가" 클릭
2. 다른 팩 선택 + 수량 → "➕ 큐에 추가" 클릭
3. 반복...
4. 📋 큐 버튼 → "▶️ 큐 실행"
5. 모든 작업 순차 자동 실행
```

**신규 버튼:**
- `➕ 큐에 추가`: 현재 설정을 큐에 추가 (팩+수량)

**사용 예시:**
```
senior_makjang  x 3개  → 큐에 추가
horror          x 2개  → 큐에 추가
senior_touching x 5개  → 큐에 추가
────────────────────────
📋 큐 → 총 10개 대기 중 → 실행
```

**수정된 파일:**
| 파일 | 변경 |
|------|------|
| `src/gui/main_window.py` | `_add_to_queue()`, `_run_queue()`, `_queue_worker()` 추가 |
| `src/utils/batch_queue.py` | `pack_id`, `prompt_mode` 필드 추가 |
| `src/gui/queue_manager_dialog.py` | 팩 ID 표시 개선 |

---

## v58.3.1 (2026-02-06)

### TTS 음성 모델 자동 폴백

`young_man`/`young_woman` 음성 모델이 없을 때 자동으로 `man`/`woman`으로 폴백하는 기능입니다.

**기존 문제:**
- `young_man`, `young_woman` voice_type 요청 시 해당 폴더에 `gpt_weights.ckpt`가 없으면 TTS 완전 실패
- calm 감정 폴백도 실패하여 영상 생성 중단

**해결:**
```python
# media_factory.py > _resolve_tts_assets()
voice_fallback_map = {
    "young_man": "man",
    "young_woman": "woman",
}

if not os.path.exists(gpt_w) and rk in voice_fallback_map:
    # 폴백 모델로 자동 전환
    rk = voice_fallback_map[rk]
```

**동작 예시:**
```
요청: young_man/happy
→ young_man 폴더 확인 → gpt_weights.ckpt 없음
→ man 폴더로 폴백 → gpt_weights.ckpt 존재
→ man/happy 사용
→ TTS 성공
```

**수정된 파일:**
| 파일 | 변경 |
|------|------|
| `src/modules_pro/media_factory.py` | `_resolve_tts_assets()`에 voice_fallback_map 추가 |

---

### 큐 시스템 pack_id 직접 로드

큐에서 각 팩별로 작업 실행 시 정확한 팩을 로드하도록 수정했습니다.

**기존 문제:**
- `senior_makjang` 큐 추가 → 실행 시 `load_default_pack("senior")` 호출
- 결과: 항상 `senior_touching.revpack` 로드 (makjang 팩 무시됨)

**해결:**
```python
# pack_config.py: load_pack_by_id() 함수 추가
def load_pack_by_id(pack_id: str) -> bool:
    # senior_makjang → senior_makjang.revpack
    # horror → horror_default.revpack
    ...

# main_window.py: _activate_pack_for_job() 수정
from config.pack_config import load_pack_by_id, ACTIVE_PACK
if load_pack_by_id(pack_id):
    self._add_log(f"[PACK] 팩 활성화: {ACTIVE_PACK.pack_name}")
```

**동작 예시:**
```
큐: [senior_makjang x1, senior_touching x1, horror x1]
실행:
  1. senior_makjang → senior_makjang.revpack 로드 ✅
  2. senior_touching → senior_touching.revpack 로드 ✅
  3. horror → horror_default.revpack 로드 ✅
```

**수정된 파일:**
| 파일 | 변경 |
|------|------|
| `src/config/pack_config.py` | `load_pack_by_id()` 함수 추가 |
| `src/gui/main_window.py` | `_activate_pack_for_job()`에서 `load_pack_by_id()` 사용 |

---

*v58.0.0 - 2026-02-06*
*v58.1.0 - 2026-02-06*
*v58.2.1 - 2026-02-06*
*v58.2.2 - 2026-02-06*
*v58.2.3 - 2026-02-06*
*v58.2.4 - 2026-02-06*
*v58.3.0 - 2026-02-06*
*v58.3.1 - 2026-02-06*
*v58.3.2 - 2026-02-06*
*v58.3.3 - 2026-02-07*

---

## v58.3.3 - MoviePy 완전 제거 + YouTube 볼륨 최적화

### 핵심 변경

**MoviePy 렌더링 코드 완전 제거!**
- **이유**: MoviePy는 CPU 기반이라 렌더링에 1시간+ 걸림
- **변경**: Remotion + FFmpeg (NVENC GPU)로 완전 전환
- **결과**: 렌더링 시간 1시간 → 2-3분

### 변경사항

#### 1. Remotion에서 전체 오디오 처리

```
❌ 기존 (잘못됨):
Remotion (자막만) → MoviePy (오디오 덮어쓰기) → FFmpeg concat

✅ 수정 (올바름):
Remotion (자막 + 이미지 + 오디오 + BGM) → FFmpeg concat
```

**수정 파일:**
- `remotion-poc/src/RadioDrama.tsx`: `fullAudioPath` prop 추가
- `src/modules_pro/remotion_assembler.py`: `set_full_audio()` 메서드 추가
- `src/modules_pro/media_factory.py`: MoviePy 오디오 덮어쓰기 코드 제거

#### 2. YouTube 권장 볼륨 적용

FFmpeg concat에서 `loudnorm` 필터로 볼륨 정규화:

```python
# video_assembler.py
"-af", "loudnorm=I=-14:TP=-1:LRA=11"  # YouTube 권장 -14 LUFS
```

**볼륨 기준:**
| 항목 | 값 |
|------|-----|
| Integrated Loudness | -14 LUFS |
| True Peak | -1 dB |
| Loudness Range | 11 |

#### 3. 트러블슈팅 문서 추가

`docs/TROUBLESHOOTING.md` 생성:
- MoviePy 사용 금지 원칙
- 렌더링 파이프라인 설명
- TTS 볼륨 문제 해결법
- 반복 이슈 기록

### 수정된 파일

| 파일 | 변경 |
|------|------|
| `remotion-poc/src/RadioDrama.tsx` | `fullAudioPath` prop, ttsVolume 기본값 1.0 |
| `src/modules_pro/remotion_assembler.py` | `set_full_audio()`, fullAudioPath 전달 |
| `src/modules_pro/media_factory.py` | MoviePy 오디오 코드 제거, 파일 경로 반환 |
| `src/modules_pro/video_assembler.py` | loudnorm 필터 추가 |
| `docs/TROUBLESHOOTING.md` | 신규 생성 |
| `CLAUDE.md` | TROUBLESHOOTING.md 참조 추가 |

