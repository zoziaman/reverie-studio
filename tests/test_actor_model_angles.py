"""v63: 캐릭터 다각도(턴어라운드) 데이터 모델 — actor_model angle 기본기 테스트."""
from utils import actor_model as am


def test_variant_parts_defaults_angle_to_front_for_legacy_keys():
    assert am._variant_parts("neutral_standing") == ("neutral", "standing", "front")
    assert am._variant_parts("talking_seated") == ("talking", "seated", "front")


def test_variant_parts_reads_angle_from_three_part_key():
    assert am._variant_parts("neutral_standing_left") == ("neutral", "standing", "left")
    assert am._variant_parts("happy_seated_back") == ("happy", "seated", "back")


def test_make_variant_key_roundtrip():
    key = am._make_variant_key("talking", "standing", "right")
    assert key == "talking_standing_right"
    assert am._variant_parts(key) == ("talking", "standing", "right")


def test_expand_variants_with_angles_full_matrix():
    expanded = am.expand_variants_with_angles(["neutral_standing"])
    assert expanded == [
        "neutral_standing_front",
        "neutral_standing_left",
        "neutral_standing_right",
        "neutral_standing_back",
    ]


def test_expand_variants_keeps_existing_angle_keys():
    expanded = am.expand_variants_with_angles(["neutral_standing_left"])
    assert expanded == ["neutral_standing_left"]


def test_variant_groups_collects_angles():
    groups = am._variant_groups(
        ["neutral_standing_front", "neutral_standing_left", "talking_standing_back"],
        list(am.DEFAULT_MOUTH_SHAPES),
        list(am.DEFAULT_EYE_SHAPES),
    )
    assert groups["angles"] == ["front", "left", "back"]


def test_default_angles_cover_four_views_and_back_has_no_face_parts():
    assert set(am.DEFAULT_ANGLES) == {"front", "left", "right", "back"}
    assert "back" in am.ANGLES_WITHOUT_FACE_PARTS


def _read_manifest(scaffold_result):
    import json
    from pathlib import Path
    path = Path(scaffold_result)
    # scaffold_actor_model이 매니페스트 파일 경로 또는 디렉토리를 반환할 수 있어 모두 처리
    if path.is_dir():
        for name in ("actor.json", "actor_model.json"):
            candidate = path / name
            if candidate.exists():
                path = candidate
                break
    return json.loads(path.read_text(encoding="utf-8"))


def test_scaffold_include_angles_expands_full_turnaround(tmp_path):
    result = am.scaffold_actor_model(
        "turnaround_test_actor",
        actor_root=tmp_path,
        repo_root=tmp_path,
        include_angles=True,
    )
    manifest = _read_manifest(result)
    variants = manifest["required_variants"]
    # 10 base × 4 angles = 40
    assert len(variants) == len(am.DEFAULT_REQUIRED_VARIANTS) * len(am.DEFAULT_ANGLES)
    assert "neutral_standing_front" in variants
    assert "neutral_standing_back" in variants


def test_scaffold_without_angles_is_backward_compatible(tmp_path):
    result = am.scaffold_actor_model(
        "legacy_test_actor",
        actor_root=tmp_path,
        repo_root=tmp_path,
        include_angles=False,
    )
    manifest = _read_manifest(result)
    assert manifest["required_variants"] == list(am.DEFAULT_REQUIRED_VARIANTS)


# --- T2: 각도별 앵커 / 레이어 ---

def test_angle_uses_face_parts():
    assert am.angle_uses_face_parts("front") is True
    assert am.angle_uses_face_parts("left") is True
    assert am.angle_uses_face_parts("back") is False


def test_resolve_anchor_points_falls_back_to_flat():
    contract = {"anchor_points": {"eye_center": {"x": 0.5, "y": 0.25}}, "anchor_points_by_angle": {}}
    assert am.resolve_anchor_points(contract, "front") == {"eye_center": {"x": 0.5, "y": 0.25}}
    assert am.resolve_anchor_points(contract, "back") == {"eye_center": {"x": 0.5, "y": 0.25}}


def test_resolve_anchor_points_uses_per_angle_override():
    contract = {
        "anchor_points": {"eye_center": {"x": 0.5, "y": 0.25}},
        "anchor_points_by_angle": {"left": {"eye_center": {"x": 0.4, "y": 0.26}}},
    }
    assert am.resolve_anchor_points(contract, "left") == {"eye_center": {"x": 0.4, "y": 0.26}}


def test_resolve_anchor_points_mirrors_left_for_right():
    contract = {
        "anchor_points": {"eye_center": {"x": 0.5, "y": 0.25}},
        "anchor_points_by_angle": {"left": {"eye_center": {"x": 0.4, "y": 0.26}}},
    }
    mirrored = am.resolve_anchor_points(contract, "right")
    # left x=0.4 → right x=0.6 (1-x), y 유지
    assert mirrored["eye_center"]["x"] == 0.6
    assert mirrored["eye_center"]["y"] == 0.26


def test_layer_order_for_angle_drops_face_layers_on_back():
    contract = {"layer_order": ["variant_base", "eye_layer", "mouth_layer"]}
    assert am.layer_order_for_angle(contract, "front") == ["variant_base", "eye_layer", "mouth_layer"]
    assert am.layer_order_for_angle(contract, "back") == ["variant_base"]
