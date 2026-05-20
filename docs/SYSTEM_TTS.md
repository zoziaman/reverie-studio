# TTS System

Reverie Studio currently exposes two supported TTS paths:

- `sovits`: GPT-SoVITS with local voice models and reference audio.
- `supertonic`: Supertonic 3 with a local reference-free preset voice pool.

The old Qwen3 path is not exposed in the public workflow. It remains only as
legacy code until a future migration removes or replaces it with a maintained
backend.

## Environment

```env
TTS_ENGINE=sovits
TTS_HYBRID_ENABLED=false
```

To use Supertonic 3:

```env
TTS_ENGINE=supertonic
SUPERTONIC_AUTO_DOWNLOAD=true
SUPERTONIC_DEFAULT_VOICE=M1
SUPERTONIC_VOICE_MAP=narrator=M1,grandpa=M2,grandma=F2,middle_man=M3,middle_woman=F3,young_man=M4,young_woman=F4,child=F5
SUPERTONIC_TOTAL_STEPS=5
SUPERTONIC_SPEED=1.05
SUPERTONIC_MAX_CHUNK_LENGTH=120
SUPERTONIC_SILENCE_DURATION=0.25
```

## Voice Types

Supported public `voice_type` values:

- `narrator`
- `narrator_male`
- `narrator_female`
- `grandpa`
- `grandma`
- `middle_man`
- `middle_woman`
- `young_man`
- `young_woman`
- `child`

Legacy aliases such as `man`, `woman`, `old_man`, and `old_woman` are accepted
only for compatibility and are normalized before synthesis.

## Failure Policy

Reference-free engines are allowed to run without SoVITS assets. If Supertonic
is selected but synthesis fails after initialization, the TTS manager attempts a
SoVITS fallback when local SoVITS settings are available.

Hybrid TTS is disabled because the old Qwen3 branch is not an active public
backend. Keep `TTS_HYBRID_ENABLED=false`.
