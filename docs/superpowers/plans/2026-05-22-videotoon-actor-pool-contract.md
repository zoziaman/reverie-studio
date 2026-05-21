# Video-Toon Actor Pool Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot video-toon consistency from scene-by-scene character generation to a pack-level actor pool with episode-level role casting.

**Architecture:** Keep existing video-toon rendering code intact and add a contract layer above it. Packs define stable actors; episodes map temporary roles to those actors; scenes reference `actor_id` rather than asking image generation to invent new lead characters.

**Tech Stack:** Python 3.10, existing `PackValidator`, pytest, JSON Schema documentation.

---

## File Structure

- Modify `src/config/pack_validator.py`: validate `motiontoon.actor_pool`, `motiontoon.role_casting_contract`, and `cast_slots.*.actor_id`.
- Modify `src/config/pack_config.py`: preserve actor-pool fields when loading motiontoon settings.
- Modify `src/config/pack_models.py`: carry actor-pool fields on `MotiontoonConfig`.
- Modify `src/modules_pro/videotoon_local.py`: carry `role_id`, `actor_id`, `emotion`, `shot_type`, and `motion_preset` into storyboard/generation requests.
- Modify `src/utils/motiontoon.py`: preserve actor-pool fields when normalizing motiontoon config.
- Create `src/utils/videotoon_contract.py`: validate episode role casting and scene-level actor references.
- Modify `tests/test_pack_validator.py`: cover valid actor pools, invalid missing actors, invalid missing visual identity, and legacy warnings.
- Modify `tests/test_motiontoon_scene_type.py`: cover normalization of actor-pool contract fields.
- Modify `tests/test_videotoon_contract.py`: cover episode casting and scene reference validation.
- Modify `tests/test_videotoon_local.py`: cover scene specs carrying actor contract fields.
- Modify `tests/test_visual_storytelling_config.py`: cover motiontoon config preserving actor-pool fields.
- Create `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`: public-facing rule document.
- Create `schemas/video_toon_actor_pool.schema.json`: actor-pool shape.
- Create `schemas/video_toon_episode_cast.schema.json`: episode role-casting and scene reference shape.

### Task 1: Preserve Actor-Pool Fields

**Files:**
- Modify: `src/utils/motiontoon.py`
- Test: `tests/test_motiontoon_scene_type.py`

- [x] **Step 1: Write the failing test**

```python
def test_normalize_motiontoon_config_preserves_actor_pool_contract():
    config = normalize_motiontoon_config(
        {
            "enabled": True,
            "actor_pool": {"actor_woman_01": {"visual_identity": "recurring woman actor"}},
            "role_casting_contract": {"enabled": True, "strict_actor_refs": True},
        }
    )

    assert config["actor_pool"]["actor_woman_01"]["visual_identity"] == "recurring woman actor"
    assert config["role_casting_contract"]["strict_actor_refs"] is True
```

- [x] **Step 2: Implement normalized fields**

Add these keys to the `normalize_motiontoon_config` return value:

```python
"actor_pool": _coerce_dict(data.get("actor_pool")),
"role_casting_contract": _coerce_dict(data.get("role_casting_contract")),
```

- [x] **Step 3: Run focused test**

Run: `pytest tests/test_motiontoon_scene_type.py -q`
Expected: all tests pass.

### Task 2: Validate Actor Pool And Role Casting

**Files:**
- Modify: `src/config/pack_validator.py`
- Test: `tests/test_pack_validator.py`

- [x] **Step 1: Add validator tests**

Cover:

```python
def test_pack_validator_accepts_actor_pool_role_casting_contract(): ...
def test_pack_validator_rejects_cast_slot_actor_missing_from_pool(): ...
def test_pack_validator_rejects_actor_without_visual_identity(): ...
def test_pack_validator_warns_for_legacy_videotoon_cast_without_actor_pool(): ...
```

- [x] **Step 2: Add validator implementation**

Add helper methods:

```python
def _known_visual_character_ids(self, visual_storytelling): ...
def _validate_actor_pool(self, actor_pool, visual_storytelling=None): ...
def _validate_role_casting_contract(self, contract): ...
```

Update `_validate_motiontoon()` so `cast_slots` can use `actor_id` and so missing actor references fail when `actor_pool` is present.

- [x] **Step 3: Run focused test**

Run: `pytest tests/test_pack_validator.py -q`
Expected: all tests pass.

### Task 3: Document The Contract

**Files:**
- Create: `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`
- Create: `schemas/video_toon_actor_pool.schema.json`
- Create: `schemas/video_toon_episode_cast.schema.json`

- [x] **Step 1: Add public design rule**

Document:

```text
actor_id = fixed visual identity, voice profile, sprite sheet, motion profile
role_id = episode-specific story function
scene_id = shot-level use of an actor in a role
```

- [x] **Step 2: Add schemas**

Create JSON schemas for actor pools and episode role casting so future agents can build against a stable shape.

- [x] **Step 3: Verify docs are discoverable**

Run: `rg -n "actor_pool|role_casting_contract|Video-Toon Actor Pool" docs schemas src tests`
Expected: contract, schemas, validator, and tests are all visible.

### Task 4: Verification

**Files:**
- All modified files.

- [x] **Step 1: Run focused pytest**

Run:

```bash
pytest tests/test_pack_validator.py tests/test_motiontoon_scene_type.py -q
```

Expected: all tests pass.

- [x] **Step 2: Check diff**

Run:

```bash
git diff --stat
git status --short
```

Expected: only docs, schemas, actor-pool validators, motiontoon config loading, VideoToon scene-contract fields, and tests changed.

### Task 5: Episode Role Casting Validator

**Files:**
- Create: `src/utils/videotoon_contract.py`
- Create: `tests/test_videotoon_contract.py`
- Modify: `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`

- [x] **Step 1: Add episode contract validator**

Create:

```python
def validate_episode_actor_contract(episode, actor_pool, *, assignment_key="role_casting", strict_actor_refs=True, allow_background_extras=True, required_scene_fields=None):
    ...
```

It must reject unknown actors, unknown roles, missing scene fields, and scenes where `actor_id` does not match the role-casting table.

- [x] **Step 2: Add tests for valid and invalid episode casting**

Run: `pytest tests/test_videotoon_contract.py -q`
Expected: all tests pass.

### Task 6: Carry Actor References Into VideoToon Scene Specs

**Files:**
- Modify: `src/modules_pro/videotoon_local.py`
- Modify: `tests/test_videotoon_local.py`

- [x] **Step 1: Add scene spec fields**

Add `role_id`, `actor_id`, `emotion`, `shot_type`, `motion_preset`, and `is_background_extra` to `VideoToonSceneSpec`.

- [x] **Step 2: Add build_scene_specs_from_production role casting**

Add optional `role_casting` input and use it to resolve `actor_id` from script/image prompt roles.

- [x] **Step 3: Add tests**

Run: `pytest tests/test_videotoon_local.py -q`
Expected: all tests pass.

### Task 7: Preserve Actor Pool Through Pack Config Loading

**Files:**
- Modify: `src/config/pack_models.py`
- Modify: `src/config/pack_config.py`
- Modify: `tests/test_visual_storytelling_config.py`

- [x] **Step 1: Add fields to MotiontoonConfig**

Add:

```python
actor_pool: Dict[str, Dict[str, Any]] = field(default_factory=dict)
role_casting_contract: Dict[str, Any] = field(default_factory=dict)
```

- [x] **Step 2: Preserve fields while loading and cloning**

Update `_load_motiontoon_config`, `_clone_motiontoon_config`, and fallback `get_motiontoon_config` construction.

- [x] **Step 3: Verify**

Run: `pytest tests/test_visual_storytelling_config.py -q`
Expected: all tests pass.

### Task 8: Enforce Contract At Bundle Boundary

**Files:**
- Modify: `src/modules_pro/videotoon_local.py`
- Modify: `tests/test_videotoon_local.py`
- Modify: `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`

- [x] **Step 1: Add optional validation to write_production_bundle**

Add optional keyword arguments:

```python
actor_pool: Optional[Dict[str, Any]] = None
role_casting: Optional[Dict[str, str]] = None
validate_actor_contract: bool = False
```

When actor pool or role casting data is provided, validate before writing generation requests.

- [x] **Step 2: Record validation in the manifest**

Add `actor_contract_validation` with `is_valid`, `errors`, `warnings`, `role_count`, and `scene_count`.

- [x] **Step 3: Reject mismatches**

Raise `ValueError` when a scene's `actor_id` does not match the episode role-casting table.

- [x] **Step 4: Verify**

Run: `pytest tests/test_videotoon_local.py tests/test_videotoon_contract.py -q`
Expected: all tests pass.

### Task 9: Demote ControlNet/IP-Adapter To Optional Variant Support

**Files:**
- Modify: `src/modules_pro/videotoon_local.py`
- Modify: `tests/test_videotoon_local.py`
- Modify: `docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md`

- [x] **Step 1: Add actor-pool-first request metadata**

Generation requests now include:

```json
{
  "identity_source": "actor_pool",
  "identity_contract": {
    "role_id": "victim",
    "actor_id": "actor_woman_01",
    "emotion": "fear"
  }
}
```

- [x] **Step 2: Re-label ControlNet/IP-Adapter as optional support**

Generation requests use:

```json
{
  "character_reference_mode": "actor_pool_optional_ip_adapter",
  "pose_control_mode": "optional_controlnet_openpose_sd15",
  "depth_control_mode": "optional_controlnet_depth_sd15",
  "variant_generation_support": {
    "mode": "optional_missing_variant_generation"
  }
}
```

- [x] **Step 3: Verify**

Run: `pytest tests/test_videotoon_local.py -q`
Expected: all tests pass.

### Task 10: Migrate Public Video-Toon Packs And Factory Wiring

**Files:**
- Modify: `assets/packs/daily_life_toon/settings.json`
- Modify: `assets/packs/mystery_toon/settings.json`
- Modify: `src/pipeline/orchestrator.py`
- Modify: `src/utils/videotoon_contract.py`
- Modify: `tests/test_pack_validator.py`
- Modify: `tests/test_videotoon_contract.py`
- Modify: `tests/test_videotoon_local.py`

- [x] **Step 1: Add actor pools to public video-toon packs**

Add `motiontoon.actor_pool`, `motiontoon.role_casting_contract`, and `cast_slots.*.actor_id` while preserving legacy `character_id`.

- [x] **Step 2: Expand cast slot aliases into role casting**

`role_casting_from_motiontoon_slots(...)` maps both slot names and slot aliases to the chosen `actor_id`.

- [x] **Step 3: Wire MediaFactory to the active pack contract**

`_write_videotoon_production_bundle(...)` reads `get_motiontoon_config()`, passes role casting into `build_scene_specs_from_production(...)`, and passes `actor_pool` / `role_casting` into `write_production_bundle(...)`.

- [x] **Step 4: Verify**

Run: `pytest tests/test_pack_validator.py tests/test_videotoon_contract.py tests/test_videotoon_local.py -q`
Expected: all tests pass.
