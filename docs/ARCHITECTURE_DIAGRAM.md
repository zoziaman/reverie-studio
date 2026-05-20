# Reverie Studio v58.3 - Architecture Diagram

> 시스템 전체 구조를 한눈에 파악하기 위한 다이어그램
> 최종 업데이트: 2026-02-06

---

## 🎯 핵심 파이프라인 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REVERIE STUDIO v58.3                               │
│                        AI 기반 YouTube 영상 자동 생성                         │
│                    + 멀티팩 큐 시스템 + AI법 준수                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  📥 INPUT                                                                    │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐                 │
│  │  Topic   │ + │  .revpack │ + │ Settings │ + │BatchQueue│                 │
│  │  (주제)   │   │  (채널팩) │   │  (설정)   │   │ (멀티팩) │                 │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🧠 SCENARIO PLANNER (시나리오 기획)                                          │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                  │
│  │ ChiefProducer  │→ │  ScriptWriter  │→ │ VisualDirector │                  │
│  │   (PD 역할)     │  │   (작가 역할)   │  │  (연출 역할)    │                  │
│  │  Gemini API    │  │  Gemini API    │  │  프롬프트 생성   │                  │
│  └────────────────┘  └────────────────┘  └────────────────┘                  │
│                              │                                               │
│                              ▼                                               │
│                    ┌──────────────────┐                                      │
│                    │   script_list    │  ← JSON 형식 대본                     │
│                    │  + voice_type    │  ← v58.2.4: 목소리 직접 지정          │
│                    │  + sfx_tag       │  ← 효과음 태그                        │
│                    └──────────────────┘                                      │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
┌────────────────────────────────┐   ┌────────────────────────────────────────┐
│  🎨 IMAGE GENERATOR            │   │  🎤 TTS ENGINE                          │
│  ┌────────────────────────┐    │   │  ┌──────────────────────────────────┐  │
│  │    SD WebUI API        │    │   │  │       GPT-SoVITS v3             │  │
│  │  (Stable Diffusion)    │    │   │  │    (감정 연기 TTS)               │  │
│  └────────────────────────┘    │   │  └──────────────────────────────────┘  │
│           │                    │   │               │                        │
│           ▼                    │   │               ▼                        │
│  ┌────────────────────────┐    │   │  ┌──────────────────────────────────┐  │
│  │  VisualDirector        │    │   │  │     AudioSynthesizer            │  │
│  │  - 팩에서 스타일 로드   │    │   │  │  - voice_type 우선 사용          │  │
│  │  - LoRA 자동 선택       │    │   │  │  - 이름 기반 성별 추론 (폴백)    │  │
│  │  - 네거티브 프롬프트    │    │   │  │  - 감정별 레퍼런스 매칭          │  │
│  └────────────────────────┘    │   │  └──────────────────────────────────┘  │
│           │                    │   │               │                        │
│           ▼                    │   │               ▼                        │
│  ┌────────────────────────┐    │   │  ┌──────────────────────────────────┐  │
│  │   75장 이미지 생성      │    │   │  │     150개 음성 파일 생성          │  │
│  │   (병렬 처리)          │    │   │  │     + full.wav 합성              │  │
│  │   + 볼륨 3배 증폭       │    │   │  └──────────────────────────────────┘  │
│  └────────────────────────┘    │   └────────────────────────────────────────┘
└────────────────────────────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🎬 REMOTION ASSEMBLER (영상 조립)                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         React + TypeScript                           │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │   │
│  │  │  Hook    │ │  Scene   │ │ Subtitle │ │   BGM    │ │  Outro   │   │   │
│  │  │  장면    │ │   장면   │ │   자막   │ │  배경음  │ │   장면   │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  v58.x 신규 기능                                                      │   │
│  │  ├─ AI 제작 표기 (3초 워터마크) - AI법 준수                           │   │
│  │  ├─ 자막 강조 (★★★ 대사) - 빨간색 + 펄스 애니메이션                  │   │
│  │  ├─ TTS 볼륨 조절 (3배 증폭)                                          │   │
│  │  └─ 후킹 → 트랜지션 → 본편 구조                                       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  🔊 AUTO-SFX (효과음 자동 삽입)                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                  │
│  │  SFX Analyzer  │→ │   SFX Manager  │→ │   SFX Mixer    │                  │
│  │  (대본 분석)    │  │  (효과음 매칭)  │  │  (FFmpeg 믹싱) │                  │
│  └────────────────┘  └────────────────┘  └────────────────┘                  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  sfx_tag 시스템                                                       │   │
│  │  ├─ 작가 지정 태그 우선                                                │   │
│  │  └─ Gemini 자동 분석 (빈 구간)                                         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  📤 OUTPUT & UPLOAD                                                          │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                  │
│  │  Final Video   │→ │   Thumbnail    │→ │ YouTube Upload │                  │
│  │   (.mp4)       │  │   Generator    │  │  (OAuth 2.0)   │                  │
│  │ + AI 제작표기  │  │ + Quality Gate │  │ + 자동 예약    │                  │
│  └────────────────┘  └────────────────┘  └────────────────┘                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 v58.3 멀티팩 큐 시스템

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📋 BATCH QUEUE SYSTEM (v58.3)                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
           ┌──────────────────────────┼──────────────────────────┐
           ▼                          ▼                          ▼
   ┌───────────────┐          ┌───────────────┐          ┌───────────────┐
   │ senior_makjang│          │ horror_default│          │senior_touching│
   │    x 3개      │          │    x 2개      │          │    x 5개      │
   └───────┬───────┘          └───────┬───────┘          └───────┬───────┘
           │                          │                          │
           └──────────────────────────┼──────────────────────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │     BatchQueue         │
                         │  (batch_queue.json)    │
                         │                        │
                         │  - pack_id             │
                         │  - prompt_mode         │
                         │  - topic_mode          │
                         │  - auto_upload         │
                         │  - status (pending)    │
                         └────────────┬───────────┘
                                      │
                                      ▼
                         ┌────────────────────────┐
                         │   _queue_worker()      │
                         │   (순차 처리)          │
                         └────────────┬───────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
           ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
           │ load_pack()   │  │ MediaFactory  │  │ auto_upload() │
           │ (팩 활성화)    │  │ (영상 생성)   │  │ (YouTube)     │
           └───────────────┘  └───────────────┘  └───────────────┘
```

---

## 📦 모듈 카테고리별 구조

### 🔴 Entry Points (진입점)
```
main.py          → CLI 실행 (영상 생성)
main_gui.py      → GUI 실행 (CustomTkinter)
```

### 🟢 Pipeline (핵심 파이프라인)
```
modules_pro/
├── scenario_planner.py   # 시나리오 기획 (PD + 작가 + 연출)
├── script_writers.py     # 대본 작성 + sfx_tag + voice_type
├── media_factory.py      # 전체 파이프라인 조율 ★
├── image_generator.py    # SD WebUI 이미지 생성
├── visual_director.py    # 프롬프트 최적화 + LoRA + 팩 스타일
├── audio_synthesizer.py  # GPT-SoVITS TTS
├── remotion_assembler.py # Remotion 영상 조립
└── video_assembler.py    # FFmpeg 백업 조립
```

### 🟡 Core (핵심 기능)
```
core/
├── auto_sfx.py           # Auto-SFX 통합 엔진
├── sfx_analyzer.py       # 대본 → 효과음 분석
├── sfx_manager.py        # 효과음 라이브러리 관리
├── sfx_mixer.py          # FFmpeg 믹싱
├── character_manager.py  # 캐릭터 프로필 관리
├── evaluators.py         # 품질 평가 (StoryCritic, VisualCritic)
└── translator.py         # 다국어 번역
```

### 🔵 GUI (사용자 인터페이스)
```
gui/
├── main_window.py           # 메인 윈도우 (ReverieGUI) ★
│   ├── _add_to_queue()      # v58.3: 큐에 추가
│   ├── _run_queue()         # v58.3: 큐 실행
│   └── _queue_worker()      # v58.3: 큐 워커
├── queue_manager_dialog.py  # v58.3: 큐 관리 다이얼로그
├── admin_dashboard.py       # 관리자 대시보드
├── autopilot_panel.py       # 자동 조종 패널
├── settings_manager.py      # 설정 관리
├── model_manager_dialog.py  # TTS 모델 관리
└── scenario_editor.py       # 시나리오 편집기
```

### 🟣 Utils (유틸리티)
```
utils/
├── youtube_uploader.py    # YouTube API 업로드
├── youtube_analytics.py   # 채널 분석
├── batch_queue.py         # v58.3: 배치 큐 관리 ★
├── nsfw_detector.py       # NSFW 검수
├── thumbnail_generator.py # 썸네일 생성
├── server_manager.py      # SD WebUI 서버 관리
└── model_manager.py       # TTS 모델 관리
```

### ⚙️ Config (설정)
```
config/
├── settings.py            # 전역 설정
├── pack_config.py         # 팩 설정 로더 ★ (v58 완전 팩화)
│   ├── PackTTS            # TTS 설정 (narrator, mapping, emotions)
│   ├── PackVisual         # 비주얼 설정 (forced_style, fallbacks)
│   ├── PackHookStyle      # 후킹 스타일
│   ├── PackSD             # SD 설정 (cfg, steps, model)
│   ├── PackScenario       # 시나리오 풀
│   └── ACTIVE_PACK        # 현재 활성 팩
└── settings_v2.py         # 고급 설정
```

### 🏭 Factory (팩 생성)
```
factory/
├── pack_designer.py       # AI 팩 설계
├── clone_pack_generator.py # 채널 클론
└── factory_tab.py         # 팩토리 GUI 탭
```

### 📊 Insight (분석)
```
insight/
├── channel_analyzer.py    # 채널 분석
├── trend_reporter.py      # 트렌드 리포트
├── style_analyzer.py      # 스타일 분석
└── ai_gatekeeper.py       # AI 컨텐츠 게이트키퍼
```

### 🤝 Council (AI 협의체)
```
council/
├── ai_caller.py           # AI API 호출
├── discussion_engine.py   # 토론 엔진
├── personas.py            # AI 페르소나
└── secretary.py           # 회의록 작성
```

---

## 🔗 의존성 관계도

```
                    ┌─────────────────┐
                    │   main.py       │
                    │   main_gui.py   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ┌───────────────┐  ┌──────────┐  ┌───────────────┐
      │   BatchQueue  │  │ .revpack │  │   Utopia      │
      │   (v58.3)     │  │ (v58.0)  │  │   Engine      │
      └───────┬───────┘  └────┬─────┘  └───────┬───────┘
              │               │                │
              └───────────────┼────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │   media_factory   │ ← 전체 조율
                    └─────────┬─────────┘
                              │
           ┌──────────────────┼──────────────────┐
           ▼                  ▼                  ▼
   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
   │scenario_planner│ │image_generator│ │audio_synth    │
   └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
           │                  │                  │
           ▼                  ▼                  ▼
   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
   │script_writers │  │visual_director│  │ tts_engine    │
   │ + voice_type  │  │ + pack_style  │  │ + 성별 추론   │
   └───────────────┘  └───────────────┘  └───────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │remotion_assembler│
                    │ + AI 제작 표기  │
                    │ + 자막 강조     │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   auto_sfx      │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │youtube_uploader │
                    └─────────────────┘
```

---

## 🎨 .revpack 시스템 (v58 완전 팩화)

```
senior_makjang.revpack (ZIP)
├── manifest.json          # 팩 메타데이터 (id, name, version, genre)
├── settings.json          # 채널 설정 (v58 확장)
│   ├── style              # 스타일 설정
│   ├── content            # 콘텐츠 설정
│   ├── characters         # 캐릭터 설정
│   ├── assets             # 에셋 설정
│   ├── tts                # v58: TTS 설정 (narrator, mapping, emotions)
│   ├── visual             # v58: 비주얼 설정 (forced_style, fallbacks)
│   ├── hook_style         # v58: 후킹 스타일 (colors, duration)
│   ├── sd                 # v58: SD 설정 (cfg, steps, model)
│   ├── thumbnail          # v58: 썸네일 설정
│   └── video              # v58: 비디오 설정 (pause, zoom)
├── topics.json            # 주제 템플릿 (v58 확장)
│   ├── templates          # 주제 템플릿
│   ├── tags               # 태그
│   └── scenario           # v58: 시나리오 풀 (tone, twist, conflict)
└── prompts/
    ├── pd_system.txt      # PD 시스템 프롬프트
    ├── writer_system.txt  # 작가 시스템 프롬프트 + voice_type 가이드
    └── sd_prompts.json    # SD 프롬프트
```

### 팩 로딩 흐름
```
pack_config.py
     │
     ├── load_pack(pack_path) / load_default_pack(genre)
     │        │
     │        ├── manifest.json 파싱
     │        ├── settings.json 복호화
     │        ├── topics.json 로드
     │        └── prompts/* 로드
     │
     ├── get_prompt("pd_system")
     │        └── 팩별 커스텀 프롬프트 반환
     │
     ├── get_tts_settings()
     │        └── narrator, character_mapping, emotions
     │
     ├── get_hook_style()
     │        └── top_label, colors, duration
     │
     └── get_scenario_pools()
              └── tone_pool, twist_pool, conflict_pool
```

---

## 📈 통계 (v58.3 기준)

| 카테고리 | 모듈 수 | 주요 클래스/함수 |
|----------|---------|------------------|
| Pipeline | 15 | MediaFactory, ScenarioPlanner, RemotionAssembler |
| GUI | 12 | ReverieGUI, QueueManagerDialog, AdminDashboard |
| Core | 8 | AutoSFX, CharacterManager, Evaluators |
| Utils | 20 | YouTubeUploader, BatchQueue, NSFWDetector |
| Config | 4 | PackConfig, ACTIVE_PACK, Settings |
| Factory | 3 | PackDesigner, ClonePackGenerator |
| Insight | 7 | ChannelAnalyzer, TrendReporter |
| Council | 6 | AICaller, DiscussionEngine |

---

## 🆕 v58.3 신규 메서드 (main_window.py)

| 메서드 | 라인 | 설명 |
|--------|------|------|
| `_add_to_queue()` | 1764 | 현재 설정을 배치 큐에 추가 |
| `_run_queue()` | 1812 | 큐 실행 시작 (백그라운드 스레드) |
| `_queue_worker()` | 1839 | 큐 작업 순차 처리 루프 |
| `_activate_pack_for_job()` | 1935 | 큐 작업용 팩 활성화 |
| `_auto_upload_video()` | 1963 | 큐 작업용 자동 업로드 |

---

*Last Updated: 2026-02-06 (v58.3.0)*
