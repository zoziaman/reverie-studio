# Supertonic 3 TTS Backend

Supertonic 3 is integrated as an optional, reference-free local TTS backend.
It is especially useful for short-form production where a fixed pool of voices
is enough and fast repeatable generation matters more than custom voice cloning.

## When to Use It

- Shorts, narration, quick dialogue tests, and batch previews.
- Projects that can fit inside the built-in voice pool: `M1-M5` and `F1-F5`.
- Local/offline TTS workflows that should not require a running GPT-SoVITS server.

Use GPT-SoVITS instead when a character must keep a custom trained voice or when
reference-audio driven voice identity is required.

## Install

```bash
pip install supertonic
```

Or with the optional project extra:

```bash
pip install -e ".[supertonic]"
```

The first real synthesis can download Supertonic model assets into the local
package/model cache. Do not commit downloaded models or generated WAV files.
Prefer the project extra inside Reverie's active Python environment so Reverie's
existing dependency pins, including `numpy<2`, are still respected.

## Enable

Set this in `.env`:

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

## Voice Pool Contract

The built-in voices are:

- Male: `M1`, `M2`, `M3`, `M4`, `M5`
- Female: `F1`, `F2`, `F3`, `F4`, `F5`

Reverie maps existing `voice_type` values onto that pool:

| Reverie voice_type | Supertonic voice |
| --- | --- |
| `narrator` | `M1` |
| `grandpa` | `M2` |
| `grandma` | `F2` |
| `man`, `middle_man` | `M3` |
| `woman`, `middle_woman` | `F3` |
| `young_man` | `M4` |
| `young_woman` | `F4` |
| `child`, `girl` | `F5` |
| `boy` | `M5` |

Override any mapping with `SUPERTONIC_VOICE_MAP`. Example:

```env
SUPERTONIC_VOICE_MAP=narrator=F1,young_man=M5,young_woman=F2
```

## Shorts Tuning

The default Reverie settings use a short-form preset:

- `SUPERTONIC_TOTAL_STEPS=5`: balanced speed/quality.
- `SUPERTONIC_MAX_CHUNK_LENGTH=120`: compact Korean chunks for cleaner pacing.
- `SUPERTONIC_SILENCE_DURATION=0.25`: slightly tighter pauses for Shorts.

Raise `SUPERTONIC_TOTAL_STEPS` to `8` or `10` for slower but higher-quality
renders. Keep the lower value for quick iteration and batch preview.

## Pipeline Impact

Supertonic is not just a different audio renderer. Because it has a finite
voice pool, script generation should eventually become cast-aware:

```text
voice pool -> cast-aware script -> voice_type validation -> TTS -> subtitle timing
```

For now, this integration only adds the selectable backend and reference-free
synthesis path. It does not rewrite the story generator yet.

## Smoke Test

```bash
set TTS_ENGINE=supertonic
pytest tests/test_supertonic_tts_adapter.py
```

For a real audio test after installing `supertonic`, run a minimal script that
calls `TTSManager.generate_single_tts(...)` or run the GUI with a short test
script and `TTS_ENGINE=supertonic`.
