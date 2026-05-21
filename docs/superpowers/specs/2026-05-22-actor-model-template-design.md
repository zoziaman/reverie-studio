# Actor Model Template Design

Status: draft for user review

This spec defines the first reusable video-toon actor model template for Reverie
Studio. It does not add runtime generation, bundled media, model weights, LoRA
files, voice datasets, or private channel output. It defines the public-safe
asset contract that later implementation can turn into files, validators, and
pack references.

## Objective

Create a single reusable actor model template that can be used across many
Reverie packs and story genres. The first target actor is:

```text
actor_adult_woman_01
```

This actor is a generic adult Korean woman video-toon actor intended for broad
testing across daily-life, mystery, scam-alert, witness, neighbor, lead,
support, and victim roles. The actor identity stays fixed. Episode roles may
change.

## Current Repo Context

The current video-toon contract already defines:

- `actor_id` as the stable visual identity, voice profile, sprite sheet, and
  motion profile.
- `role_id` as the episode-specific story function.
- `scene_id` as the shot-level use of an actor in a role.
- `settings.motiontoon.actor_pool` as the pack-level place where reusable
  actors are declared.
- `role_casting` as the episode-level mapping from temporary story role to
  fixed actor.

The missing layer is an actor model package: a reusable folder contract for the
actor's identity lock, prompt templates, required variants, mouth shapes, eye
shapes, and QA checklist.

## Non-Goals

This template must not:

- Bundle real generated actor images.
- Bundle voice samples, voice datasets, BGM, SFX, LoRA files, checkpoints, or
  model weights.
- Claim that the actor is production-ready.
- Add automatic image generation or TTS generation.
- Add private local paths, credentials, OAuth data, Firebase files, session
  logs, memory DBs, or generated channel output.

## Recommended Approach

Use an independent actor model asset package. Packs reference it from
`actor_pool` instead of duplicating actor details inside every pack.

Rejected alternatives:

- Only expanding `actor_pool` fields is too cramped once many actors and genres
  exist.
- Building an actor factory now is too early because image generation, LoRA,
  ControlNet, TTS, and QA would all become coupled before the asset contract is
  stable.

## Target Public-Safe Folder

The implementation should create this starter package:

```text
assets/actor_models/actor_adult_woman_01/
  actor.json
  prompts/
    identity_prompt.txt
    variant_prompt.txt
    mouth_prompt.txt
    negative_prompt.txt
  references/
    README.md
    .gitkeep
  variants/
    .gitkeep
  face_parts/
    .gitkeep
  qa/
    actor_model_checklist.md
```

The folders are intentionally empty of real media. They define where private
or user-generated assets should be placed in a local clone.

## Actor Contract

`actor.json` should contain:

```json
{
  "actor_id": "actor_adult_woman_01",
  "display_name": "Adult Woman Actor 01",
  "template_version": "actor_model_template_v1",
  "readiness_state": "template",
  "age_band": "adult",
  "gender_presentation": "woman",
  "role_range": [
    "lead",
    "support",
    "victim",
    "witness",
    "neighbor",
    "office_worker",
    "mystery_support"
  ],
  "identity_lock": {
    "face_shape": "consistent adult Korean woman face shape",
    "hair": "short or medium neat dark hair, fixed per generated actor",
    "body_type": "ordinary adult proportions, half-body video-toon friendly",
    "signature_clothing": "simple modern cardigan or blouse silhouette",
    "must_not_change": [
      "age band",
      "face shape",
      "hair silhouette",
      "body proportions",
      "primary clothing silhouette"
    ]
  },
  "style_contract": {
    "visual_style": "clean Korean webtoon video-toon cutout",
    "line_quality": "clean line art",
    "rendering": "cel-shaded, readable expression",
    "framing": "waist-up or half-body, centered for layered compositing"
  },
  "required_variants": [
    "neutral_standing",
    "talking_standing",
    "blink_standing",
    "happy_standing",
    "sad_standing",
    "angry_standing",
    "worried_standing",
    "scared_standing",
    "neutral_seated",
    "talking_seated"
  ],
  "mouth_shapes": [
    "mouth_closed",
    "mouth_small_open",
    "mouth_wide_open",
    "mouth_round"
  ],
  "eye_shapes": [
    "eyes_open",
    "eyes_closed",
    "eyes_worried",
    "eyes_angry"
  ],
  "voice_profile": {
    "recommended_slot": "female_01",
    "stable_voice_required": true
  },
  "public_release_boundary": {
    "contains_real_actor_media": false,
    "contains_voice_samples": false,
    "contains_model_weights": false,
    "contains_private_paths": false
  }
}
```

## Pack Reference Shape

A future pack can reference the actor model from `settings.motiontoon.actor_pool`:

```json
{
  "actor_pool": {
    "actor_adult_woman_01": {
      "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
      "visual_identity": "adult Korean woman reusable video-toon actor",
      "voice_profile": "female_01",
      "required_variants": [
        "neutral_standing",
        "talking_standing",
        "worried_standing"
      ]
    }
  }
}
```

The actor model is the full source of identity requirements. The pack-level
entry may narrow the required variants for a specific pack, but it should not
silently redefine the actor's face, age band, body type, or default voice.

## Prompt Templates

The prompt files should be reusable instructions, not final generated prompts.

`identity_prompt.txt` should define the stable actor identity and the traits
that must not drift.

`variant_prompt.txt` should define how to request each expression or pose while
keeping the same actor identity.

`mouth_prompt.txt` should define the four mouth shapes used by early mouth-flap
assembly.

`negative_prompt.txt` should block common identity drift such as age changes,
face changes, outfit replacement, extra people, UI overlays, unreadable text,
cropped head, or full-body composition when half-body is required.

## Validation Plan

Add `schemas/video_toon_actor_model.schema.json` with these requirements:

- `actor_id` is required and non-empty.
- `template_version` is required.
- `readiness_state` is one of `template`, `draft`, `ready_for_test`,
  `approved`, or `retired`.
- `identity_lock` is required.
- `required_variants` is a non-empty string array.
- `mouth_shapes` is a non-empty string array.
- `eye_shapes` is a non-empty string array.
- `public_release_boundary` is required and must state that the template has no
  real actor media, no voice samples, no model weights, and no private paths.

Add `tests/test_actor_model_template.py` to verify:

- The schema exists.
- The sample actor package exists.
- `actor.json` parses as JSON.
- Folder name matches `actor_id`.
- Required variants, mouth shapes, and eye shapes are present.
- Prompt files exist.
- Public template folders do not contain generated media files.

## Implementation Work Units

1. Add `docs/ACTOR_MODEL_TEMPLATE.md`.
2. Add `schemas/video_toon_actor_model.schema.json`.
3. Add `assets/actor_models/actor_adult_woman_01/actor.json`.
4. Add the four prompt template files.
5. Add placeholder `.gitkeep` files under `references`, `variants`, and
   `face_parts`.
6. Add `qa/actor_model_checklist.md`.
7. Add `tests/test_actor_model_template.py`.
8. Run the new test plus existing video-toon tests:

```text
pytest tests/test_actor_model_template.py tests/test_pack_validator.py tests/test_videotoon_contract.py -q
```

## Acceptance Criteria

The goal is ready for implementation when the user approves this design. The
implementation is complete only when:

- The actor model design is documented.
- The public-safe sample actor package exists.
- The sample contains no real media or private runtime artifacts.
- The schema and tests prove the contract shape.
- Existing actor-pool behavior remains compatible.

## Review Gate

User approval is required before creating the actor model files, schema, tests,
or package folders.
