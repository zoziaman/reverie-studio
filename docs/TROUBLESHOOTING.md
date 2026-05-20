# Reverie Studio 트러블슈팅 가이드

> 반복되는 이슈와 해결법을 기록합니다.
> Claude 컨텍스트가 날아가도 이 문서를 참조하면 됩니다.

---

## 🚨 핵심 설계 원칙 (절대 위반 금지!)

### 1. MoviePy 사용 금지
- **이유**: MoviePy는 **존나 느림**. CPU 기반이라 렌더링에 1시간+ 걸림
- **대안**: FFmpeg + GPU (NVENC) 사용 → 2-3분 렌더링
- **예외**: 없음. 어떤 상황에서도 MoviePy로 영상 렌더링하지 말 것

### 2. 렌더링 파이프라인
```
Remotion (자막 + 이미지 + 오디오)
    ↓
FFmpeg concat (NVENC GPU 인코딩)
    ↓
최종 영상
```
- Remotion이 **모든 것을 처리** (자막, 이미지, TTS 오디오, BGM)
- FFmpeg는 **합치기만** (hook + intro + main + outro)
- **중간에 MoviePy 끼어들면 안 됨!**

### 3. 볼륨 처리
- **YouTube 권장 볼륨**: -14 LUFS (mean: -14~-16 dB)
- **TTS 볼륨 증폭**: FFmpeg `-af "volume=XdB"` 필터로 처리
- **볼륨 증폭 위치**: `ffmpeg_concat_videos()` 함수에서 처리

---

## 목차

1. [TTS 볼륨이 작게 나오는 문제](#1-tts-볼륨이-작게-나오는-문제)
2. [FFmpeg concat 관련](#2-ffmpeg-concat-관련)
3. [SoVITS TTS 관련](#3-sovits-tts-관련)
4. [Remotion 렌더링 관련](#4-remotion-렌더링-관련)
5. [GPU/CUDA 관련](#5-gpucuda-관련)

---

## 1. TTS 볼륨이 작게 나오는 문제

### 증상
- 영상 생성 후 TTS 음성이 너무 작음
- BGM에 묻혀서 대사가 안 들림
- "소리가 또 줄었네?" 같은 피드백

### YouTube 권장 볼륨
| 항목 | 권장값 |
|------|--------|
| Loudness | **-14 LUFS** |
| True Peak | **-1 dB** |
| Mean Volume | **-14 ~ -16 dB** |

### 현재 상태 vs 목표
| 상태 | Mean Volume | 비고 |
|------|-------------|------|
| TTS 원본 wav | -18.5 dB | SoVITS 출력 |
| 최종 영상 | -34.9 dB | 너무 작음! |
| **목표** | **-14 dB** | YouTube 권장 |

### 해결 방법

**FFmpeg concat에서 볼륨 필터 추가:**
```python
# video_assembler.py ffmpeg_concat_videos() 수정
cmd = [
    ffmpeg_path,
    "-y",
    "-f", "concat",
    "-safe", "0",
    "-i", list_file.name,
    "-c:v", "h264_nvenc",
    "-preset", "p4",
    "-cq", "18",
    "-pix_fmt", "yuv420p",
    "-af", "loudnorm=I=-14:TP=-1:LRA=11",  # YouTube 권장 볼륨으로 정규화
    "-c:a", "aac",
    "-b:a", "192k",
    output_path
]
```

**loudnorm 필터 설명:**
- `I=-14`: 목표 Integrated Loudness (-14 LUFS)
- `TP=-1`: True Peak 제한 (-1 dB, 클리핑 방지)
- `LRA=11`: Loudness Range (다이나믹 레인지)

### 히스토리
- 2026-02-07: 야간 배치 테스트 후 볼륨 이슈 재발견
- **원인**: MoviePy 코드가 잘못 끼어들어서 볼륨 손실
- **교훈**: MoviePy 절대 쓰지 말 것!
- 2026-02-07: v58.3.5 - TTS 소스 단계 증폭으로 최종 해결
  - `media_factory._amplify_tts_volume()` 메서드 추가
  - FFmpeg loudnorm 필터로 TTS WAV 파일을 -14 LUFS로 정규화
  - `video_assembler.py`에서 volume 필터 제거 (소스에서 이미 증폭됨)
  - **베리즈 권장**: 소스 단계 증폭이 가장 깔끔함

---

## 2. FFmpeg concat 관련

### 픽셀 포맷 불일치 (v57.6.1에서 해결됨)
- **증상**: concat 시 영상 깨짐, 색상 이상
- **원인**: 입력 영상들의 픽셀 포맷(yuv420p, yuv444p 등)이 다름
- **해결**: `reencode=True`로 재인코딩 + `-pix_fmt yuv420p` 통일

### GPU 인코딩 실패
- **증상**: `h264_nvenc` 코덱 에러
- **원인**: NVIDIA GPU 없거나 드라이버 문제
- **해결**: `h264_nvenc` → `libx264`로 폴백

---

## 3. SoVITS TTS 관련

### 모델 폴더 구조
```
assets/models/sovits/
├── narrator_male/     # 남성 나레이터 (narrator voice_type용)
├── narrator_female/   # 여성 나레이터
├── man/              # 남자 캐릭터
├── woman/            # 여자 캐릭터
├── young_man/        # 청년
├── young_woman/      # 젊은 여성
├── grandma/          # 할머니
└── grandpa/          # 할아버지
```

### voice_type 매핑 규칙
| voice_type | 모델 폴더 |
|------------|----------|
| narrator | narrator_male 또는 narrator_female (랜덤/설정) |
| man | man |
| woman | woman |
| young_man | young_man |
| young_woman | young_woman |
| grandma | grandma |
| grandpa | grandpa |

---

## 4. Remotion 렌더링 관련

### Remotion의 역할 (v58+)
Remotion이 **본편 전체**를 렌더링:
- 이미지 시퀀스 (Ken Burns 효과)
- 자막 (speaker 색상 포함)
- TTS 오디오 (개별 세그먼트)
- BGM 믹싱 (페이드인/아웃)
- AI 제작 표기

### Props 전달 확인
```
remotion-poc/src/RadioDrama.tsx
- audioSegments: TTS 오디오 세그먼트 배열
- ttsVolume: TTS 볼륨 (기본 1.0, 증폭은 FFmpeg에서)
- bgmVolume: BGM 볼륨 (채널별 다름)
- showAiDisclosure: AI 제작 표기 여부
```

### 중요: Remotion 후 MoviePy 사용 금지!
```
❌ 잘못된 방식:
Remotion 렌더링 → MoviePy로 오디오 덮어쓰기 → FFmpeg concat

✅ 올바른 방식:
Remotion 렌더링 (오디오 포함) → FFmpeg concat (볼륨 정규화)
```

---

## 5. GPU/CUDA 관련

### VRAM 부족
- **증상**: CUDA out of memory
- **해결**:
  - SD WebUI 설정에서 배치 사이즈 줄이기
  - `--medvram` 또는 `--lowvram` 옵션
  - SoVITS와 SD 동시 실행 피하기

### NVENC 세션 제한
- **증상**: "too many NVENC sessions" 에러
- **원인**: NVIDIA 소비자용 GPU는 동시 NVENC 세션 3개 제한
- **해결**: 병렬 렌더링 수 줄이기 (`concurrency` 파라미터)

---

## 추가 이슈 발생 시

1. 이 문서에 추가
2. 베리즈(NotebookLM)에 소스 추가로 동기화
3. 관련 코드 위치 명시
4. 해결 방법 + 히스토리 기록

