"""v63: 장면 블로킹 — 캐릭터 시선 방향(facing) 자동 결정.

영상툰 채널들은 캐릭터가 서로 마주보거나 정면을 보는 '블로킹'이 자연스럽다.
이 모듈은 장면의 등장인물/화자 정보로부터 각 캐릭터의 facing(front/left/right/back)을
규칙 기반으로 정한다. 순수 함수라 단위 테스트로 완전 검증 가능.

규칙(초안):
- 1인 또는 나레이션/독백 → 모두 front
- 2인 대화 → 서로 마주봄: 좌측 인물 right, 우측 인물 left (180도 규칙: 이전 장면 facing 유지)
- 3인+ → 화자 front, 나머지 left/right 교대
- 퇴장/돌아섬(exit/leave) → back
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

VALID_FACINGS = ("front", "left", "right", "back")
_NARRATION_SCENE_TYPES = {"narration", "monologue", "voiceover", "내레이션", "독백"}
_EXIT_SCENE_TYPES = {"exit", "leave", "turn_away", "퇴장", "돌아섬"}


def normalize_facing(value: Any) -> str:
    """임의 값을 유효한 facing으로 정규화 (기본 front)."""
    v = str(value or "front").strip().lower()
    return v if v in VALID_FACINGS else "front"


def _char_id(char: Any) -> str:
    if isinstance(char, Mapping):
        return str(char.get("id") or char.get("name") or char.get("role_id") or "")
    return str(getattr(char, "id", "") or getattr(char, "name", "") or getattr(char, "role_id", "") or "")


def _is_speaker(char: Any) -> bool:
    if isinstance(char, Mapping):
        return bool(char.get("is_speaker", False))
    return bool(getattr(char, "is_speaker", False))


def assign_scene_facings(
    characters: Sequence[Any],
    *,
    scene_type: str = "dialogue",
    previous_facings: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """장면 등장인물별 facing을 결정해 {char_id: facing}로 반환.

    previous_facings: 직전 장면의 {char_id: facing}. 같은 인물은 가능한 한 유지(180도 규칙).
    """
    prev = {str(k): normalize_facing(v) for k, v in (previous_facings or {}).items()}
    ids: List[str] = [cid for cid in (_char_id(c) for c in characters) if cid]
    # 중복 제거(순서 유지)
    seen: set[str] = set()
    ordered_ids = [cid for cid in ids if not (cid in seen or seen.add(cid))]

    scene_type_norm = str(scene_type or "").strip().lower()
    result: Dict[str, str] = {}

    if not ordered_ids:
        return result

    # 나레이션/독백 → 정면
    if scene_type_norm in _NARRATION_SCENE_TYPES:
        return {cid: "front" for cid in ordered_ids}

    # 퇴장/돌아섬 → 뒷모습 (화자 제외하고 나가는 인물 위주지만, 단순화: 전원 back)
    if scene_type_norm in _EXIT_SCENE_TYPES:
        return {cid: "back" for cid in ordered_ids}

    if len(ordered_ids) == 1:
        cid = ordered_ids[0]
        return {cid: prev.get(cid, "front")}

    if len(ordered_ids) == 2:
        left_id, right_id = ordered_ids[0], ordered_ids[1]
        # 180도 규칙: 이전에 정해진 마주봄 배치가 있으면 유지
        if prev.get(left_id) in ("right", "left") and prev.get(right_id) in ("right", "left") \
                and prev[left_id] != prev[right_id]:
            return {left_id: prev[left_id], right_id: prev[right_id]}
        # 좌측 인물은 오른쪽을 보고(right), 우측 인물은 왼쪽을 본다(left) → 서로 마주봄
        return {left_id: "right", right_id: "left"}

    # 3인 이상: 화자는 정면(관객/그룹 응대), 나머지는 좌우 교대
    result = {}
    side_cycle = ["left", "right"]
    side_i = 0
    for cid in ordered_ids:
        is_spk = False
        for c in characters:
            if _char_id(c) == cid:
                is_spk = _is_speaker(c)
                break
        if is_spk:
            result[cid] = prev.get(cid, "front")
        else:
            result[cid] = prev.get(cid) if prev.get(cid) in ("left", "right") else side_cycle[side_i % 2]
            side_i += 1
    return result


def apply_facings_to_characters(characters: Sequence[Any], facings: Mapping[str, str]) -> None:
    """결정된 facing을 캐릭터 객체/딕셔너리에 적용(in-place). dataclass(frozen)은 제외."""
    for char in characters:
        cid = _char_id(char)
        if not cid or cid not in facings:
            continue
        facing = normalize_facing(facings[cid])
        if isinstance(char, dict):
            char["facing"] = facing
        else:
            try:
                setattr(char, "facing", facing)
            except Exception:
                pass  # frozen dataclass 등은 건너뜀
