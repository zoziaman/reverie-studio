# Reverie Pack Specification v59

> 이 문서는 Reverie Studio v59의 **실제 코드 구현**에 기반한 팩 스펙입니다.
> 최종 업데이트: 2026-02-12
> 참조 코드: `src/config/pack_config.py` (v59.5.12)
> 참조 팩: horror_default, senior_touching, senior_makjang, senior_family_drama, senior_generational_drama

---

## 1. 팩이란?

**ReveriePack**은 Reverie Studio의 콘텐츠 생성 파이프라인에서 사용되는 **장르별 설정 파일**입니다.

### 역할
- AI 대본 생성(PD/Writer)의 지시사항 결정
- TTS 음성 캐릭터와 감정 배분 결정
- Stable Diffusion 이미지 스타일/모델 결정
- 배경음악(BGM), 효과음(SFX) 선택
- 영상 훅/썸네일/자막 스타일 결정
- 시나리오 소재 풀(tone, twist, place 등) 제공

### 파이프라인에서의 위치
```
[팩 로드] → [시나리오 생성] → [대본 작성] → [TTS 생성] → [이미지 생성] → [영상 조립] → [업로드]
    ↓              ↓               ↓             ↓              ↓             ↓
  pack_config  scenario_planner  gemini_script  tts_module   sd_generator  remotion_assembler
```

### 파일 형식
| 형식 | 확장자 | 용도 | 구조 |
|------|--------|------|------|
| JSON | `.json` | 개발/테스트/내부용 | 단일 JSON 파일 |
| RevPack | `.revpack` | 배포/주문제작/판매용 | 암호화 ZIP (Fernet + PBKDF2-SHA256) |

> `.revpack` 내부 구조: `manifest.json` + `settings.json` (각각 `.enc` 암호화 가능)
> JSON 팩은 `_load_pack_from_json()` 함수로, .revpack은 `load_pack()` 함수로 로드됩니다.

---

## 2. JSON 팩 전체 구조

```json
{
  "pack_id": "string",           // 필수: 고유 식별자
  "pack_name": "string",         // 필수: 표시 이름
  "version": "string",           // 필수: 버전 (예: "1.0.0")
  "author": "string",            // 필수: 제작자
  "description": "string",       // 필수: 설명
  "genre": "string",             // 필수: 장르 ("horror" | "senior")

  "tts": { ... },                // 필수: TTS 설정
  "bgm": { ... },                // 필수: BGM 설정
  "sfx": { ... },                // 필수: SFX 설정
  "sd": { ... },                 // 필수: SD 기본 설정
  "visual": { ... },             // 필수: 비주얼 캐릭터/스타일
  "prompts": { ... },            // 필수: PD/Writer 프롬프트
  "content": { ... },            // 필수: 콘텐츠 설정
  "video": { ... },              // 필수: 비디오 설정
  "hook_style": { ... },         // 필수: 훅 스타일
  "thumbnail": { ... },          // 필수: 썸네일 설정
  "scenario": { ... },           // 필수: 시나리오 풀
  "visual_storytelling": { ... }, // 필수: 비주얼 스토리텔링 (v59 기본)
  "scene_analyzer": { ... },     // 필수: 장면 분석기 설정 (v59 기본)

  "topic_templates": [ ... ],    // 선택: 주제 예시
  "tags": [ ... ],               // 선택: 태그
  "intro_scripts": [ ... ]       // 선택: 인트로 멘트 (미사용, 미래 기능용)
}
```

---

## 3. 필수 필드 상세 스펙

### 3.1 기본정보

| 필드 | 타입 | 필수 | 설명 | 예시 |
|------|------|------|------|------|
| `pack_id` | string | ✅ | 고유 식별자 (영문+언더스코어) | `"horror_default"` |
| `pack_name` | string | ✅ | 한글 표시 이름 | `"공포 채널"` |
| `version` | string | ✅ | 시맨틱 버전 | `"1.0.0"` |
| `author` | string | ✅ | 제작자 이름 | `"Reverie Studio"` |
| `description` | string | ✅ | 팩 설명 | `"공포/괴담 콘텐츠 채널"` |
| `genre` | string | ✅ | 장르 키 (`"horror"` 또는 `"senior"`) | `"horror"` |

> **genre 값의 의미**: 장르 분류 및 레거시 SD 모델 매핑에 사용됩니다.
> - `"horror"` → 공포/괴담/미스터리 계열
> - `"senior"` → 시니어/감동/막장/세대갈등 계열
> - ⚠️ **v59부터 SD 체크포인트는 `visual_storytelling.sd_model.checkpoint`에서 직접 지정합니다.**
>   `genre`는 분류 메타데이터로만 사용됩니다.

---

### 3.2 TTS (`tts`)

TTS(Text-to-Speech) 음성 설정입니다.

```json
{
  "tts": {
    "narrator": "narrator_female",
    "character_mapping": {
      "나레이션": "narrator_female",
      "할아버지": "grandpa",
      "할머니": "grandma",
      ...
    },
    "default_emotion": "calm",
    "allowed_emotions": ["scared", "angry", "sad", "happy", "calm", "whisper"],
    "emotion_weights": {
      "scared": 3,
      "calm": 5
    }
  }
}
```

#### 9종 Voice Type

| voice_type | 설명 | ElevenLabs 모델 | 감정 목록 |
|------------|------|-----------------|-----------|
| `narrator_male` | 남성 나레이터 | narrator_male | calm, fear |
| `narrator_female` | 여성 나레이터 | narrator_female | calm, sad, happy, angry, scared |
| `grandpa` | 할아버지 | grandpa | calm, sad, angry, happy, scared, whisper, worried, desperate |
| `grandma` | 할머니 | grandma | calm, sad, angry, happy, scared, whisper, worried, desperate |
| `man` | 청년 남성 | man | calm, sad, angry, happy, scared, whisper, worried, desperate |
| `woman` | 청년 여성 | woman | calm, sad, angry, happy, scared, whisper, worried, desperate |
| `middle_man` | 중년 남성 | middle_man | calm, sad, angry, happy, scared, whisper, worried, desperate |
| `middle_woman` | 중년 여성 | middle_woman | calm, sad, angry, happy, scared, whisper, worried, desperate |

> `young_man`, `young_woman`은 각각 `man`, `woman`의 alias입니다.
> 레퍼런스 음성 파일: `assets/models/reference_samples/{voice_type}/{emotion}.wav`

#### character_mapping 작성 가이드

한국어 캐릭터명을 voice_type에 매핑합니다. AI 대본에서 사용될 수 있는 **모든 호칭**을 등록해야 합니다.

**필수 매핑 (모든 팩 공통):**
```json
{
  "narrator": "narrator_*",
  "나레이션": "narrator_*",
  "내레이션": "narrator_*",
  "할아버지": "grandpa",
  "할머니": "grandma",
  "할배": "grandpa",
  "할매": "grandma",
  "남자": "man",
  "여자": "woman",
  "청년": "man",
  "아저씨": "middle_man",
  "아줌마": "middle_woman",
  "아버지": "middle_man",
  "어머니": "middle_woman",
  "아빠": "middle_man",
  "엄마": "middle_woman"
}
```

**장르별 추가 매핑 예시:**
- 공포: `"주인공": "woman"`, `"귀신": "woman"`
- 가족사: `"며느리": "middle_woman"`, `"시어머니": "grandma"`, `"사위": "middle_man"`

#### emotion_weights

감정별 가중치입니다. AI 대본 생성 시 감정 분배 비율에 영향을 줍니다.

```json
// 공포 팩
"emotion_weights": { "scared": 3, "angry": 1, "sad": 1, "calm": 5 }

// 감동 팩
"emotion_weights": { "sad": 4, "happy": 3, "calm": 5 }

// 막장 팩
"emotion_weights": { "angry": 4, "sad": 3, "desperate": 2, "calm": 3 }
```

---

### 3.3 BGM (`bgm`)

```json
{
  "bgm": {
    "folder": "horror"
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `folder` | string | BGM 폴더명 |

> **사용 가능한 folder 값**: `"horror"`, `"makjang"`, `"touching"`
> 실제 BGM 경로는 `assets/bgm/{folder}/` 하위의 MP3 파일들입니다.
> ⚠️ 코드에서 `bgm.folder`는 직접 참조되지 않습니다. BGM 선택은 GUI의 `mode` 파라미터와 `use_channel_bgm` 설정에 의해 결정됩니다. 이 필드는 메타데이터 역할입니다.

---

### 3.4 SFX (`sfx`)

```json
{
  "sfx": {
    "folder": "horror",
    "enabled": true,
    "category": "horror",
    "intensity": "high"
  }
}
```

| 필드 | 타입 | 설명 | 값 |
|------|------|------|----|
| `folder` | string | SFX 폴더명 | `"horror"`, `"makjang"`, `"touching"` |
| `enabled` | boolean | SFX 활성화 여부 | `true` / `false` |
| `category` | string | SFX 카테고리 | `"horror"`, `"emotional"` |
| `intensity` | string | SFX 강도 | `"low"`, `"medium"`, `"high"` |

---

### 3.5 SD (`sd`)

Stable Diffusion 기본 설정입니다. `visual_storytelling.sd_model`과 별도로 존재합니다.

```json
{
  "sd": {
    "positive": "masterpiece, best quality, ...",
    "negative": "(worst quality:1.4), ...",
    "style": "silhouette horror",
    "model": "horror",
    "cfg_scale": 7.0,
    "steps": 20,
    "image_style": "horror manga style, ..."
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `positive` | string | 기본 positive 프롬프트 |
| `negative` | string | 기본 negative 프롬프트 |
| `style` | string | 스타일 이름 (메타데이터) |
| `model` | string | SD 모델 키 (`"horror"` 또는 `"senior"`) |
| `cfg_scale` | float | CFG Scale (기본 6.0~7.0) |
| `steps` | int | 샘플링 스텝 수 (기본 20~28) |
| `image_style` | string | 이미지 스타일 설명 (메타데이터) |

> `sd.positive`와 `sd.negative`는 `prompts.sd_positive`가 비어있을 때 자동 교차 연결됩니다.
> **v59에서 실제 이미지 생성은 `visual_storytelling.sd_model`이 담당합니다.** `sd` 섹션은 레거시 호환 + 메타데이터 역할입니다.

---

### 3.6 Visual (`visual`)

비주얼 캐릭터 정의와 강제 스타일 설정입니다.

```json
{
  "visual": {
    "character_system_enabled": false,
    "characters": {
      "grandma": {
        "base": "...(외형 프롬프트)...",
        "style": "...(스타일 접미사)..."
      },
      "grandpa": { "base": "...", "style": "..." },
      "man": { "base": "...", "style": "..." },
      "woman": { "base": "...", "style": "..." },
      "middle_man": { "base": "...", "style": "..." },
      "middle_woman": { "base": "...", "style": "..." },
      "narrator": { "base": "...", "style": "..." },
      "_default": { "base": "...", "style": "..." }
    },
    "forced_style": {
      "force_positive": "...",
      "force_negative": "..."
    },
    "thumbnail_backgrounds": [ "...", "..." ],
    "safe_fallbacks": [ "...", "..." ],
    "safe_fallback_prompt": "..."
  }
}
```

#### characters

각 voice_type에 대응하는 비주얼 프롬프트입니다.

| 키 | 필수 | 설명 |
|----|------|------|
| `grandma` | ✅ | 할머니 외형 |
| `grandpa` | ✅ | 할아버지 외형 |
| `man` | ✅ | 청년 남성 외형 |
| `woman` | ✅ | 청년 여성 외형 |
| `middle_man` | ✅ | 중년 남성 외형 |
| `middle_woman` | ✅ | 중년 여성 외형 |
| `narrator` | ✅ | 나레이터 외형 |
| `_default` | ✅ | 매핑 안 된 캐릭터용 폴백 |

각 캐릭터 항목:
```json
{
  "base": "스타일 + 외형 + 의상 + 표정 + fully clothed",
  "style": "화풍 + 색조 + 분위기"
}
```

> **중요**: 노인 캐릭터(grandma/grandpa)에는 반드시 나이 강조 태그를 포함하세요:
> `"(elderly grandmother:1.4), (wrinkled face:1.3), (aged skin:1.2)"`
> 중년 캐릭터에도: `"(middle-aged man:1.3), (mature face:1.2)"`

#### forced_style

모든 이미지에 강제 적용되는 스타일 프롬프트입니다.

```json
{
  "force_positive": "monochrome manga, black and white ink drawing, ...",
  "force_negative": "colorful, bright colors, photorealistic, 3d render, ..."
}
```

> SceneAnalyzer가 생성한 프롬프트에 `force_positive`가 앞에 붙고, `force_negative`가 negative에 추가됩니다.

#### thumbnail_backgrounds

썸네일 배경 프롬프트 리스트입니다. 15~30개 권장.

```json
"thumbnail_backgrounds": [
  "abandoned hallway, flickering light, no people, cinematic",
  "rainy window with droplets, no people",
  ...
]
```

> 모든 배경에 `"no people"`를 포함하세요 (인물은 별도 합성).

#### safe_fallbacks

이미지 생성 실패 시 사용되는 폴백 프롬프트입니다. **8개 권장**.

```json
"safe_fallbacks": [
  "empty old room, dusty furniture, dim lamp light, cinematic atmosphere",
  ...
]
```

#### safe_fallback_prompt

최종 폴백용 단일 프롬프트입니다.

---

### 3.7 Prompts (`prompts`)

AI 대본 생성을 위한 PD/Writer 시스템 프롬프트입니다.

```json
{
  "prompts": {
    "pd_system": "당신은 OO 전문 PD입니다.\n...",
    "writer_system": "OO 전문 작가입니다.\n..."
  }
}
```

#### pd_system 작성 가이드

PD 프롬프트는 **스토리 구조와 캐릭터 배치**를 지시합니다.

필수 포함 요소:
1. **5막 스토리 구조** (도입 → 전개 → 갈등 → 클라이맥스 → 결말)
2. **캐릭터 배치 가이드** (어떤 세대/역할이 필수인지)
3. **장르별 핵심 포인트** (공포: 서서히 고조, 감동: 여운, 막장: 반전)
4. **금지사항** (유혈/폭력, 비현실적 요소 등)

#### writer_system 작성 가이드

Writer 프롬프트는 **문체, 대사 말투, 감정 태그 사용법**을 지시합니다.

필수 포함 요소:
1. **문장 스타일** (짧은 문장 vs 서술적 등)
2. **캐릭터별 말투 예시** (실제 대사 예문 포함)
3. **감정 태그 사용법** (`[angry]`, `[sad]` 등과 비율)
4. **SFX 사용 가이드** (`[SFX:door]`, `[SFX:impact]` 등)
5. **"1턴 = 1대사" 원칙**

---

### 3.8 Content (`content`)

콘텐츠 길이와 스타일 설정입니다.

```json
{
  "content": {
    "duration_minutes": 5,
    "min_turns": 80,
    "max_turns": 150,
    "image_style": "silhouette horror"
  }
}
```

| 필드 | 타입 | 설명 | 기본값 |
|------|------|------|--------|
| `duration_minutes` | int | 목표 영상 길이(분) | 5 |
| `min_turns` | int | 최소 턴 수 | 50~80 |
| `max_turns` | int | 최대 턴 수 | 100~150 |
| `image_style` | string | 이미지 스타일명 (메타데이터) | `""` |

---

### 3.9 Video (`video`)

비디오 렌더링 설정입니다.

```json
{
  "video": {
    "pause_duration": 0.4,
    "zoom_speed": 1.0
  }
}
```

| 필드 | 타입 | 설명 | 기본값 |
|------|------|------|--------|
| `pause_duration` | float | 장면 전환 시 일시정지(초) | 0.4~0.5 |
| `zoom_speed` | float | Ken Burns 줌 속도 배율 | 1.0 |

---

### 3.10 Hook Style (`hook_style`)

영상 도입부 훅 장면의 스타일입니다.

```json
{
  "hook_style": {
    "top_label": "【 괴 담 】",
    "top_color": "#8B0000",
    "main_color": "#FFFFFF",
    "bg_color": [0, 0, 0],
    "duration": 4.0
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `top_label` | string | 상단 라벨 텍스트 (예: `"【 괴 담 】"`) |
| `top_color` | string | 상단 라벨 색상 (HEX) |
| `main_color` | string | 메인 텍스트 색상 (HEX) |
| `bg_color` | [int, int, int] | 배경 RGB 색상 |
| `duration` | float | 훅 장면 표시 시간(초) |

---

### 3.11 Thumbnail (`thumbnail`)

썸네일 설정입니다.

```json
{
  "thumbnail": {
    "text_default": "실화",
    "style_guide": "공포/미스터리 느낌의 강렬한 제목. 예시: ..."
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `text_default` | string | 기본 텍스트 (예: `"실화"`, `"충격"`, `"감동실화"`) |
| `style_guide` | string | AI가 제목을 생성할 때 참고할 가이드 |

---

### 3.12 Scenario (`scenario`)

시나리오 생성기(scenario_planner.py)가 사용하는 소재 풀입니다.

```json
{
  "scenario": {
    "safe_templates": [ "..." ],
    "tone_pool": [ "..." ],
    "twist_pool": [ "..." ],
    "relationship_pool": [ "..." ],
    "place_pool": [ "..." ]
  }
}
```

#### 실제 사용되는 풀 (scenario_planner.py에서 읽음)

| 풀 | 용도 | 권장 개수 | 설명 |
|----|------|----------|------|
| `safe_templates` | ✅ 이미지 폴백 | 15~80개 | 인물 없는 배경 이미지 프롬프트 |
| `tone_pool` | ✅ 시나리오 톤 | 5개 | 스토리 구조/분위기 방향 |
| `twist_pool` | ✅ 반전 소재 | 5~7개 | 반전/클라이맥스 장치 |
| `relationship_pool` | ✅ 관계 | 5~6개 | 등장인물 관계 유형 |
| `place_pool` | ✅ 장소 | 5~7개 | 주요 배경 장소 |

#### 미사용 풀 (코드에 로드되지만 실제 미참조)

> 아래 필드들은 `PackScenario` dataclass에 정의되어 있지만, `scenario_planner.py`에서 하드코딩된 리스트를 사용하므로 실제로 읽히지 않습니다. 호환성을 위해 존재합니다.

| 풀 | 상태 |
|----|------|
| `arc_pool` | ❌ 미사용 (하드코딩) |
| `trigger_pool` | ❌ 미사용 (하드코딩) |
| `conflict_pool` | ❌ 미사용 (하드코딩) |
| `mystery_types` | ❌ 미사용 |
| `evidence_pool` | ❌ 미사용 |

---

### 3.13 Visual Storytelling (`visual_storytelling`)

v59부터 **모든 팩의 필수 기본 설정**입니다. 이미지 생성, 자막, 시각 효과를 통합 관리합니다.
새 팩을 만들 때 반드시 `"enabled": true`로 설정하세요.

```json
{
  "visual_storytelling": {
    "enabled": true,
    "version": "v59.3.2",

    "image_generation": {
      "target_images": 120,
      "min_images": 100,
      "max_images": 150,
      "reuse_threshold": 0.85,
      "quality_threshold": 0.7
    },

    "scene_analysis": {
      "use_gemini": true,
      "context_window": 5,
      "emotion_detection": true,
      "action_detection": true
    },

    "character_consistency": {
      "enabled": true,
      "similarity_threshold": 0.8,
      "expression_swap": true,
      "pose_library": true
    },

    "sd_model": { ... },
    "subtitle_style": { ... },
    "visual_effects": { ... }
  }
}
```

> ⚠️ **`enabled`는 반드시 `true`로 설정하세요.** `false`이면 레거시 모드로 폴백되어 v59 기능이 비활성화됩니다.

#### sd_model

실제 Stable Diffusion 체크포인트 및 생성 파라미터입니다.

```json
{
  "sd_model": {
    "checkpoint": "revAnimated_v2Rebirth.safetensors",
    "vae": "",
    "sampler": "DPM++ 2M Karras",
    "scheduler": "Normal",
    "steps": 28,
    "cfg_scale": 6.0,
    "width": 768,
    "height": 432,
    "clip_skip": 2,
    "positive_base": "masterpiece, best quality, ...",
    "negative_base": "worst quality, low quality, ...",
    "lora_models": []
  }
}
```

| 필드 | 타입 | 설명 | 기본값 |
|------|------|------|--------|
| `checkpoint` | string | 체크포인트 파일명 | (필수) |
| `vae` | string | VAE 파일명 (빈 문자열 = 기본) | `""` |
| `sampler` | string | 샘플러 | `"DPM++ 2M Karras"` |
| `scheduler` | string | 스케줄러 | `"Normal"` |
| `steps` | int | 샘플링 스텝 | 20~28 |
| `cfg_scale` | float | CFG Scale | 6.0~7.0 |
| `width` | int | 이미지 너비 | 768 |
| `height` | int | 이미지 높이 | 432 |
| `clip_skip` | int | CLIP Skip | 2 |
| `positive_base` | string | 모든 이미지에 공통 적용되는 positive | `""` |
| `negative_base` | string | 모든 이미지에 공통 적용되는 negative | `""` |
| `lora_models` | array | LoRA 모델 목록 | `[]` |

> **해상도**: SD 1.5 기준 768×432 (16:9) 권장. 총 픽셀 수가 ~330K 이내여야 품질 유지.
> **checkpoint 매핑**:
> - 공포: `dreamshaper_8.safetensors`
> - 시니어: `revAnimated_v2Rebirth.safetensors`

**LoRA 설정 예시:**
```json
"lora_models": [
  {
    "name": "korean_vintage_manhwa",
    "weight": 0.7,
    "trigger": "d5i9a6le878c73ca2t3g"
  }
]
```

#### subtitle_style

자막 스타일 설정입니다.

```json
{
  "subtitle_style": {
    "font_family": "NanumSquareRoundEB",
    "font_size": 42,
    "position": "bottom",
    "background_opacity": 0.7,
    "text_color": "#FFFFFF",
    "speaker_colors": {
      "나레이션": "#CCCCCC",
      "narrator": "#CCCCCC",
      "할머니": "#D4A574",
      "grandma": "#D4A574"
    }
  }
}
```

> `speaker_colors`는 한국어명과 영문 voice_type 양쪽 모두 등록하세요.

#### visual_effects

시각 효과 설정입니다.

```json
{
  "visual_effects": {
    "vignette": { "enabled": true, "intensity": 0.4 },
    "color_filter": { "type": "horror", "saturation": 0.7, "contrast": 1.1 },
    "film_grain": { "enabled": true, "intensity": 0.15 },
    "transitions": { "default": "crossfade", "duration": 0.5 }
  }
}
```

| 효과 | 필드 | 설명 | 공포 예시 | 감동 예시 | 막장 예시 |
|------|------|------|----------|----------|----------|
| vignette | intensity | 비네팅 강도 (0~1) | 0.4 | 0.2 | 0.3 |
| color_filter | type | 색상 필터 종류 | `"horror"` | `"warm"` | `"drama"` |
| color_filter | saturation | 채도 (0~1) | 0.7 | 0.9 | 0.85 |
| color_filter | contrast | 대비 (0.5~1.5) | 1.1 | 1.0 | 1.05 |
| film_grain | enabled | 필름 그레인 | true | false | true (약) |
| film_grain | intensity | 그레인 강도 | 0.15 | 0.0 | 0.1 |
| transitions | default | 전환 효과 | crossfade | crossfade | crossfade |
| transitions | duration | 전환 시간(초) | 0.5 | 0.6 | 0.5 |

---

### 3.14 Scene Analyzer (`scene_analyzer`)

SceneAnalyzer(Gemini)가 대사를 이미지 프롬프트로 변환할 때 사용하는 아트 스타일 설정입니다.

```json
{
  "scene_analyzer": {
    "art_style_prefix": "monochrome manga, black and white ink drawing,",
    "art_style_description": "같은 만화가의 빈티지 한국 공포 만화",
    "texture_keywords": "clean lineart, high contrast, ink strokes, ...",
    "forbidden_styles": "colorful, 3d render, photorealistic, ...",
    "good_examples": [
      "monochrome manga, ..., solo young woman looking terrified, ..., medium shot",
      "monochrome manga, ..., ghostly figure standing at end of corridor, ..., wide shot"
    ]
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `art_style_prefix` | string | 모든 프롬프트 앞에 붙는 스타일 접두사 |
| `art_style_description` | string | Gemini에게 전달할 스타일 설명 (한국어 OK) |
| `texture_keywords` | string | 텍스처 관련 키워드 |
| `forbidden_styles` | string | 금지 스타일 (Gemini가 피해야 할 것) |
| `good_examples` | array | 좋은 프롬프트 예시 4개 이상 |

> `good_examples`는 Gemini의 few-shot learning에 사용됩니다. 4개 이상 제공하세요.
> 각 예시에 `"solo"` 또는 `"no people"`를 포함하여 다중 인물 생성을 방지하세요.
> 반드시 카메라 앵글(`medium shot`, `close-up`, `wide shot`, `bust shot`)을 포함하세요.

---

## 4. 선택 필드

### 4.1 topic_templates

시나리오 생성 시 참고용 주제 예시입니다.

```json
"topic_templates": [
  "폐가에서 발견된 일기장의 비밀",
  "매일 밤 3시에 울리는 초인종"
]
```

### 4.2 tags

팩 검색/분류용 태그입니다.

```json
"tags": ["공포", "괴담", "무서운이야기", "호러", "귀신"]
```

### 4.3 intro_scripts

인트로 멘트 텍스트입니다.

```json
"intro_scripts": [
  "오늘도 소름 돋는 이야기를 들려드리겠습니다.",
  "밤이 깊어갑니다. 이야기를 시작하죠."
]
```

> ⚠️ **미사용**: 현재 코드에서 getter는 있지만 호출하는 곳이 없습니다. 미래 기능용으로 유지합니다.

---

## 5. 장르별 팩 만들기 가이드

### 5.1 Horror 팩

**아트 스타일**: 흑백 만화풍, 모노크롬, 잉크 드로잉
**체크포인트**: `dreamshaper_8.safetensors`
**LoRA**: `korean_vintage_manhwa` (w=0.7), `horror_manga` (w=0.5)
**감정 분배**: calm 50%, scared 30%, 나머지 20%
**나레이터**: `narrator_male` (차분한 남성)
**visual_effects**: 강한 비네팅(0.4), horror 필터, 필름 그레인 ON

```
핵심 포인트:
- force_positive에 "monochrome manga, black and white" 필수
- force_negative에 "colorful, bright colors" 필수
- safe_templates: 버려진 건물, 안개, 어둠, 인적 없는 장소
- 캐릭터 "ghost" 추가 가능
```

### 5.2 Senior 감동 팩

**아트 스타일**: 따뜻한 수채화, 파스텔 톤
**체크포인트**: `revAnimated_v2Rebirth.safetensors`
**LoRA**: 없음
**감정 분배**: calm 50%, sad 30%, happy 20%
**나레이터**: `narrator_female` (따뜻한 여성)
**visual_effects**: 약한 비네팅(0.2), warm 필터, 필름 그레인 OFF

```
핵심 포인트:
- force_positive에 "warm watercolor illustration, soft pastel colors" 필수
- force_negative에 "horror, dark, scary" 필수
- safe_templates: 빈 카페, 비오는 창가, 따뜻한 조명
- 할머니/할아버지 캐릭터에 나이 강조 태그 중요
```

### 5.3 Senior 막장 팩

**아트 스타일**: 극적 웹툰 스타일 또는 유화풍
**체크포인트**: `revAnimated_v2Rebirth.safetensors`
**LoRA**: 없음
**감정 분배**: angry 30%, sad 25%, desperate 15%, calm 20%
**나레이터**: `narrator_female`
**visual_effects**: 중간 비네팅(0.3), drama 필터, 약한 필름 그레인

```
핵심 포인트:
- 자극적이지만 유혈/폭력은 금지
- 반전 구조가 핵심: twist_pool 충실하게
- 가족 관계 캐릭터 매핑 세밀하게 (며느리, 시어머니 등)
- thumbnail: 충격/반전 유발 키워드
```

### 5.4 Senior 세대갈등 팩

**아트 스타일**: 따뜻한 회화풍, 자연 색감
**체크포인트**: `revAnimated_v2Rebirth.safetensors`
**LoRA**: 없음
**감정 분배**: calm 30%, sad 25%, happy 15%, angry 12%, worried 10%
**나레이터**: `narrator_female`
**visual_effects**: 약한 비네팅(0.2), warm 필터, 필름 그레인 OFF

```
핵심 포인트:
- 어느 세대도 '악인'이 아님 — 다를 뿐
- thumbnail_backgrounds: 전통+현대의 대비 소재
- 화해는 열린 결말 구조
- 3세대 가치관 차이를 자연스럽게
```

---

## 6. 프로덕션 체크리스트

새 팩을 만든 후, 프로덕션에 투입하기 전 아래를 확인하세요.

### 6.1 JSON 문법 검증

```bash
python -c "import json; json.load(open('assets/packs/새팩.json', encoding='utf-8')); print('OK')"
```

### 6.2 pack_config 로드 테스트

```python
cd <repo-root>
python -c "
import sys
sys.path.insert(0, 'src')
from config.pack_config import _load_pack_from_json
from pathlib import Path
result = _load_pack_from_json(Path('assets/packs/새팩.json'))
print(f'Load result: {result}')
"
```

### 6.3 필수 필드 체크리스트

```
□ pack_id — 고유 식별자 (다른 팩과 중복 없음)
□ genre — "horror" 또는 "senior"
□ tts.narrator — 유효한 voice_type
□ tts.character_mapping — 기본 매핑 모두 포함
□ tts.allowed_emotions — voice_metadata.json에 존재하는 감정만
□ visual.characters — 9종 voice_type 모두 + _default
□ visual.forced_style — force_positive, force_negative 모두
□ visual.safe_fallbacks — 8개 이상
□ visual.thumbnail_backgrounds — 15개 이상
□ prompts.pd_system — 5막 구조, 캐릭터 배치, 금지사항 포함
□ prompts.writer_system — 말투 예시, 감정 태그 비율, SFX 가이드 포함
□ visual_storytelling.enabled — 반드시 true (v59 기본)
□ visual_storytelling.sd_model.checkpoint — 유효한 체크포인트 파일명
□ visual_storytelling.sd_model.positive_base — 비어있지 않음
□ visual_storytelling.sd_model.negative_base — 비어있지 않음
□ visual_storytelling.subtitle_style.speaker_colors — 한국어+영문 양쪽
□ scene_analyzer.good_examples — 4개 이상, 카메라 앵글 포함
□ scenario.safe_templates — 15개 이상
□ scenario.tone_pool — 5개
□ scenario.twist_pool — 5개 이상
□ scenario.relationship_pool — 5개 이상
□ scenario.place_pool — 5개 이상
```

### 6.4 금지 키워드 확인

`negative` 프롬프트에 아래가 반드시 포함되어야 합니다:
```
nsfw, nude, naked, revealing clothes
```

`visual.characters`의 모든 `base` 프롬프트에 반드시 포함:
```
fully clothed
```

### 6.5 기존 팩과 구조 비교

```bash
# horror_default와 키 구조 비교
python -c "
import json
base = json.load(open('assets/packs/horror_default.json', encoding='utf-8'))
new = json.load(open('assets/packs/새팩.json', encoding='utf-8'))
missing = set(base.keys()) - set(new.keys())
extra = set(new.keys()) - set(base.keys())
print(f'Missing keys: {missing}')
print(f'Extra keys: {extra}')
"
```

---

## 7. 부록

### 7.1 미사용 필드 목록

아래 필드들은 `PackScenario` dataclass에 정의되어 있거나 JSON에 존재하지만, 현재 코드에서 실제로 참조되지 않습니다.

| 필드 | 위치 | 상태 | 비고 |
|------|------|------|------|
| `intro_scripts` | 루트 | 미사용 | getter 존재, 호출 없음 |
| `scenario.arc_pool` | scenario | 미사용 | 하드코딩 사용 |
| `scenario.trigger_pool` | scenario | 미사용 | 하드코딩 사용 |
| `scenario.conflict_pool` | scenario | 미사용 | 하드코딩 사용 |
| `scenario.mystery_types` | scenario | 미사용 | 미구현 |
| `scenario.evidence_pool` | scenario | 미사용 | 미구현 |
| `bgm.folder` | bgm | 간접 사용 | GUI mode로 결정됨 |

### 7.2 voice_metadata.json 감정 목록

각 voice_type이 지원하는 감정 목록입니다. `allowed_emotions`에는 이 목록의 감정만 사용하세요.

| voice_type | 지원 감정 |
|------------|-----------|
| narrator_male | calm, fear |
| narrator_female | calm, sad, happy, angry, scared |
| grandpa | calm, sad, angry, happy, scared, whisper, worried, desperate |
| grandma | calm, sad, angry, happy, scared, worried, whisper, desperate |
| man | calm, sad, angry, happy, scared, worried, whisper, desperate |
| woman | calm, sad, angry, happy, scared, worried, whisper, desperate |
| middle_man | calm, sad, angry, happy, scared, worried, whisper, desperate |
| middle_woman | calm, sad, angry, happy, scared, worried, whisper, desperate |

### 7.3 .revpack 파일 구조

`.revpack`은 ZIP 형식의 암호화된 팩 파일입니다.

```
{name}.revpack (ZIP)
├── manifest.json       # 또는 manifest.json.enc (암호화)
└── settings.json       # 또는 settings.json.enc (암호화)
```

- 암호화: Fernet (AES-128-CBC) + PBKDF2-SHA256
- 암호화 키: `pack_config.py`와 `pack_creator_full.py`에서 동일한 salt/password 사용
- `manifest.json` = 기본정보 (pack_id, pack_name, version, author, genre 등)
- `settings.json` = 나머지 모든 설정 (tts, visual, prompts, scenario 등)

### 7.4 SD 모델 체크포인트 목록

현재 사용 중인 체크포인트:

| 체크포인트 | 장르 | 용도 |
|-----------|------|------|
| `dreamshaper_8.safetensors` | horror | 흑백 만화풍, 공포 |
| `revAnimated_v2Rebirth.safetensors` | senior | 수채화/유화/회화풍, 시니어 |

> 새 체크포인트를 추가하려면 `sd-webui/models/Stable-diffusion/` 폴더에 배치하고 `visual_storytelling.sd_model.checkpoint`에 파일명을 지정하세요.
