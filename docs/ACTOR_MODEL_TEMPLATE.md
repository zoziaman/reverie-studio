# Actor Model Template

Status: public-safe template contract

This document defines how Reverie Studio stores a reusable video-toon actor as
an asset package. It extends the active actor-pool rule in
`docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`.

The actor model package is not a generated media bundle. It is a contract for
where local users place references, variants, face parts, and QA notes after
they generate or curate their own assets.

## First Template Actor

The first template actor is:

```text
actor_adult_woman_01
```

This actor is a reusable adult Korean woman video-toon actor. The same actor can
be cast as a lead, support character, witness, neighbor, victim, office worker,
or mystery support role across different packs and episodes.

## Folder Shape

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

The public repository should keep these folders free of generated media, voice
samples, checkpoints, LoRA files, local paths, session logs, and credentials.

## actor.json

`actor.json` is the stable source of truth for one actor's identity lock,
required variants, mouth shapes, eye shapes, voice slot, and public release
boundary.

Packs may reference the actor from `settings.motiontoon.actor_pool`:

```json
{
  "actor_pool": {
    "actor_adult_woman_01": {
      "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
      "visual_identity": "adult Korean woman reusable video-toon actor",
      "voice_profile": "female_01",
      "required_variants": ["neutral_standing", "talking_standing"]
    }
  }
}
```

The pack can narrow required variants for a channel, but it should not redefine
the actor's age band, face shape, body proportions, or stable voice.

## Required Variants

The starter actor template requires:

- `neutral_standing`
- `talking_standing`
- `blink_standing`
- `happy_standing`
- `sad_standing`
- `angry_standing`
- `worried_standing`
- `scared_standing`
- `neutral_seated`
- `talking_seated`

These names are keys, not required public files. Local users can generate or
curate private images under `variants/`.

## Mouth And Eye Shapes

The early mouth-flap contract uses:

- `mouth_closed`
- `mouth_small_open`
- `mouth_wide_open`
- `mouth_round`

The early blink/expression support contract uses:

- `eyes_open`
- `eyes_closed`
- `eyes_worried`
- `eyes_angry`

Private local face-part files can be placed under `face_parts/` after the user
creates them.

## Public-Safe Boundary

The template may contain:

- JSON metadata.
- Prompt templates.
- README files.
- QA checklists.
- Empty placeholder files.

The template must not contain:

- Real generated actor images.
- Real voice samples or voice datasets.
- BGM, SFX, or channel output.
- LoRA files, checkpoints, model weights, or vendor caches.
- Local filesystem paths.
- API keys, OAuth tokens, Firebase service accounts, memory DBs, or session
  logs.

## Validation

The sample actor template is checked by `tests/test_actor_model_template.py`.
The schema is defined in `schemas/video_toon_actor_model.schema.json`.

Runtime-facing validation lives in `utils.actor_model.validate_actor_model_package`.
Pack-level validation uses `PackValidator(repo_root=...)` to verify
`settings.motiontoon.actor_pool.*.actor_model_path` references. A pack can only
request variants that exist in the actor model contract.

The public `daily_life_toon` and `mystery_toon` packs both expose
`actor_adult_woman_01` in `settings.motiontoon.actor_pool` and cast that actor
into one lead/observer slot while keeping older named actor aliases available
for compatibility.
