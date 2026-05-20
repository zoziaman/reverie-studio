# Reverie Pack Schema v59

> 이 문서는 v59 Visual Storytelling을 지원하는 팩의 표준 스키마를 정의합니다.
> 최종 업데이트: 2026-02-09

---

## 개요

v59부터 팩은 **Visual Storytelling** 기능을 지원합니다:
- 캐릭터 일관성 (Character Consistency)
- 장면 분석 기반 이미지 생성 (SceneAnalyzer)
- 캐릭터/배경 라이브러리 (사전 생성)
- 시각 효과 (비네팅, 색감 필터, Ken Burns)

---

## 팩 디렉토리 구조

```
assets/packs/{pack_id}/
├── manifest.json          # 필수: 메타 정보
├── settings.json          # 필수: 핵심 설정
├── prompts/
│   └── sd_prompts.json    # 선택: SD 프롬프트 오버라이드
└── topics.json            # 선택: 주제 템플릿
```

---

## 1. manifest.json (필수)

팩의 메타 정보를 정의합니다.

```json
{
  "package_id": "horror_mystery",
  "package_name": "미스터리 공포팩",
  "version": "59.1.0",
  "author": "Reverie Studio",
  "description": "실화 기반 미스터리 공포 콘텐츠용 팩",
  "created_at": "2026-02-09",

  "reverie_version_min": "1",
  "reverie_version_max": null,

  "license": {
    "type": "free",
    "key_required": false,
    "expires_at": null
  },

  "channel_type": "horror",
  "channel_display_name": "미스터리 공포채널"
}
```

### 필수 필드

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `package_id` | string | 고유 ID (영문, 언더스코어) | `"horror_mystery"` |
| `package_name` | string | 표시 이름 | `"미스터리 공포팩"` |
| `version` | string | 팩 버전 (semver) | `"59.1.0"` |
| `reverie_version_min` | string | **무조건 "1"** | `"1"` |
| `channel_type` | string | 채널 유형 | `"horror"`, `"senior"`, `"education"` |

> ⚠️ **주의**: `reverie_version_min`은 반드시 `"1"`로 설정하세요.
> `"59"` 등으로 설정하면 호환성 오류가 발생합니다!

---

## 2. settings.json (필수)

팩의 핵심 설정을 정의합니다.

```json
{
  "visual_storytelling": {
    "enabled": true,
    "version": "v59.1.0",

    "characters": {
      "narrator": {
        "id": "narrator",
        "name": "나레이터",
        "base": "dark gray abstract humanoid form, no facial features, soft edges",
        "style": "minimalist, atmospheric, muted tones",
        "expressions": {
          "neutral": "calm observing presence",
          "tense": "slightly forward lean, alert presence"
        },
        "poses": {
          "standing": "upright observing pose",
          "sitting": "seated contemplative pose"
        }
      },
      "ghost": {
        "id": "ghost",
        "name": "귀신",
        "base": "pitch black humanoid silhouette, single glowing red dot eye",
        "style": "minimalist horror, high contrast, backlighting",
        "expressions": {
          "menacing": "elongated limbs, forward lean",
          "lurking": "partially visible, edge of frame"
        },
        "poses": {
          "standing": "tall imposing silhouette",
          "approaching": "mid-stride toward camera"
        }
      },
      "_default": {
        "base": "dark shadowy silhouette, no facial features",
        "style": "minimalist horror, high contrast"
      }
    },

    "image_generation": {
      "target_images": 120,
      "min_images": 100,
      "max_images": 150,
      "reuse_threshold": 0.85,
      "quality_threshold": 0.7,
      "max_consecutive_reuse": 2
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

    "sd_model": {
      "checkpoint": "realisticVisionV51_v51VAE",
      "vae": null,
      "positive_base": "masterpiece, best quality, dark atmosphere",
      "negative_base": "realistic face, detailed face, nsfw"
    },

    "subtitle_style": {
      "font_family": "NanumSquareRoundEB",
      "font_size": 42,
      "font_weight": "bold",
      "text_color": "#FFFFFF",
      "stroke_color": "#000000",
      "stroke_width": 3,
      "shadow_color": "rgba(0,0,0,0.8)",
      "shadow_blur": 8,
      "background_enabled": true,
      "background_color": "rgba(0,0,0,0.6)",
      "background_padding": 12,
      "background_radius": 8,
      "position": "bottom",
      "margin_bottom": 60
    },

    "visual_effects": {
      "vignette_enabled": true,
      "vignette_intensity": 0.4,
      "vignette_color": "#000000",
      "color_filter_enabled": true,
      "color_filter": "horror",
      "color_filter_intensity": 0.3,
      "ken_burns_enabled": true,
      "ken_burns_zoom_range": [1.0, 1.15],
      "ken_burns_pan_enabled": true,
      "film_grain_enabled": true,
      "film_grain_intensity": 0.15
    },

    "transitions": {
      "default": "crossfade",
      "duration": 0.5,
      "scene_change": "fade_black",
      "scene_change_duration": 0.8
    }
  },

  "tts": {
    "default_voice": "narrator_male",
    "character_mapping": {
      "나레이션": "narrator_male",
      "나레이터": "narrator_male",
      "할아버지": "grandpa",
      "할머니": "grandma",
      "남자": "man",
      "여자": "woman"
    },
    "default_emotion": "calm",
    "allowed_emotions": ["calm", "scared", "whisper", "sad", "angry"]
  },

  "sd": {
    "positive": "masterpiece, best quality, dark atmosphere, cinematic",
    "negative": "(worst quality:1.4), (low quality:1.4), nsfw, text, watermark",
    "cfg_scale": 6.5,
    "steps": 28,
    "sampler": "DPM++ 2M Karras",
    "width": 1024,
    "height": 576
  },

  "visual": {
    "character_system_enabled": false,
    "forced_style": {
      "force_positive": "documentary mystery style, noir lighting, cinematic",
      "force_negative": "realistic face, detailed face, photograph, 3d render"
    },
    "thumbnail_backgrounds": [
      "abandoned hallway, flickering light, no people",
      "empty hospital corridor, eerie silence, no people"
    ],
    "safe_fallbacks": [
      "empty old room, dusty furniture, dim lamp light",
      "rainy window, blurry city lights, melancholic mood"
    ]
  },

  "video": {
    "pause_duration": 0.4,
    "zoom_speed": 1.0,
    "fps": 30
  },

  "hook_style": {
    "top_label": "【 미스터리 】",
    "top_color": "#4169E1",
    "main_color": "#FFFFFF",
    "bg_color": [0, 0, 0],
    "duration": 4.0
  },

  "assets": {
    "bgm_folder": "horror",
    "sfx_folder": "horror",
    "sfx_enabled": true,
    "sfx_category": "horror",
    "sfx_intensity": "medium"
  },

  "content": {
    "duration_minutes": 7,
    "min_turns": 100,
    "max_turns": 180
  }
}
```

---

## 3. characters 필드 상세

### 필수 구조

```json
"characters": {
  "{character_id}": {
    "id": "string",           // 캐릭터 고유 ID
    "name": "string",         // 표시 이름 (한글 가능)
    "base": "string",         // SD 기본 프롬프트
    "style": "string",        // SD 스타일 프롬프트
    "expressions": {          // 표정 라이브러리 (선택)
      "neutral": "string",
      "happy": "string",
      ...
    },
    "poses": {                // 포즈 라이브러리 (선택)
      "standing": "string",
      "sitting": "string",
      ...
    }
  },
  "_default": {               // 필수: 폴백용 기본 캐릭터
    "base": "string",
    "style": "string"
  }
}
```

### 예시: 공포 채널 캐릭터

```json
"characters": {
  "narrator": {
    "id": "narrator",
    "name": "나레이터",
    "base": "dark gray abstract humanoid form, no facial features, soft edges, observing presence",
    "style": "minimalist, atmospheric, muted tones",
    "expressions": {
      "neutral": "calm stance",
      "tense": "slightly forward lean"
    }
  },
  "ghost": {
    "id": "ghost",
    "name": "귀신",
    "base": "pitch black humanoid silhouette, single glowing red dot eye in center of head, no other facial features, elongated limbs",
    "style": "minimalist horror, high contrast, backlighting, dramatic shadows",
    "expressions": {
      "menacing": "elongated limbs spread, looming presence",
      "lurking": "partially visible at edge of frame"
    }
  },
  "protagonist": {
    "id": "protagonist",
    "name": "주인공",
    "base": "black humanoid silhouette, completely featureless, no face details, simple human outline",
    "style": "minimalist, clean edges, subtle backlighting"
  },
  "_default": {
    "base": "dark shadowy silhouette, no facial features, abstract human form",
    "style": "minimalist horror, high contrast"
  }
}
```

### 예시: 시니어 채널 캐릭터

```json
"characters": {
  "narrator": {
    "id": "narrator",
    "name": "나레이터",
    "base": "soft sky blue rounded silhouette figure, gentle glow, abstract friendly form",
    "style": "flat vector art, pastel colors, Kurzgesagt style"
  },
  "grandma": {
    "id": "grandma",
    "name": "할머니",
    "base": "warm coral pink rounded silhouette, soft edges, gentle hunched posture, simple curved line for warm smile",
    "style": "flat vector art, pastel watercolor feel, heartwarming mood",
    "expressions": {
      "happy": "wide curved smile, bright dot eyes",
      "sad": "downturned curve mouth, drooping dot eyes",
      "loving": "gentle smile, arms slightly open"
    }
  },
  "_default": {
    "base": "soft colored abstract humanoid silhouette, gentle form",
    "style": "flat vector art, pastel colors, Headspace style"
  }
}
```

---

## 3-1. 캐릭터 base 프롬프트 품질 기준 (v59.9.0)

> **v59.9.0에서 SceneAnalyzer가 캐릭터 외모를 sd_prompt에 넣지 않도록 변경됨.**
> PromptComposer가 팩의 `base` 프롬프트를 SD 프롬프트 앞에 자동 삽입합니다.
> 따라서 `base` 프롬프트의 품질이 **이미지 캐릭터 구별의 핵심**입니다.

### 필수 요소 (없으면 캐릭터 구별 불가)

| 요소 | 설명 | 예시 |
|------|------|------|
| **성별+나이** | SD가 인물을 그리는 기본 축 | `elderly Korean grandmother`, `young Korean man` |
| **얼굴 특징** | Weight 부여로 일관성 강화 | `(wrinkled face:1.3)`, `round cheeks, soft features` |
| **헤어** | 캐릭터 구별 1순위 시각 요소 | `grey hair in bun`, `short black hair` |
| **의상** | 문화권/역할 표현 | `traditional hanbok`, `business suit`, `casual cardigan` |
| **안전** | NSFW 방지 필수 | `fully clothed` |

### 권장 요소 (있으면 품질 상승)

| 요소 | 설명 | 예시 |
|------|------|------|
| 체형/자세 | 캐릭터 성격 표현 | `hunched posture`, `confident stance` |
| 표정 기본값 | 기본 감정 | `warm smile`, `stern expression` |
| Weight 부여 | SD 1.5 토큰 우선도 | `(elderly Korean grandmother:1.4)` |

### 품질 등급

| 등급 | base 길이 | 필수 요소 | 예시 팩 |
|------|----------|----------|---------|
| ★★★ | 120자+ | 전부 포함 | `senior_touching` |
| ★★ | 80~120자 | 성별+나이+헤어+의상 | `senior_family_drama` |
| ★ | 50~80자 | 성별+나이만 | 최소 허용 수준 |
| ❌ | <50자 | 실루엣/색상만 | 캐릭터 구별 불가 |

### 좋은 예시 vs 나쁜 예시

```json
// ❌ 나쁜 예시 (캐릭터 구별 불가):
"grandma": {
  "base": "dusty rose silhouette, tense posture, simple stern expression",
  "style": "flat vector art"
}
// 문제: 성별 없음, 나이 없음, 의상 없음, 헤어 없음

// ✅ 좋은 예시 (캐릭터 구별 가능):
"grandma": {
  "base": "(elderly Korean grandmother:1.4), (wrinkled face:1.3), warm wrinkled smile, grey hair in bun, traditional hanbok, kind eyes, fully clothed",
  "style": "watercolor illustration, warm emotional tones"
}
// 성별(grandmother) + 나이(elderly) + 얼굴(wrinkled) + 헤어(grey in bun) + 의상(hanbok) + 안전(fully clothed)
```

### narrator 특수 규칙

- narrator의 `base`는 **화면에 등장하지 않음** (목소리만)
- SceneAnalyzer가 나레이션 장면에서 narrator를 그리지 않도록 처리
- narrator `base`는 간단해도 무방 (실제 렌더링되지 않음)
- 단, PromptComposer가 나레이터를 실수로 그릴 경우를 대비해 `abstract silhouette` 유지 권장

---

## 4. 검증 규칙

팩 로드 시 다음 규칙을 검증합니다:

### 필수 검증

| 규칙 | 설명 |
|------|------|
| `package_id` 존재 | 팩 ID 필수 |
| `reverie_version_min == "1"` | 호환성 보장 |
| `channel_type` 유효값 | `horror`, `senior`, `education` 등 |
| `characters`가 객체 | 리스트 ❌, 객체 ✅ |
| `characters._default` 존재 | 폴백 캐릭터 필수 |

### 경고 (오류 아님)

| 규칙 | 설명 |
|------|------|
| `visual_storytelling.enabled` 누락 | 기본값 false |
| `sd_model.checkpoint` 누락 | 현재 모델 사용 |
| `expressions` 비어있음 | 표정 변경 불가 |

---

## 5. 마이그레이션 가이드

### 기존 팩 → v59 변환

1. **manifest.json 분리**
   - 단일 JSON에서 메타 정보 추출

2. **characters 형식 변경**
   ```json
   // Before (잘못됨)
   "characters": ["types", "count", "special"]

   // After (올바름)
   "characters": {
     "narrator": { "base": "...", "style": "..." },
     "_default": { "base": "...", "style": "..." }
   }
   ```

3. **visual_storytelling 섹션 추가**
   - `enabled: true` 설정
   - `sd_model`, `subtitle_style`, `visual_effects` 정의

---

## 6. 템플릿

`assets/packs/_template_v59/` 디렉토리에 빈 템플릿이 있습니다.

```bash
# 새 팩 생성
cp -r assets/packs/_template_v59 assets/packs/my_new_pack
# manifest.json, settings.json 수정
```

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|----------|
| v59.1.0 | 2026-02-09 | 초기 스키마 정의 |
