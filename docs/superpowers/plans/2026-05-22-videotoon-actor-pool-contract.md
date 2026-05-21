# Video-Toon Actor Pool Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pivot video-toon consistency from scene-by-scene character generation to a pack-level actor pool with episode-level role casting.

**Architecture:** Keep existing video-toon rendering code intact and add a contract layer above it. Packs define stable actors; episodes map temporary roles to those actors; scenes reference `actor_id` rather than asking image generation to invent new lead characters.

**Tech Stack:** Python 3.10, existing `PackValidator`, pytest, JSON Schema documentation.

---

## File Structure

- Modify `src/config/pack_validator.py`: validate `motiontoon.actor_pool`, `motiontoon.role_casting_contract`, and `cast_slots.*.actor_id`.
- Modify `src/utils/motiontoon.py`: preserve actor-pool fields when normalizing motiontoon config.
- Modify `tests/test_pack_validator.py`: cover valid actor pools, invalid missing actors, invalid missing visual identity, and legacy warnings.
- Modify `tests/test_motiontoon_scene_type.py`: cover normalization of actor-pool contract fields.
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

Expected: only docs, schemas, validator, motiontoon config normalization, and tests changed.
