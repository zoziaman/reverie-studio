# Video-Toon Actor Pool Contract

Status: active design rule

Reverie Studio video-toon packs should not rely on scene-by-scene character generation as the primary way to preserve character consistency. The stable unit is a pack-level actor pool. Episodes assign those fixed actors to temporary story roles.

## Rule

Use this model for video-toon packs:

```text
actor_id = fixed visual identity, voice profile, sprite sheet, motion profile
role_id = episode-specific story function
scene_id = shot-level use of an actor in a role
```

The same actor can play different roles in different omnibus episodes. The actor's face, body language, palette, and voice should remain stable. The role, motivation, relationships, and emotional arc can change per episode.

## Why This Replaces The Old Approach

The older consistency approach tried to keep characters stable through prompts, fixed seeds, ControlNet, or IP-Adapter while each scene still asked the image backend to invent a person. That is brittle.

This contract moves identity upstream:

1. Create or import the actor pool for the pack.
2. Audit the actor pool before episode production.
3. Cast actors into episode roles.
4. Build scene and shot plans that reference actor_id.
5. Use ControlNet, IP-Adapter, or ComfyUI only to generate missing actor variants, not as the primary runtime consistency mechanism.

## Pack-Level Actor Pool

`settings.motiontoon.actor_pool` defines reusable actors for the pack.

```json
{
  "motiontoon": {
    "enabled": true,
    "video_toon_local_enabled": true,
    "actor_pool": {
      "actor_woman_01": {
        "character_id": "actor_woman_01",
        "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
        "visual_identity": "sharp-eyed recurring woman actor with short black hair",
        "voice_profile": "female_01",
        "required_variants": ["neutral_front", "fear_front", "talking_front"],
        "sprite_sheet": {
          "neutral_front": "assets/characters/actor_woman_01/neutral_front.png",
          "fear_front": "assets/characters/actor_woman_01/fear_front.png",
          "talking_front": "assets/characters/actor_woman_01/talking_front.png"
        }
      }
    }
  }
}
```

Minimum fields:

- `visual_identity`: Required. Short human-readable lock on the actor's stable look.
- `actor_model_path`: Optional but recommended. Relative path to the reusable actor model package contract.
- `character_id`: Optional bridge to existing `visual_storytelling.characters`.
- `voice_profile`: Optional but recommended. Keeps the same face tied to the same voice.
- `required_variants`: Optional list of sprite or expression keys needed before production.
- `sprite_sheet`: Optional map from variant key to local asset path.

## Episode-Level Role Casting

Episodes should cast actors into roles. The role can change per episode; the actor stays stable.

```json
{
  "episode_id": "used_market_scam",
  "role_casting": {
    "scammer": "actor_man_01",
    "victim": "actor_woman_01",
    "witness": "actor_elder_01"
  }
}
```

Recommended rule: keep the actor's voice stable unless the story explicitly treats the actor as disguised or distorted.

## Scene-Level Shot Contract

Generated or planned scenes should reference actors, not free-form new people.

```json
{
  "scene_id": "s014",
  "role_id": "victim",
  "actor_id": "actor_woman_01",
  "emotion": "fear",
  "pose": "front",
  "shot_type": "medium_close",
  "background_id": "apartment_night_01",
  "motion_preset": "slow_push"
}
```

If a scene needs an anonymous crowd or background extra, mark it as an extra and do not let it become a recurring main role.

## Validator Boundary

The pack validator now accepts and checks:

- `settings.motiontoon.actor_pool`
- `settings.motiontoon.role_casting_contract`
- `settings.motiontoon.cast_slots.*.actor_id`

Legacy `character_id` slots are still accepted for older packs. New video-toon packs should move toward `actor_id`.

Episode and scene validation lives in `utils.videotoon_contract`:

- `role_casting_from_motiontoon_slots(...)` converts pack slots into an episode role-casting table.
- `validate_episode_actor_contract(...)` checks that episode roles point to known actors and that scenes do not drift away from the assigned actor.
- `scene_dicts_from_specs(...)` extracts validation fields from `VideoToonSceneSpec` objects.

`VideoToonSceneSpec` carries `role_id`, `actor_id`, `emotion`, `shot_type`, and `motion_preset` into the generation request and storyboard JSON. This keeps the production bundle aligned with the actor-pool contract before image generation begins.

`VideoToonLocalWorkspace.write_production_bundle(...)` can enforce this contract before any generation request is written. Pass `actor_pool` and `role_casting` to record `actor_contract_validation` in the bundle manifest. A mismatch raises `ValueError` before the run reaches ComfyUI or SD WebUI.

Generation requests now expose `identity_source`, `identity_contract`, and `variant_generation_support`. When `actor_id` is present, the identity source is `actor_pool`; IP-Adapter and ControlNet are marked as optional support for missing pose, depth, or face-reference variants.

`reverie-actor-model-requests episode-asset-plan ...` can be used as a
preflight between episode planning and rendering. It reads a roster plan plus an
episode JSON, validates role-to-actor references, and maps each scene to the
fixed actor variant, mouth layer, and eye layer expected by the actor model
package. Missing scene variants are reported before image generation begins.
Use `episode-asset-coverage` as the broad render-readiness gate: it verifies
each scene's fixed actor variant, mouth layer, and eye layer exist locally.
Use `episode-variant-requests` to convert those missing variants into
deduplicated local generation requests without mutating the public actor
package contract.
Use `episode-variant-coverage` after local generation to verify those
supplemental `variants/*.png` files exist before rendering the episode.
Use `episode-variant-promotions` only when a generated supplemental variant
should become a durable actor-model requirement; it writes a reviewable plan
instead of mutating `actor.json` automatically.
Use `apply-episode-variant-promotions` only after that review to update the
local actor package's `required_variants`; generated media still remains a
local asset and should not be committed by default.

Background plates follow the same public-safe asset rule. Pack
`background_library.location_templates` can be expanded with
`reverie-background-library-requests asset-requests ...` into
`reverie.background_library.asset_requests.v1`, then checked with
`reverie-background-library-requests coverage ...` before rendering. See
`docs/BACKGROUND_ASSET_TEMPLATE.md` for the background request and coverage
contract.

Use `reverie-videotoon-preflight episode ...` after actor episode asset
coverage and background asset coverage are both written. For real episode
rendering, use `reverie-background-library-requests episode-asset-requests ...`
followed by `reverie-background-library-requests episode-coverage ...` so the
background gate requests and checks only the locations referenced by that
episode's scenes. Preflight combines both reports into
`reverie.pack.videotoon_episode_preflight.v1` and should be the final local
render gate before assembling a video-toon episode.

The production orchestrator derives role casting from `motiontoon.cast_slots`, including slot aliases, and passes the active pack's `actor_pool` into the VideoToon bundle writer. Public `daily_life_toon` and `mystery_toon` settings include actor pools and role-casting contracts.

`PackValidator(repo_root=...)` validates `actor_model_path` when it is present.
It checks that the referenced actor model package exists, remains inside the
repository root, keeps public-safe boundaries, matches the actor pool key, and
contains every pack-level `required_variants` entry requested by that actor.

## Target Video-Toon Grammar

The target is not full animation first. The reliable MVP is:

- fixed actor cutouts
- reusable expression or pose variants
- background plates that can change per episode
- camera moves such as slow push, snap zoom, shake, black hold, and flash
- prop closeups and evidence overlays
- subtitles and timing that carry the rhythm

Full mouth flap, blinking, and detailed puppet motion are useful later. They should not block the core actor-pool contract.
