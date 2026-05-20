# 렌더링 엔진 시스템

> Remotion 전용 + FFmpeg Concat
> 최종 업데이트: 2026-02-06 (v58.1.0)

---

## 개요

v57.5부터 **Remotion 전용 모드**로 전환. GPU/CPU/AUTO 선택 UI 제거됨.

---

## 렌더링 파이프라인

```
1. 본편 조립 (Remotion) → main.mp4 (~1-2분)
2. 최종 렌더링 (FFmpeg Concat) → 최종.mp4 (~2-3분)
```

---

## v57.6.1 핵심 개선

- **Remotion**: `--pixel-format=yuv420p` 추가 (재생 호환성 보장)
- **최종 렌더링**: MoviePy → FFmpeg Concat 교체 (~1시간 → ~2-3분)

---

## 성능 비교

| 단계 | 기존 (MoviePy) | 현재 (v57.6.1) | 개선 |
|------|---------------|----------------|------|
| 본편 조립 | ~4-5분 | ~1-2분 (Remotion) | 3배 빠름 |
| **최종 렌더링** | **~1시간** | **~2-3분** (FFmpeg) | **20배 빠름** |
| **총 소요시간** | **~1시간 5분** | **~5분** | **13배 빠름** |

---

## v57.5 변경사항 - Remotion 전용 모드

**GUI에서 제거된 항목**:
- 렌더링 엔진 선택 (GPU/CPU/AUTO)
- `settings_manager.py`의 `get_render_engine()` → 항상 `"remotion"` 반환

**추가된 항목**:
- 채널별 스타일 설정 (`get_channel_style()`, `set_channel_style()`)

---

## v57.6.1 변경사항 - FFmpeg Concat + 픽셀 포맷

### 1. Remotion 픽셀 포맷 수정 (`remotion_assembler.py`)

```python
cmd = [
    "npx", "remotion", "render",
    ...
    "--pixel-format=yuv420p",  # 필수! 없으면 재생 불가
]
```

### 2. 최종 렌더링 FFmpeg Concat (`media_factory.py`)

```python
# 기존: MoviePy concatenate_videoclips → write_videofile (~1시간)
# 현재: 개별 클립 내보내기 → ffmpeg_concat_videos (~2-3분)
```

### 3. 픽셀 포맷 통일 (`video_assembler.py`)

```python
def ffmpeg_concat_videos(..., reencode=True, preset="fast"):
    # reencode=True: yuv420p로 통일 (호환성 보장)
    # reencode=False: 스트림 복사 (동일 코덱 필수)
```

---

## 채널별 스타일 설정 (v57.5)

| 채널 | BGM 볼륨 | 자막 크기 | 화자명 크기 |
|------|----------|----------|------------|
| horror | 0.20 | 36 | 28 |
| senior | 0.18 | 42 | 32 |

```python
# GUI 연동
from gui.settings_manager import SettingsManager
sm = SettingsManager(config_dir)
style = sm.get_channel_style("senior")
# {'bgm_volume': 0.18, 'subtitle_size': 42, 'speaker_size': 32}
```

---

## Remotion 관련 파일

| 파일 | 역할 | v57.6.1 변경 |
|------|------|-------------|
| `remotion-poc/src/RadioDrama.tsx` | 메인 렌더링 컴포넌트 | 채널별 자막 크기 |
| `remotion-poc/src/Root.tsx` | Composition 설정 | subtitleSize, speakerSize props |
| `remotion_assembler.py` | Python-Remotion 브릿지 | `--pixel-format=yuv420p` |
| `video_assembler.py` | 영상 조립 유틸리티 | `ffmpeg_concat_videos()` 추가 |
| `media_factory.py` | 영상 제작 파이프라인 | FFmpeg Concat 최종 렌더링 |
| `settings_manager.py` | GUI 설정 | Remotion 전용, 채널 스타일 |

---

## 설정 파일

```env
# .env 파일 (v57.6.1)
RENDER_ENGINE=remotion    # 고정 (GUI에서 변경 불가)
REMOTION_CONCURRENCY=6    # 병렬 렌더링 스레드 수
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe  # 외부 FFmpeg (선택)
```

---

## 트러블슈팅

**Q: 영상이 재생 안 됨 (0x80004005 오류)**
- A: Remotion `--pixel-format=yuv420p` 누락. v57.6.1로 업데이트 필요.

**Q: 최종 렌더링이 1시간 걸림**
- A: FFmpeg Concat 미적용. `media_factory.py` v57.6.1 확인.

**Q: 클립 합칠 때 코덱 불일치 오류**
- A: `ffmpeg_concat_videos(reencode=True)` 사용 (기본값)

---

## TTS/자막 동기화 (v57.6.7)

### 문제
- `subtitle_data.start/end`: pause 미포함 (음성 길이만)
- `audio_clips`: 음성 + pause 클립 연결
- 결과: 씬이 진행될수록 자막과 음성 간격 벌어짐

### 수정

```python
subtitle_data.append({
    "start": current_time,
    "end": current_time + turn_dur,  # 음성 끝
    "scene_end": current_time + turn_dur + pause_dur,  # 씬 끝 (pause 포함)
})

# _assemble_main_remotion에서 scene_end 사용
dur_ms = int((sub.get("scene_end", sub["end"]+0.5) - sub["start"]) * 1000)
```

---

## v58.1 신규 기능

### 1. AI 제작 표기 (AI법 준수)

영상 시작 시 좌측 상단에 AI 제작 표기가 자동 표시됩니다.

```typescript
// RadioDrama.tsx
const AiDisclosure: React.FC<{ durationFrames: number }> = ({ ... }) => {
  // 페이드인 (0~15프레임) → 유지 → 페이드아웃 (마지막 15프레임)
  return (
    <div style={{ position: "absolute", top: 30, left: 30, opacity, zIndex: 100 }}>
      <div style={{ color: "rgba(255, 255, 255, 0.85)", fontSize: 18, ... }}>
        이 영상은 AI로 제작되었습니다
      </div>
    </div>
  );
};
```

**RemotionAssembler 파라미터:**
- `show_ai_disclosure`: AI 표기 표시 여부 (기본: True)
- `ai_disclosure_duration`: 표시 시간 초 (기본: 3.0)

### 2. 자막 강조 효과

중요 대사에 `★★★` 마커 추가 시 자동 강조 처리됩니다.

```typescript
// RadioDrama.tsx
const isHighlighted = text.includes("★★★") || text.includes("★");
const displayText = text.replace(/★+/g, "").trim();

// 강조 효과
color: isHighlighted ? "#FF4444" : "white",
fontSize: isHighlighted ? subtitleSize * 1.1 : subtitleSize,
backgroundColor: isHighlighted ? "rgba(60,0,0,0.8)" : "rgba(0,0,0,0.6)",
border: isHighlighted ? "2px solid rgba(255,68,68,0.6)" : "none",
```

### 3. TTS 볼륨 증폭

기존 2.5배 → 3.0배로 증폭되어 BGM 대비 음성이 더 명확합니다.

```typescript
// RadioDrama.tsx
<Audio src={getAssetPath(audio.path)} volume={ttsVolume} />  // 기본 3.0
```

**RemotionAssembler 파라미터:**
- `tts_volume`: TTS 볼륨 배수 (기본: 3.0)
