# Reverie Pack 생성 완전 가이드 (v60.0.0)

> 이 문서는 새로운 .revpack을 만들 때 참조하는 **완전 양식**입니다.
> 이 문서만 보면 코드 수정 없이 새 장르의 팩을 만들 수 있습니다.
>
> **최종 업데이트**: 2026-02-15
> **적용 버전**: v60.0.0+

---

## 목차

1. [핵심 원칙](#1-핵심-원칙)
2. [.revpack 구조](#2-revpack-구조)
3. [manifest.json](#3-manifestjson)
4. [settings.json — 전체 스키마](#4-settingsjson--전체-스키마)
5. [topics.json — 시나리오 풀](#5-topicsjson--시나리오-풀)
6. [prompts/ — 프롬프트 파일 (20개)](#6-prompts--프롬프트-파일-20개)
7. [팩 생성 체크리스트](#7-팩-생성-체크리스트)
8. [pack_creator_full.py 자동 생성](#8-pack_creator_fullpy-자동-생성)
9. [기존 팩 참조표](#9-기존-팩-참조표)
10. [트러블슈팅](#10-트러블슈팅)

---

## 1. 핵심 원칙

```
레베리 시스템 = 팩(.revpack)을 실행하는 범용 클라이언트

✅ 새 장르 추가 = 새 팩 생성 (코드 수정 0줄)
❌ 코드에 장르별 if/else 금지
❌ 프롬프트 하드코딩 금지
❌ 하드코딩 풀 금지 (tone_pool, twist_pool 등)
```

| 팩에 넣어야 함 | 코드에 넣으면 안 되는 이유 |
|---|---|
| 프롬프트 템플릿 텍스트 | 장르마다 다르므로 팩이 결정 |
| 톤/분위기/키워드 풀 | PackScenario에 이미 구조 있음 |
| SFX 카테고리 가이드 + 키워드 매핑 | 장르별 SFX 태그가 다름 |
| 이미지 아트 스타일 문자열 | 공포=모노크롬, 시니어=수채화 등 |
| 비상 템플릿 대본 시퀀스 | 장르별 대사/분위기가 다름 |
| 감정 정책 (emotion_weights) | 공포=scared 우선, 감동=sad 우선 |
| 글쓰기 규칙 (craft_rules) | 공포=카운트다운 기법, 감동=감정 곡선 등 |
| 페이싱 가이드 (pacing) | 파트별 긴장감 구조가 장르마다 다름 |

---

## 2. .revpack 구조

`.revpack` = ZIP 파일 (확장자만 변경)

```
my_new_pack.revpack (ZIP)
├── manifest.json               ← 기본 메타데이터
├── settings.json               ← 상세 설정 (TTS, Visual, SFX, Atmosphere, Emergency, Hook 등)
├── topics.json                 ← 시나리오 풀, 템플릿, 태그
└── prompts/
    ├── pd_system.txt               ← PD 시스템 프롬프트
    ├── writer_system.txt           ← 작가 시스템 프롬프트
    ├── sd_prompts.json             ← SD positive/negative 프롬프트
    ├── topic_generation.txt        ← [v60] 토픽 생성 프롬프트
    ├── topic_enhanced.txt          ← [v60] 강화 모드 토픽 프롬프트
    ├── hook_generation.txt         ← [v60] 오프닝 훅 프롬프트
    ├── hook_enhanced.txt           ← [v60] 강화 훅 프롬프트
    ├── metadata_generation.txt     ← [v60] YouTube 메타데이터 생성
    ├── thumbnail_style.txt         ← [v60] 썸네일 타이틀 스타일
    ├── story_bible.txt             ← [v60] 스토리 바이블 생성
    ├── story_bible_improve.txt     ← [v60] 바이블 개선
    ├── story_summarize.txt         ← [v60] 파트 간 요약
    ├── structural_outline.txt      ← [v60] 구조적 아웃라인
    ├── craft_rules.txt             ← [v60] 글쓰기 규칙
    ├── pacing_part1.txt            ← [v60] 파트1 페이싱 가이드
    ├── pacing_part2.txt            ← [v60] 파트2 페이싱 가이드
    ├── pacing_part3.txt            ← [v60] 파트3 페이싱 가이드
    ├── image_style.txt             ← [v60] SD 아트 스타일 문자열
    └── image_llm_prompt.txt        ← [v60] LLM→SD 프롬프트 생성 규칙
```

> 암호화 지원: 각 파일에 `.enc` 확장자 추가 시 Fernet 복호화 적용

---

## 3. manifest.json

```json
{
  "package_id": "comedy_default",
  "package_name": "코미디 기본팩",
  "version": "60.0.0",
  "author": "Reverie Studio",
  "description": "일상 코미디 콘텐츠용 팩. 밝은 분위기, 개그 포인트 강조.",
  "created_at": "2026-02-15",

  "reverie_version_min": "60",
  "reverie_version_max": null,

  "license": {
    "type": "premium",
    "key_required": true,
    "expires_at": null
  },

  "category": "comedy",
  "genre": "comedy",
  "tags": ["comedy", "daily", "funny", "korean"],
  "thumbnail": "thumbnail.png"
}
```

### 필드 설명

| 필드 | 필수 | 설명 |
|------|------|------|
| `package_id` | ✅ | 고유 ID (영문_snake_case, 예: `comedy_default`) |
| `package_name` | ✅ | 표시 이름 (한국어 가능) |
| `version` | ✅ | 팩 버전 (레베리 버전과 일치 권장) |
| `author` | ✅ | 제작자 |
| `description` | ✅ | 팩 설명 (1~2문장) |
| `category` | ✅ | 카테고리 (`horror`, `senior`, `comedy`, `romance` 등) |
| `genre` | ✅ | 장르 (category와 동일하거나 하위 장르) |
| `license.type` | ✅ | `free` / `premium` |
| `license.key_required` | ✅ | 라이센스 키 필요 여부 |

---

## 4. settings.json — 전체 스키마

```json
{
  "pack_info": {
    "name": "Comedy Default Pack",
    "version": "v60.0.0",
    "description": "일상 코미디 영상 생성용 기본 팩",
    "author": "Reverie Studio",
    "created": "2026-02-15"
  },

  "requirements": {
    "sd_model": {
      "name": "DreamShaper 8",
      "filename": "dreamshaper_8.safetensors",
      "download_url": "https://civitai.com/models/4384/dreamshaper",
      "size_gb": 2.0
    },
    "vram_min_gb": 6,
    "vram_recommended_gb": 8
  },

  "style": {
    "image_style": "colorful cartoon illustration, cheerful atmosphere, bright lighting",
    "model": "comedy"
  },

  "tts": {
    "narrator": "narrator_male",
    "character_mapping": {
      "narrator": "narrator_male",
      "나레이션": "narrator_male",
      "남자": "man",
      "여자": "woman",
      "주인공": "man"
    },
    "default_emotion": "happy",
    "allowed_emotions": ["happy", "angry", "sad", "surprised", "calm"],
    "emotion_weights": {
      "happy": 5,
      "angry": 2,
      "sad": 1,
      "surprised": 3,
      "calm": 2
    }
  },

  "characters": {
    "protagonist": {
      "base": "cheerful young Korean man, casual clothing, expressive face",
      "style": "cartoon illustration, bright colors, clean lineart"
    },
    "friend": {
      "base": "funny sidekick character, round face, exaggerated expressions",
      "style": "cartoon illustration, comedic proportions"
    },
    "_default": {
      "base": "generic cartoon character, simple design",
      "style": "cartoon illustration, bright colors"
    }
  },

  "content": {
    "duration_minutes": 5,
    "min_turns": 60,
    "max_turns": 120
  },

  "assets": {
    "bgm_folder": "comedy",
    "sfx_folder": "comedy",
    "sfx_enabled": true,
    "sfx_category": "comedy",
    "sfx_intensity": "high",
    "use_channel_bgm": true,
    "use_channel_sfx": true,
    "use_channel_tts": true
  },

  "visual": {
    "character_system_enabled": false,
    "forced_style": {
      "force_positive": "colorful cartoon, bright illustration, clean lineart, cheerful mood",
      "force_negative": "dark, horror, monochrome, realistic, nsfw, blurry, low quality"
    },
    "thumbnail_backgrounds": [
      "bright cafe interior, colorful decor, sunny window, no people",
      "comic book style explosion effect, action lines, bright yellow background"
    ],
    "safe_fallbacks": [
      "bright empty room, colorful furniture, cheerful atmosphere, no people",
      "sunny park bench, green trees, blue sky, peaceful scene, no people"
    ],
    "safe_fallback_prompt": "bright colorful illustration, empty cheerful scene, cartoon style, no people"
  },

  "sfx": {
    "category_guide": "This is a COMEDY video. Available SFX tags: laugh (audience laughter), bonk (comedic hit), whoosh (fast movement), spring (bouncy effect), fail (failure horn), applause. Place 2-4 effects per minute at funny moments.",
    "keyword_map": {
      "웃": "laugh",
      "ㅋㅋ": "laugh",
      "때리": "bonk",
      "맞": "bonk",
      "빠르": "whoosh",
      "달리": "whoosh",
      "실패": "fail",
      "넘어": "fail",
      "놀라": "spring",
      "깜짝": "spring",
      "박수": "applause",
      "짝짝": "applause"
    }
  },

  "atmosphere": {
    "mood_map": {
      "funny": "bright saturated colors, exaggerated expressions, action lines",
      "awkward": "slightly desaturated, frozen moment, sweat drop",
      "heartwarming": "soft warm glow, golden light, gentle atmosphere"
    },
    "keywords": {
      "funny": ["웃기", "개그", "빵", "ㅋㅋ"],
      "awkward": ["어색", "민망", "당황", "멘붕"],
      "heartwarming": ["감동", "따뜻", "우정", "사랑"]
    }
  },

  "emergency": {
    "template_sequence": [
      ["나레이션", "narrator", "이 이야기는 어느 평범한 일상에서 시작됩니다.", "calm"],
      ["나레이션", "narrator", "주인공 민수는 오늘도 지각이었습니다.", "happy"],
      ["민수", "man", "아 또 늦었다!", "surprised"],
      ["나레이션", "narrator", "허겁지겁 뛰어가다 미끄러졌습니다.", "happy"],
      ["민수", "man", "아야!", "angry"],
      ["나레이션", "narrator", "하필 그때 짝사랑하는 여자가 지나갔습니다.", "calm"],
      ["여자", "woman", "괜찮아요?", "worried"],
      ["민수", "man", "아 네 괜찮습니다 하하", "happy"],
      ["나레이션", "narrator", "괜찮지 않았습니다.", "happy"]
    ]
  },

  "video": {
    "pause_duration": 0.3,
    "zoom_speed": 1.0
  },

  "hook_style": {
    "top_label": "【 코미디 】",
    "top_color": "#FFD700",
    "main_color": "#FFFFFF",
    "bg_color": [30, 30, 80],
    "duration": 4.0
  },

  "thumbnail": {
    "text_default": "실화",
    "style_guide": "밝고 재미있는 제목. 예시: \"이건 실화입니다\", \"진짜 이런 일이?\". 짧고 임팩트 있게 (2~4어절)."
  },

  "sd": {
    "positive": "masterpiece, best quality, bright colors, cheerful, cartoon style, clean lineart, professional illustration",
    "negative": "(worst quality:1.4), (low quality:1.4), dark, horror, monochrome, nsfw, text, watermark, blurry",
    "cfg_scale": 7.0,
    "steps": 15
  },

  "visual_storytelling": {
    "enabled": true,
    "version": "v60.0.0",
    "characters": {
      "protagonist": {
        "base": "cheerful young Korean man, casual clothing",
        "style": "cartoon illustration, bright colors"
      },
      "_default": {
        "base": "generic cartoon character",
        "style": "cartoon illustration"
      }
    },
    "image_generation": {
      "target_images": 120,
      "min_images": 100,
      "max_images": 150
    }
  },

  "scene_analyzer": {
    "art_style_prefix": "colorful cartoon illustration, bright cheerful colors, clean lineart, comic style",
    "art_style_negative": "dark, horror, monochrome, realistic photograph, nsfw",
    "camera_guide": {
      "dialogue": "medium shot, eye level, clean background",
      "comedy_moment": "extreme close-up, exaggerated expression, action lines",
      "scene_setting": "wide establishing shot, bright environment",
      "reaction": "close-up, surprised expression, sweat drop effect"
    },
    "good_examples": [
      {"prompt": "medium shot, two friends talking at bright cafe table, coffee cups, warm sunlight through window, colorful cartoon illustration", "why": "Clear character interaction with appropriate setting"},
      {"prompt": "extreme close-up, shocked face with sweat drop, action lines background, comedic expression, cartoon style", "why": "Comedy timing emphasized through camera angle"}
    ]
  }
}
```

### settings.json 필드 상세 설명

#### 4.1 `tts` 섹션
| 필드 | 타입 | 설명 |
|------|------|------|
| `narrator` | string | 기본 나레이터 음성 (`narrator_male` / `narrator_female`) |
| `character_mapping` | dict | 한국어 역할명 → 음성 모델 ID 매핑 |
| `default_emotion` | string | 기본 감정 (`calm`, `happy`, `sad` 등) |
| `allowed_emotions` | list | 허용 감정 목록 (이 외 감정은 default로 대체) |
| `emotion_weights` | dict | 감정별 가중치 (높을수록 자주 등장) |

#### 4.2 `sfx` 섹션 (v60)
| 필드 | 타입 | 설명 |
|------|------|------|
| `category_guide` | string | AI에게 제공하는 SFX 사용 가이드 (영어, 태그 목록 포함) |
| `keyword_map` | dict | 한국어 키워드 → SFX 태그 매핑 (대본 텍스트 기반 자동 태깅) |

> **SFX 태그 규칙**: `keyword_map`의 값은 `assets/sfx/{sfx_folder}/` 아래 실제 파일명과 매칭되어야 합니다.

#### 4.3 `atmosphere` 섹션 (v60)
| 필드 | 타입 | 설명 |
|------|------|------|
| `mood_map` | dict | 분위기 키 → SD 라이팅/분위기 키워드 (영어) |
| `keywords` | dict | 분위기 키 → 한국어 키워드 리스트 (대본 텍스트 감지용) |

> **동작 방식**: 대본 텍스트에서 한국어 키워드를 감지 → 해당 분위기의 SD 라이팅 키워드를 이미지 프롬프트에 추가

#### 4.4 `emergency` 섹션 (v60)
| 필드 | 타입 | 설명 |
|------|------|------|
| `template_sequence` | list[list] | 비상 대본 시퀀스 `[[역할, 캐릭터ID, 대사, 감정], ...]` |

> **용도**: Gemini API 실패 시 폴백 대본으로 사용. 최소 30턴, 최대 50턴 권장.
> **형식**: `["나레이션", "narrator", "대사 텍스트", "calm"]`
> - 역할: 한국어 표시명 (나레이션, 민수, 수진 등)
> - 캐릭터ID: TTS character_mapping의 키 (narrator, man, woman 등)
> - 대사: 한국어 텍스트
> - 감정: allowed_emotions 중 하나

#### 4.5 `hook_style` 섹션
| 필드 | 타입 | 설명 |
|------|------|------|
| `top_label` | string | 상단 장르 라벨 (예: `【 괴 담 】`, `【 코미디 】`) |
| `top_color` | string | 라벨 색상 (hex) |
| `main_color` | string | 제목 텍스트 색상 (hex) |
| `bg_color` | list[int] | 배경색 RGB (예: `[0, 0, 0]` = 검정) |
| `duration` | float | 훅 화면 표시 시간 (초) |

#### 4.6 `scene_analyzer` 섹션
| 필드 | 타입 | 설명 |
|------|------|------|
| `art_style_prefix` | string | 모든 SD 프롬프트 앞에 붙는 아트 스타일 (영어) |
| `art_style_negative` | string | 네거티브에 추가할 스타일 (영어) |
| `camera_guide` | dict | 상황별 카메라 워크 가이드 (AI 참조용) |
| `good_examples` | list[dict] | 좋은 프롬프트 예시 (AI 학습용, prompt + why) |

---

## 5. topics.json — 시나리오 풀

```json
{
  "templates": [
    "평범한 직장인의 출근길에 벌어진 황당한 사건",
    "소개팅에서 생긴 믿을 수 없는 일",
    "배달 음식 주문에서 시작된 소동"
  ],
  "tags": ["일상", "코미디", "개그", "반전"],

  "scenario": {
    "tone_pool": ["황당", "개그", "훈훈개그", "블랙코미디", "슬랩스틱"],
    "relationship_pool": ["친구", "직장동료", "연인", "가족", "이웃"],
    "place_pool": ["회사", "카페", "편의점", "공원", "지하철"],
    "arc_pool": ["오해에서 시작된 소동", "연쇄 실수", "예상 밖 반전"],
    "trigger_pool": ["실수", "오해", "우연", "착각", "고집"],
    "twist_pool": ["알고보니 자기 잘못", "상대방이 더 황당", "모두가 공범"],
    "conflict_pool": [],
    "mystery_types": [],
    "evidence_pool": []
  }
}
```

### 시나리오 풀 필드 설명

| 필드 | 용도 | 필수 |
|------|------|------|
| `templates` | 주제 생성 시 샘플로 제공 (최소 3개) | ✅ |
| `tags` | 주제 필터링/분류용 태그 | ✅ |
| `tone_pool` | 이야기 톤/분위기 (랜덤 선택) | ✅ |
| `relationship_pool` | 등장인물 관계 (랜덤 선택) | ✅ |
| `place_pool` | 배경 장소 (랜덤 선택) | ✅ |
| `arc_pool` | 이야기 전개 패턴 | 선택 |
| `trigger_pool` | 사건 촉발 요인 | 선택 |
| `twist_pool` | 반전 유형 | 선택 |
| `conflict_pool` | 갈등 유형 (막장용) | 선택 |
| `mystery_types` | 미스터리 유형 (미스터리용) | 선택 |
| `evidence_pool` | 단서 유형 (미스터리용) | 선택 |

> **규칙**: 비어있는 풀은 빈 리스트 `[]`로 설정. 코드는 빈 풀을 자동 건너뜁니다.

---

## 6. prompts/ — 프롬프트 파일 (20개)

### 6.1 기존 프롬프트 (4개)

| 파일명 | 용도 | 형식 |
|--------|------|------|
| `pd_system.txt` | PD(프로듀서) 시스템 프롬프트 | 텍스트 |
| `writer_system.txt` | 작가 시스템 프롬프트 | 텍스트 |
| `sd_prompts.json` | SD positive/negative | JSON (`{"positive":"...", "negative":"..."}`) |

### 6.2 v60 신규 프롬프트 (16개)

| 파일명 | 용도 | 파이프라인 단계 | 설명 |
|--------|------|----------------|------|
| `topic_generation.txt` | 토픽 생성 | Step 1 | Gemini에게 주제 1줄 생성 요청 시 시스템 프롬프트 |
| `topic_enhanced.txt` | 강화 토픽 | Step 1 (Enhanced) | 강화 모드에서 더 창의적인 토픽 생성 |
| `hook_generation.txt` | 훅 생성 | Step 2 | 영상 첫 4초 오프닝 훅 텍스트 생성 |
| `hook_enhanced.txt` | 강화 훅 | Step 2 (Enhanced) | 강화 모드 훅 |
| `metadata_generation.txt` | YouTube 메타데이터 | Step 2.5 | 제목, 태그, 설명 생성 |
| `thumbnail_style.txt` | 썸네일 스타일 | Step 2.5 | 썸네일 타이틀 생성 가이드 |
| `story_bible.txt` | 스토리 바이블 | Step 3 | 전체 스토리 구조, 캐릭터, 세계관 JSON 생성 |
| `story_bible_improve.txt` | 바이블 개선 | Step 3.5 | 기존 바이블을 개선/보강 |
| `story_summarize.txt` | 파트 간 요약 | Step 4 | Part1→Part2, Part2→Part3 넘길 때 요약 |
| `structural_outline.txt` | 구조적 아웃라인 | Step 3.5 | 3-Part 구조 아웃라인 (트위스트/복선/회수) |
| `craft_rules.txt` | 글쓰기 규칙 | Step 4 | 대본 작성 시 필수 규칙 (대사 비율, 감정 표현 등) |
| `pacing_part1.txt` | 파트1 페이싱 | Step 4 (Part1) | 파트1 구조 가이드 (도입, 인물 소개, 첫 긴장) |
| `pacing_part2.txt` | 파트2 페이싱 | Step 4 (Part2) | 파트2 구조 가이드 (갈등 심화, 중간 반전) |
| `pacing_part3.txt` | 파트3 페이싱 | Step 4 (Part3) | 파트3 구조 가이드 (클라이맥스, 결말) |
| `image_style.txt` | SD 아트 스타일 | Step 6 | SD 이미지 아트 스타일 문자열 |
| `image_llm_prompt.txt` | LLM→SD 규칙 | Step 6 | Gemini가 SD 프롬프트 생성 시 따라야 할 규칙 |

### 6.3 프롬프트 작성 규칙

1. **언어**: 영어 권장 (Gemini API + SD 모두 영어가 효과적)
2. **길이**: 100~500단어 (너무 짧으면 품질↓, 너무 길면 Gemini 무시)
3. **구조**: 역할 정의 → 규칙 → 출력 형식 → 예시 순
4. **금지형 피하기**: "~하지마" 대신 "~해야 한다" 긍정형 지시
5. **숫자 제한**: "3~5개" 처럼 구체적 범위 명시
6. **플레이스홀더**: `{topic}`, `{style_hint}`, `{previous_summary}` 등 런타임 치환

### 6.4 프롬프트 예시 (topic_generation.txt)

```
You are a creative Korean content writer specializing in comedy stories.

TASK: Generate ONE unique and engaging comedy topic in Korean (1 sentence).

RULES:
1. The topic must be a realistic everyday situation with comedic potential
2. Include a specific trigger event that starts the comedy
3. The topic should appeal to Korean audience aged 20-50
4. Output ONLY the topic text, nothing else
5. Write in Korean

CONTEXT:
- Tone: {tone}
- Setting: {place}
- Relationship: {relationship}
- Trigger: {trigger}

GOOD EXAMPLES:
- "카페에서 전 여자친구를 만났는데 옆에 앉은 사람이 현 여자친구였다"
- "회사 단체 카톡에 여자친구한테 보낼 메시지를 잘못 보냈다"
- "배달 음식에 쪽지가 적혀있었는데 읽자마자 소름이 돋았다"
```

---

## 7. 팩 생성 체크리스트

새 팩을 만들 때 이 체크리스트를 따르세요:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 새 팩 생성 체크리스트
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

□ 1. 디렉토리 생성
     assets/packs/{pack_id}/
     assets/packs/{pack_id}/prompts/

□ 2. manifest.json 작성
     - package_id (고유, 영문_snake_case)
     - category, genre, tags

□ 3. settings.json 작성 (이 문서의 섹션 4 참조)
     □ pack_info
     □ requirements
     □ style
     □ tts (narrator, character_mapping, emotion_weights)
     □ characters (_default 필수!)
     □ content (duration_minutes, min/max_turns)
     □ assets (bgm/sfx_folder, sfx_category)
     □ visual (forced_style, thumbnail_backgrounds, safe_fallbacks)
     □ sfx (category_guide, keyword_map)           ← v60 필수
     □ atmosphere (mood_map, keywords)              ← v60 필수
     □ emergency (template_sequence, 30~50턴)       ← v60 필수
     □ video (pause_duration, zoom_speed)
     □ hook_style (top_label, colors, duration)
     □ thumbnail (text_default, style_guide)
     □ sd (positive, negative, cfg_scale, steps)
     □ visual_storytelling (characters, image_generation)
     □ scene_analyzer (art_style_prefix, camera_guide, good_examples)

□ 4. topics.json 작성 (시나리오 풀)
     □ templates (최소 3개)
     □ tags
     □ scenario.tone_pool (최소 3개)
     □ scenario.relationship_pool
     □ scenario.place_pool

□ 5. prompts/ 폴더 — 20개 프롬프트 파일
     □ pd_system.txt
     □ writer_system.txt
     □ sd_prompts.json
     □ topic_generation.txt       ← v60
     □ topic_enhanced.txt         ← v60
     □ hook_generation.txt        ← v60
     □ hook_enhanced.txt          ← v60
     □ metadata_generation.txt    ← v60
     □ thumbnail_style.txt        ← v60
     □ story_bible.txt            ← v60
     □ story_bible_improve.txt    ← v60
     □ story_summarize.txt        ← v60
     □ structural_outline.txt     ← v60
     □ craft_rules.txt            ← v60
     □ pacing_part1.txt           ← v60
     □ pacing_part2.txt           ← v60
     □ pacing_part3.txt           ← v60
     □ image_style.txt            ← v60
     □ image_llm_prompt.txt       ← v60

□ 6. .revpack 생성 (ZIP 패키징)
     python -c "
     import zipfile
     from pathlib import Path
     pack_dir = Path('assets/packs/{pack_id}')
     with zipfile.ZipFile(f'{pack_dir.name}.revpack', 'w', zipfile.ZIP_DEFLATED) as zf:
         for f in pack_dir.rglob('*'):
             if f.is_file():
                 zf.write(f, f.relative_to(pack_dir))
     print(f'{pack_dir.name}.revpack 생성 완료')
     "

□ 7. 로딩 테스트
     python -c "
     import sys; sys.path.insert(0, 'src')
     from config.pack_config import load_pack_by_id, get_prompt, get_sfx_config, get_atmosphere_config, get_emergency_sequence
     load_pack_by_id('{pack_id}')
     assert get_prompt('topic_generation'), 'topic_generation 누락!'
     assert get_prompt('craft_rules'), 'craft_rules 누락!'
     assert get_sfx_config().category_guide, 'sfx category_guide 누락!'
     assert get_atmosphere_config().mood_map, 'atmosphere mood_map 누락!'
     assert get_emergency_sequence(), 'emergency sequence 누락!'
     print('ALL CHECKS PASSED')
     "

□ 8. 4-Layer 검증
     □ Layer 1: 데이터 흐름 — get_prompt()가 올바른 텍스트 반환?
     □ Layer 2: 의존성 — TTS character_mapping의 ID가 실제 음성 모델과 매칭?
     □ Layer 3: 프로덕션 — 120장 이미지 + 50턴 대본 시 이상 없음?
     □ Layer 4: 빈 필드 — 선택적 필드가 비어도 폴백이 동작?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 8. pack_creator_full.py 자동 생성

`tools/pack_creator_full.py`를 사용하면 Gemini가 자동으로 팩을 생성합니다.

### 사용법

```python
python tools/pack_creator_full.py --genre comedy --name "코미디 기본팩" --style "cheerful cartoon"
```

### 자동 생성되는 항목

| 항목 | 생성 방식 |
|------|----------|
| manifest.json | 입력 파라미터 기반 |
| settings.json | Gemini가 장르에 맞게 생성 (tts, visual, sfx, atmosphere, emergency 포함) |
| topics.json | Gemini가 장르별 시나리오 풀 생성 |
| prompts/ 20개 | Gemini가 장르별 프롬프트 텍스트 생성 |
| .revpack | 자동 ZIP 패키징 |

### GeneratedPrompts 데이터클래스 (v60)

```python
@dataclass
class GeneratedPrompts:
    pd_system: str          # PD 시스템 프롬프트
    writer_system: str      # 작가 시스템 프롬프트
    sd_positive: str        # SD positive
    sd_negative: str        # SD negative
    # ... 기존 9개 필드 ...

    # v60: 팩-클라이언트 아키텍처
    topic_generation: str       # 토픽 생성
    topic_enhanced: str         # 강화 토픽
    hook_generation: str        # 훅 생성
    hook_enhanced: str          # 강화 훅
    metadata_generation: str    # 메타데이터
    thumbnail_style_guide: str  # 썸네일 스타일
    story_bible: str            # 스토리 바이블
    story_bible_improve: str    # 바이블 개선
    story_summarize: str        # 파트 간 요약
    structural_outline: str     # 구조적 아웃라인
    craft_rules: str            # 글쓰기 규칙
    pacing_part1: str           # 파트1 페이싱
    pacing_part2: str           # 파트2 페이싱
    pacing_part3: str           # 파트3 페이싱
    image_style: str            # 이미지 스타일
    image_llm_prompt: str       # LLM→SD 규칙
    sfx_config: Dict            # SFX 설정
    atmosphere_config: Dict     # 분위기 설정
    emergency_sequence: List    # 비상 시퀀스
```

---

## 9. 기존 팩 참조표

| 팩 ID | 카테고리 | 장르 | 아트 스타일 | 훅 라벨 | 감정 우선 |
|--------|----------|------|-----------|---------|----------|
| `horror_default` | horror | horror | monochrome manga, ink drawing | 【 괴 담 】 | scared, calm |
| `horror_mystery` | horror | mystery | documentary noir, high contrast | 【 미스터리 】 | calm, scared |
| `senior_touching` | senior | touching | warm watercolor, soft pastel | 【 감 동 】 | sad, calm |
| `senior_makjang` | senior | makjang | dramatic webtoon, intense lighting | 【 막 장 】 | angry, sad |

### 팩별 SFX 태그

| 팩 | 주요 SFX 태그 |
|----|-------------|
| horror | tension, heartbeat, suspense, jumpscare, whisper, footsteps, door, thunder |
| touching | sad, crying, happy, whoosh |
| makjang | tension, dramatic, slam, crash |

### 팩별 분위기 키

| 팩 | 분위기 키 |
|----|----------|
| horror | horror, tense, mysterious |
| touching | peaceful, sad, happy |
| makjang | tense, dramatic, emotional |

---

## 10. 트러블슈팅

### Q: 팩 로딩 후 get_prompt()가 빈 문자열 반환

```python
# 확인 방법
from config.pack_config import ACTIVE_PACK
print(f"is_loaded: {ACTIVE_PACK.is_loaded}")
print(f"pack_id: {ACTIVE_PACK.pack_id}")
print(f"topic_generation: {bool(ACTIVE_PACK.prompts.topic_generation)}")
```

**원인**: 프롬프트 파일이 prompts/ 폴더에 없거나, 파일명 오타
**해결**: 체크리스트 섹션 5번 재확인

### Q: SFX 태그가 매칭되지 않음

**원인**: `keyword_map`의 값이 `assets/sfx/{sfx_folder}/` 아래 파일명과 불일치
**해결**: `sfx_registry.py`의 등록된 태그 목록과 대조

### Q: GUI에서 채널 선택 시 v60 설정 미적용

**원인**: `_load_package_to_active_pack()`에서 `raw_settings`가 없음
**해결**: 채널 JSON에 `settings.json` 내용이 포함되어 있는지 확인

### Q: .revpack ZIP에서 프롬프트 로딩 실패

**원인**: ZIP 내부 경로가 `prompts/topic_generation.txt`가 아닌 다른 경로
**해결**: ZIP 내부 구조 확인 — `zipfile.ZipFile.namelist()` 출력

---

## 파이프라인 데이터 흐름 (팩 기준)

```
.revpack 로딩 → ACTIVE_PACK 전역 설정
  ↓
1. ScenarioPlanner.create_topic()
   - get_prompt("topic_generation") ← prompts/topic_generation.txt
   - get_scenario_pools()           ← topics.json → PackScenario
   - Gemini API → 토픽 1줄 (한국어)
  ↓
2. ScenarioPlanner.create_powerful_hook()
   - get_prompt("hook_generation")  ← prompts/hook_generation.txt
   - Gemini API → 훅 텍스트
  ↓
3. ScenarioPlanner._build_story_bible()
   - get_prompt("story_bible")      ← prompts/story_bible.txt
   - Gemini API → 스토리 바이블 JSON
  ↓
4. ScriptWriters.write_part() × 3파트
   - get_prompt("craft_rules")      ← prompts/craft_rules.txt
   - get_prompt("pacing_part1/2/3") ← prompts/pacing_partN.txt
   - get_prompt("writer_system")    ← prompts/writer_system.txt
   - Gemini API → 대본 [{role, character, text, emotion}, ...]
  ↓
5. TTS (GPT-SoVITS)
   - ACTIVE_PACK.tts.character_mapping ← settings.json tts
   - 음성 합성 → WAV
  ↓
6. SceneAnalyzer → SD 이미지 생성
   - get_prompt("image_style")      ← prompts/image_style.txt
   - get_prompt("image_llm_prompt") ← prompts/image_llm_prompt.txt
   - get_atmosphere_config()        ← settings.json atmosphere
   - Gemini → SD WebUI → PNG
  ↓
7. SFX 분석
   - get_sfx_config()               ← settings.json sfx
  ↓
8. RemotionAssembler → MP4 렌더링
   - ACTIVE_PACK.hook_style         ← settings.json hook_style
  ↓
9. YouTube 업로드
```

---

> **이 문서를 읽으면 코드 수정 없이 새 장르의 팩을 만들 수 있습니다.**
> 질문이 있으면 기존 팩(`assets/packs/horror_default/`)을 참조하세요.
