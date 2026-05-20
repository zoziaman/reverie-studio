import pytest

from pipeline.text_processor import TextProcessor


@pytest.fixture
def tp():
    return TextProcessor()


def test_clean_text_for_tts_reads_year_month_time_naturally(tp):
    result = tp.clean_text_for_tts(
        "\u0032\u0030\u0032\u0036\ub144 \u0033\uc6d4, \uc624\uc804 \u0037\uc2dc \u0032\u0033\ubd84\uc785\ub2c8\ub2e4."
    )
    assert "\uc774\uacf5\uc774\uc721" not in result
    assert "\uc774\ucc9c\uc774\uc2ed\uc721\ub144" in result
    assert "\uc0bc\uc6d4" in result
    assert "\uc624\uc804 \uc77c\uacf1\uc2dc \uc774\uc2ed\uc0bc\ubd84" in result


def test_clean_text_for_tts_reads_full_date_naturally(tp):
    result = tp.clean_text_for_tts(
        "\u0032\u0030\u0032\u0036\ub144 \u0033\uc6d4 \u0032\u0034\uc77c \uc624\uc804 \u0037\uc2dc \u0032\u0033\ubd84\uc785\ub2c8\ub2e4."
    )
    assert "\uc774\ucc9c\uc774\uc2ed\uc721\ub144 \uc0bc\uc6d4 \uc774\uc2ed\uc0ac\uc77c" in result
    assert "\uc624\uc804 \uc77c\uacf1\uc2dc \uc774\uc2ed\uc0bc\ubd84" in result


def test_clean_text_for_tts_reads_clock_time_naturally(tp):
    result = tp.clean_text_for_tts(
        "\ud68c\uc758 \uc2dc\uac04\uc740 \u0031\u0034:\u0033\u0032\uc785\ub2c8\ub2e4."
    )
    assert "\uc77c\uc0ac\uc0bc\uc774" not in result
    assert "\uc2ed\uc0ac\uc2dc \uc0bc\uc2ed\uc774\ubd84" in result


def test_clean_text_for_tts_keeps_zero_minutes(tp):
    result = tp.clean_text_for_tts("\uc624\uc804 \u0037\uc2dc \u0030\u0030\ubd84\uc785\ub2c8\ub2e4.")
    assert "\uc624\uc804 \uc77c\uacf1\uc2dc \uc601\ubd84" in result
    assert "\uc2dc \ubd84" not in result


def test_clean_text_for_tts_keeps_zero_minutes_in_colon_time(tp):
    result = tp.clean_text_for_tts("\uc2dc\uc791 \uc2dc\uac04\uc740 \u0031\u0039:\u0030\u0030\uc785\ub2c8\ub2e4.")
    assert "\uc2ed\uad6c\uc2dc \uc601\ubd84" in result
    assert "\uc2dc \ubd84" not in result


def test_clean_text_for_tts_reads_large_money_naturally(tp):
    result = tp.clean_text_for_tts(
        "\u0031\uc5b5\u0032\u0030\u0030\u0030\ub9cc\uc6d0 \uc1a1\uae08\uc785\ub2c8\ub2e4."
    )
    assert "\uc77c\uc5b5\uc774\ucc9c\ub9cc\uc6d0" in result
    assert "\uc77c\uc774\uacf5\uacf5\uacf5\ub9cc\uc6d0" not in result
