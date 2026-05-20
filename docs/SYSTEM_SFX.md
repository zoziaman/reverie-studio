# Auto-SFX 시스템

> 자동 효과음 삽입 시스템
> 최종 업데이트: 2026-02-03 (v57.6.5)

---

## 개요

v57.6.5에서 **Auto-SFX가 MediaFactory 파이프라인에 완전 통합**됨.

---

## 처리 흐름

```
1. 작가 모듈(script_writers.py)이 대본에 sfx_tag 추가
2. MediaFactory가 TTS 완료 후 subtitle_data에서 실제 타이밍 획득
3. sfx_analyzer가 sfx_tag 우선 처리 + AI/키워드 분석 보조
4. sfx_mixer가 FFmpeg로 효과음 믹싱
5. 최종 영상에 효과음 포함
```

---

## 작가 SFX 태그 시스템

script_writers.py에서 대본 생성 시 **sfx_tag 필드 자동 생성**:

```python
# JSON 출력 예시
{
    "script_list": [
        {"role": "narrator", "text": "그 순간...", "emotion": "tension", "sfx_tag": "tension"},
        {"role": "man", "text": "문이 열렸어", "emotion": "scared", "sfx_tag": "door"},
        {"role": "narrator", "text": "평화로운 아침", "emotion": "calm", "sfx_tag": ""}  # 태그 없음
    ]
}
```

---

## 사용 가능한 sfx_tag

| 카테고리 | 태그 |
|----------|------|
| **Horror/Tension** | `tension`, `heartbeat`, `suspense`, `jumpscare`, `whisper` |
| **Environment** | `footsteps`, `door`, `thunder`, `wind`, `night`, `rain` |
| **Emotional** | `sad`, `crying`, `happy` |
| **Common** | `whoosh`, `impact`, `scream`, `glass` |

---

## 태그 사용 규칙

- 전체 대본의 **10~15% 턴**에만 sfx_tag 지정
- `jumpscare`는 **영상당 1-2회**만 사용
- **연속으로 같은 태그** 사용 금지

---

## SFX 분석 우선순위 (sfx_analyzer.py)

```
1순위: 작가 지정 sfx_tag (바로 SFXCue 생성)
2순위: Gemini AI 분석 (sfx_tag 없는 세그먼트만)
3순위: 키워드 기반 분석 (Gemini 실패 시 폴백)
```

---

## SFX 관련 파일

| 파일 | 역할 | v57.6.5 변경 |
|------|------|-------------|
| `script_writers.py` | sfx_tag 생성 | `_role_rule()`에 SFX 규칙 추가 |
| `sfx_analyzer.py` | 대본 분석 | sfx_tag 우선 처리 로직 |
| `sfx_manager.py` | 효과음 관리 | 레지스트리 기반 검색 |
| `sfx_mixer.py` | FFmpeg 믹싱 | 효과음 오버레이 |
| `auto_sfx.py` | 통합 엔진 | 전체 파이프라인 |
| `media_factory.py` | 파이프라인 | STEP 10 Auto-SFX 호출 |
| `settings_manager.py` | GUI 설정 | SFX 설정 관리 |

---

## 효과음 에셋 (assets/sfx/)

```
assets/sfx/
├── common/              # 공통 효과음
│   ├── whoosh.mp3       # 장면 전환
│   └── notification.mp3 # 알림
├── emotional/           # 감정 효과음
│   ├── crying.mp3       # 울음
│   └── piano_sad.mp3    # 슬픈 피아노
└── horror/              # 공포 효과음
    ├── ambient/         # 환경음
    │   ├── night_crickets.mp3
    │   ├── rain.mp3
    │   ├── thunder.mp3
    │   └── wind_howl.mp3
    ├── jump_scare/      # 점프 스케어
    │   ├── impact.mp3
    │   ├── scream.mp3
    │   └── sudden_hit.mp3
    ├── supernatural/    # 초자연
    │   ├── door_creak.mp3
    │   ├── footsteps_slow.mp3
    │   ├── glass_break.mp3
    │   └── whisper.mp3
    └── tension/         # 긴장감
        ├── breathing.mp3
        ├── heartbeat.mp3
        └── suspense_drone.mp3
```

---

## SFX 설정 (settings_manager.py)

```python
# GUI에서 SFX 설정 관리
from gui.settings_manager import SettingsManager
sm = SettingsManager(config_dir)

# SFX 활성화/비활성화
sm.set_sfx_enabled(True)
enabled = sm.get_sfx_enabled()  # True

# SFX 세부 설정
settings = sm.get_sfx_settings()
# {'enabled': True, 'intensity': 'medium', 'master_volume': 0.7}

sm.set_sfx_settings({
    'enabled': True,
    'intensity': 'high',  # low/medium/high
    'master_volume': 0.8
})
```
