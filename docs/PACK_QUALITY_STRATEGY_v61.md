# 팩 품질 전략 v61 — SD 이미지 + 대본 + TTS 전면 개선

> Superseded note, 2026-05-22: For video-toon character consistency, use
> `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md` as the active rule. ControlNet and
> IP-Adapter are optional support for generating missing actor variants, not the
> primary runtime consistency mechanism.

> **작성일**: 2026-02-17
> **상태**: 전략 수립 완료, 실행 대기
> **핵심 결정**: 전 장르 2D 웹툰/일러스트 통일, 실사풍 완전 폐기

---

## 1. 배경: 창업자 피드백 (원문 요약)

### 1-1. SD 이미지 품질 (최우선)

> "SD를 쓰면서 자꾸 퀄리티를 집요하게 말하게 된다. 단순 라디오 드라마가 아닌, 이미지 자체에서도 스토리가 느껴지고 완벽하게 보여야한다."

> "불쾌한골짜기가 어떤 모델을 써도 나온다"

> "2D일러스트 또는 2D웹툰으로 가도되는데, 그걸 분명히 말했는데, 결국 그런느낌으로는 절대 수정안하더라?"

> "한명이 나와야하는 장면에 억지로 여러명이 나오고 얼굴이 같다. 표정이 기괴해 항상."

> "Google Whisk의 결과물을 보고 너무 부러웠다.. 캐릭터 일관성도 나오고, 그에 맞는 장면이 너무 잘나온다."

### 1-2. 대본 완성도

> "제미나이의 대본집필력보다 클로드의 대본집필력이 좋았다. 그냥 완성만 시키는게 목표가 아니라 타겟층의 반응을 이끌정도의 문학적 기능이 필요하다."

### 1-3. TTS 역할 매핑

> "역할매핑은 분명 젊은여성인데 중년여성목소리가 매핑이 되는경우가 있었다."

---

## 2. 기술 분석: 발견된 근본 원인

### 2-1. 🔴 해상도 버그 — 1280×720으로 생성 (SD 1.5 한계 초과)

```
팩 설정(SDModelConfig):  768×432 (SD 1.5 최적, 16:9)
실제 적용(ImagePipeline): 1280×720 (config.VIDEO_WIDTH/HEIGHT)

원인: image_pipeline.py의 _sd_generate_single()에서
      ComposedPrompt.width/height를 무시하고 self.video_width 사용
```

**결과:**
- SD 1.5는 512×512로 학습됨 → 1280×720은 약 3.5배 큰 해상도
- 같은 얼굴 복제 (1명 장면에 여러 명)
- 인체 비율 붕괴
- 기괴한 표정

**수정:** image_pipeline.py에서 ComposedPrompt의 width/height를 우선 사용하도록 변경 (코드 5줄)

### 2-2. 🔴 모델 부적합 — DreamShaper 8 = 반실사

```
현재 모델:    dreamshaper_8.safetensors (반실사 특화)
원하는 스타일: 2D 웹툰 / 일러스트
```

DreamShaper 8은 사실적 인물 표현에 특화. 프롬프트에 "2D illustration"을 넣어도 모델이 실사 방향으로 끌어감.
→ 불쾌한 골짜기의 근본 원인.

**수정:** 2D 일러스트 전용 체크포인트로 교체 (팩 설정만 변경)

### 2-3. 🟡 negative 프롬프트에 복수 인물 차단 부재

현재 "solo" 키워드만으로 1명 제어 시도 → SD 1.5에서 "solo"가 보장되지 않음.
negative에 `(multiple people:1.4), (2girls:1.4), (crowd:1.3)` 등 없음.

### 2-4. ✅ art_style_config는 정상 전달

시니어 팩에 `scene_analyzer` 블록이 있어서 수채화/웹툰 스타일이 Gemini에게 정상 전달됨.
공포 팩은 DEFAULT_ART_STYLE(흑백 만화)로 올바르게 폴백.

---

## 3. 핵심 결정: 전 장르 2D 웹툰/일러스트 통일

### 3-1. 왜 2D인가?

| 스타일 | 불쾌한골짜기 | 캐릭터 일관성 | SD 1.5 호환 | 시청자 수용성 |
|--------|:-----------:|:----------:|:----------:|:----------:|
| 실사 | 🔴 매우 높음 | 🔴 거의 불가 | 🔴 한계 | 🟡 검증 필요 |
| 반실사 (DreamShaper) | 🔴 높음 | 🔴 어려움 | 🟡 부분 가능 | 🟡 위험 |
| **2D 일러스트/웹툰** | **✅ 없음** | **🟡 상대적 용이** | **✅ 최적** | **✅ YouTube 검증됨** |

### 3-2. 장르별 아트 스타일 방향

| 장르 | 아트 스타일 | 참조 | 모델 후보 |
|------|-----------|------|----------|
| **시니어 감동** | 따뜻한 수채화 일러스트 | 파스텔톤, 부드러운 라인 | Pastel-Mix / AnythingV5 |
| **시니어 막장** | 강렬한 웹툰 드라마 | 강한 명암, 극적 표정 | Counterfeit-V3 / MeinaMix |
| **공포** | 흑백 만화 / 다크 일러스트 | 고대비, 잉크 텍스처 | Anything-ink / DarkSushi |
| **미스터리** (신규) | 느와르 일러스트 | 짙은 그림자, 차가운 톤 | MeinaMix + LoRA |
| **로맨스** (신규) | 순정만화 스타일 | 밝은 톤, 꽃 이펙트 | AnythingV5 + LoRA |
| **코미디** (신규) | 밝은 카툰 | 과장된 표정, 비비드 색상 | ToonYou / AnythingV5 |

### 3-3. 모델 교체 전략

**원칙: 팩별로 최적 모델 지정 (팩-클라이언트 아키텍처)**

```json
// 팩 settings.json 예시
"visual_storytelling": {
    "sd_model": {
        "checkpoint": "anythingV5_PrtRE.safetensors",
        "width": 768,
        "height": 432,
        "cfg_scale": 7.0,
        "steps": 20,
        "clip_skip": 2
    }
}
```

새 장르 = 새 팩 + 적합한 모델 지정. 코드 수정 0줄.

---

## 4. 실행 계획

### Phase A: 인프라 버그 수정 ✅ 완료 (2026-02-17)

| 작업 | 파일 | 변경량 | 효과 |
|------|------|--------|------|
| ✅ 해상도 버그 수정 | image_pipeline.py | ~5줄 | 768×432 적용 → 얼굴 복제/비율 붕괴 해결 |
| ✅ negative에 복수인물 차단 추가 | 팩 sd_prompts.json + settings.json | 설정만 | "solo" 보강 |

### Phase B: 모델 교체 + 테스트 ✅ 완료 (2026-02-17)

**비교 테스트 실행:**
- 4개 모델 × 6장면 = 24장 (밝은 3장면 + 어두운 3장면)
- 설정: 768×432, seed=42, steps=20, cfg=7.0, DPM++ 2M Karras
- 결과: `test_output/model_comparison/` + `test_output/model_comparison_round2/`

**테스트 모델 및 결과:**
| 모델 | 시니어(따뜻한) | 공포(어두운) | 막장(드라마) | 미스터리(느와르) | 최종 |
|------|:---:|:---:|:---:|:---:|:---:|
| AnythingV5 | ⭐⭐⭐⭐ | ⭐⭐ (캐릭터 소실) | ⚠️ 인물 수 폭발 | ⭐⭐⭐⭐⭐ | ❌ 편차 큼 |
| Flat-2D Animerge | ⭐⭐ (연령 표현 불가) | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ❌ 시니어 부적합 |
| **MeinaMix V12** | **⭐⭐⭐⭐⭐** | ⭐⭐⭐ | **⭐⭐⭐⭐⭐** | ⭐⭐⭐⭐ | **✅ 채택** |
| Counterfeit V3 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 🟡 공포 전용 후보 |

**최종 결정: MeinaMix V12 전 장르 통일**
- 연령 표현 최고 (할머니가 할머니로 보임)
- 감정 전달/스토리텔링 최고
- 인물 수 제어 안정적
- 공포 장면은 프롬프트 강화로 보완, 나중에 공포 전용 팩에서 Counterfeit V3 가능

**적용 완료:**
- senior_touching: meinamix_v12Final.safetensors (steps 20, cfg 7.0)
- senior_makjang: meinamix_v12Final.safetensors (steps 20, cfg 7.0)
- horror_v59: meinamix_v12Final.safetensors (steps 20, cfg 7.0)
- 구 모델 삭제: DreamShaper 8, GhostMix 등 6개 (~23.7GB 확보)

**캐릭터 일관성:**
- IP-Adapter 코드 인프라: ✅ 준비됨 (consistency_manager.py + ip_adapter_bridge.py)
- SD WebUI ControlNet 확장: ❌ 미설치 → 향후 설치 시 즉시 활용 가능
- 현재 보완: 프롬프트 기반 외모 묘사 고정

### Phase C: 프롬프트 품질 심화 ✅ 완료 (2026-03-01)

| 작업 | 파일 | 완료 내용 |
|------|------|---------|
| ✅ craft_rules.txt 대폭 강화 | senior_touching/prompts/craft_rules.txt | SCRIPT_RUBRIC.md 9개 기준 전부 반영: 구체적 배경, 세대 간 오해→이해, 소품 기법, 4인 캐릭터, 오감 디테일, 일상어 기법, 제목 가이드 |
| ✅ craft_rules.txt 막장판 강화 | senior_makjang/prompts/craft_rules.txt | 구체적 배경, 2중 반전, 증거 기법, 도덕적 딜레마, 4인 캐릭터, 오감 디테일, 제목 가이드 |
| ✅ voice_type 세분화 | 양 팩 writer_system.txt | 아들/사위 → middle_man, 며느리/딸 → middle_woman, 손자/손녀 → young_man/young_woman |
| ✅ TTS 캐릭터 매핑 수정 | 양 팩 settings.json | character_mapping: 아들→middle_man, 딸→middle_woman 등 7개 수정 |
| ✅ 할머니/할아버지 SD 프롬프트 | 양 팩 settings.json | elderly 키워드 추가, age_negative/gender_negative 신규 추가 |
| ❌ image_llm_prompt.txt 재설계 | senior_touching + makjang | 다음 단계 |
| ❌ pacing_part1~3.txt 고도화 | senior_touching + makjang | 다음 단계 |

### Phase D: 새 카테고리 팩 생성

- 미스터리, 로맨스, 코미디 등 신규 장르
- 각 장르별 최적 모델 + 프롬프트 세트
- A/B 테스트로 리텐션 검증

---

## 5. 우선순위 요약

```
✅ 완료: Phase A — 해상도 버그 수정 (코드 5줄, 즉각 효과)
✅ 완료: Phase B — MeinaMix V12 전 장르 통일 (24장 비교 테스트 완료)
✅ 부분완료: Phase C — SCRIPT_RUBRIC.md 기준 craft_rules + writer_system + settings 수정 (2026-03-01)
  ❌ 미완: image_llm_prompt.txt 재설계, pacing_part1~3.txt 고도화
1순위: Phase C 마무리 — image_llm_prompt + pacing 고도화
2순위: Phase D — 새 카테고리 확장
3순위: ControlNet + IP-Adapter 설치 → 캐릭터 일관성 강화
```

---

## 6. 관련 파일 매핑

| 영역 | 핵심 파일 | 역할 |
|------|----------|------|
| SD 해상도 | `src/pipeline/image_pipeline.py` | _sd_generate_single() payload width/height |
| SD 모델 설정 | 팩 `settings.json` → visual_storytelling.sd_model | 체크포인트, 해상도, cfg_scale |
| SD 프롬프트 생성 | `src/modules_pro/scene_analyzer.py` | Gemini → SD 프롬프트 |
| 프롬프트 조합 | `src/modules_pro/prompt_composer.py` | 캐릭터 외모 + 스타일 + 품질 합성 |
| 프롬프트 필터링 | `src/modules_pro/visual_director.py` | 최종 sanitize + negative |
| 대본 품질 | 팩 `prompts/craft_rules.txt` | 글쓰기 규칙 |
| 대본 페이싱 | 팩 `prompts/pacing_part1~3.txt` | 파트별 구조 |
| TTS 매핑 | 팩 `settings.json` → tts.character_mapping | 캐릭터 → 음성 모델 |

---

## 7. 알려진 제약사항

### SD 1.5 vs Google Whisk

- Whisk는 **이미지 참조(reference image)** 기반 → 캐릭터 일관성 보장
- SD 1.5는 **텍스트 프롬프트만** → 캐릭터 일관성 한계
- IP-Adapter로 부분 보완 가능하지만 완벽하지 않음
- **SDXL 또는 Flux 전환 시** 품질 대폭 향상 가능 (단, VRAM 8GB 제약)

### RTX 4060 Ti 8GB 제약

- SD 1.5: 768×432 가능 ✅
- SDXL: 1024×1024 가능하지만 느림 (1장 30초+)
- Flux: 8GB에서 어려움 🔴
- **현 단계에서는 SD 1.5 + 2D 모델이 최적**

---

> **이 문서는 팩 품질 개선의 마스터 플랜입니다.**
> Phase A부터 순서대로 실행하며, 각 Phase 완료 시 결과를 검증하고 다음으로 진행합니다.
