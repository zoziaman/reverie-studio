"""v63: 장면 블로킹(facing 자동 결정) 단위 테스트."""
from utils import scene_blocking as sb


def _char(cid, is_speaker=False):
    return {"id": cid, "is_speaker": is_speaker}


def test_normalize_facing():
    assert sb.normalize_facing("LEFT") == "left"
    assert sb.normalize_facing("weird") == "front"
    assert sb.normalize_facing(None) == "front"


def test_single_character_faces_front():
    assert sb.assign_scene_facings([_char("a")]) == {"a": "front"}


def test_narration_all_front():
    out = sb.assign_scene_facings([_char("a"), _char("b")], scene_type="narration")
    assert out == {"a": "front", "b": "front"}


def test_two_characters_face_each_other():
    out = sb.assign_scene_facings([_char("a", True), _char("b")])
    # 좌측(a) → right, 우측(b) → left = 서로 마주봄
    assert out == {"a": "right", "b": "left"}
    assert out["a"] != out["b"]


def test_two_characters_maintain_previous_facing_180_rule():
    prev = {"a": "left", "b": "right"}
    out = sb.assign_scene_facings([_char("a"), _char("b")], previous_facings=prev)
    assert out == {"a": "left", "b": "right"}


def test_three_characters_speaker_front_others_sides():
    out = sb.assign_scene_facings([_char("a", True), _char("b"), _char("c")])
    assert out["a"] == "front"
    assert {out["b"], out["c"]} == {"left", "right"}


def test_exit_scene_back():
    out = sb.assign_scene_facings([_char("a")], scene_type="exit")
    assert out == {"a": "back"}


def test_empty_characters():
    assert sb.assign_scene_facings([]) == {}


def test_apply_facings_to_dict_characters():
    chars = [{"id": "a"}, {"id": "b"}]
    sb.apply_facings_to_characters(chars, {"a": "right", "b": "left"})
    assert chars[0]["facing"] == "right"
    assert chars[1]["facing"] == "left"


def test_apply_facings_to_object_characters():
    class C:
        def __init__(self, cid):
            self.id = cid
            self.facing = "front"
    chars = [C("a")]
    sb.apply_facings_to_characters(chars, {"a": "left"})
    assert chars[0].facing == "left"
