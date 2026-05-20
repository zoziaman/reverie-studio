from utils.motiontoon import infer_scene_type


def test_confrontation_takes_precedence_over_prop_keywords():
    text = "\uacc4\uc88c \uc99d\uac70\uac00 \uc788\ub294\ub370, \ub2f9\uc2e0 \uac70\uc9d3\ub9d0 \uadf8\ub9cc\ud574."

    assert infer_scene_type(text, speaker="\uc21c\uc790") == "confrontation"
