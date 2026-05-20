# Auto-SFX 효과음 라이브러리

> 이 폴더에 효과음을 추가하면 Auto-SFX 시스템이 자동으로 인식합니다.

---

## 폴더 구조

```
assets/sfx/
├── horror/                    # 공포 전용
│   ├── tension/               # 긴장감 (배경 드론음, 서스펜스)
│   ├── jump_scare/            # 점프 스케어 (충격음, 비명)
│   ├── ambient/               # 배경 분위기 (바람, 비, 밤)
│   └── supernatural/          # 초자연적 (속삭임, 발걸음, 유리)
│
├── emotional/                 # 감동/로맨스
│
├── common/                    # 공통
│   └── transition/            # 장면 전환
│
└── sfx_registry.json          # 효과음 레지스트리 (자동 생성)
```

---

## 효과음 다운로드 방법

### 추천 무료 사이트

| 사이트 | 링크 | 라이센스 | 특징 |
|--------|------|----------|------|
| **Pixabay** | https://pixabay.com/sound-effects/ | 무료 상업적 사용 | 가장 추천, 한글 검색 |
| **Mixkit** | https://mixkit.co/free-sound-effects/ | 무료 상업적 사용 | 고품질, 카테고리 정리 |
| **Freesound** | https://freesound.org/ | CC0/CC BY | 방대한 양 |
| **Zapsplat** | https://www.zapsplat.com/ | 무료 (크레딧 표기) | 10만개+ |

---

## 필수 효과음 체크리스트

### 공포 (horror/)

#### tension/ (긴장감)
- [ ] `heartbeat.mp3` - 심장 박동 (Pixabay: "heartbeat scary")
- [ ] `suspense_drone.mp3` - 으스스한 드론음 (Pixabay: "horror tension drone")
- [ ] `breathing.mp3` - 거친 숨소리 (Pixabay: "breathing scary")

#### jump_scare/ (점프 스케어)
- [ ] `sudden_hit.mp3` - 갑작스러운 충격음 (Pixabay: "jumpscare sound")
- [ ] `scream.mp3` - 비명 (Pixabay: "horror scream")
- [ ] `impact.mp3` - 타격음 (Pixabay: "impact hit")

#### ambient/ (배경 분위기)
- [ ] `wind_howl.mp3` - 바람 소리 (Pixabay: "wind howling")
- [ ] `rain.mp3` - 빗소리 (Pixabay: "rain loop")
- [ ] `thunder.mp3` - 천둥 (Pixabay: "thunder storm")
- [ ] `night_crickets.mp3` - 밤 귀뚜라미 (Pixabay: "night crickets ambient")

#### supernatural/ (초자연)
- [ ] `whisper.mp3` - 속삭임 (Pixabay: "ghost whisper")
- [ ] `footsteps_slow.mp3` - 느린 발걸음 (Pixabay: "footsteps slow creepy")
- [ ] `door_creak.mp3` - 문 삐걱 (Pixabay: "door creak horror")
- [ ] `glass_break.mp3` - 유리 깨짐 (Pixabay: "glass break")

### 감동 (emotional/)
- [ ] `piano_sad.mp3` - 슬픈 피아노 (Pixabay: "sad piano emotional")
- [ ] `crying.mp3` - 울음소리 (Pixabay: "crying sob")

### 공통 (common/)
- [ ] `whoosh.mp3` - 장면 전환 (Pixabay: "whoosh transition")
- [ ] `notification.mp3` - 알림/강조 (Pixabay: "notification sound")

---

## 파일명 규칙

파일명에 키워드를 포함하면 자동으로 태그가 추론됩니다.

| 키워드 | 자동 태그 |
|--------|----------|
| heartbeat, heart | heartbeat, tension |
| tension, suspense | tension |
| breath | breathing |
| jump, scare, sudden | jumpscare |
| scream | scream |
| hit, impact | impact |
| wind | wind |
| rain | rain |
| thunder, storm | thunder |
| night, cricket | night |
| whisper, ghost | whisper |
| footstep, step | footsteps |
| door, creak | door |
| glass, break | glass |
| sad | sad |
| cry, sob | crying |
| happy | happy |
| whoosh, transition | whoosh |

### 예시
```
heartbeat_slow.mp3       → 태그: heartbeat, tension
jumpscare_sudden_01.mp3  → 태그: jumpscare
door_creak_horror.mp3    → 태그: door
```

---

## 권장 사양

| 항목 | 권장 |
|------|------|
| 포맷 | MP3 (용량 작음) 또는 WAV (고품질) |
| 샘플레이트 | 44.1kHz 이상 |
| 비트레이트 | 128kbps 이상 |
| 길이 | 짧은 효과음: 1~3초 / 배경음: 10~30초 |

---

## 효과음 등록 후 확인

```python
from core.auto_sfx import get_auto_sfx

sfx = get_auto_sfx()
stats = sfx.get_sfx_stats()

print(f"총 효과음: {stats['total_sfx']}개")
print(f"카테고리: {stats['categories']}")
```

---

## 사용 예시

```python
from core.auto_sfx import add_sfx_to_video

# 시나리오 기반 자동 효과음 추가
output = add_sfx_to_video(
    video_path="output/horror_video.mp4",
    scenario=scenario_dict,
    category="horror",
    intensity="medium"
)
```

---

## 문의

효과음 관련 문의는 이슈를 통해 남겨주세요.
