# tests/test_text_processor.py
"""
v60.1.0 Phase 2: TextProcessor 단위 테스트

pipeline.text_processor.TextProcessor의 7개 메서드 테스트.
외부 의존 0 — 순수 텍스트 변환 로직만 검증.
"""
import pytest

# conftest.py에서 src/ 경로 추가됨
from pipeline.text_processor import TextProcessor


@pytest.fixture
def tp():
    """TextProcessor 인스턴스"""
    return TextProcessor()


# ============================================================
# 1. num_to_sino_kor_1_99
# ============================================================

class TestNumToSinoKor1_99:
    """1~99 숫자 → 한국어 한자음 변환"""

    def test_zero_returns_empty(self, tp):
        assert tp.num_to_sino_kor_1_99(0) == ""

    def test_negative_returns_empty(self, tp):
        assert tp.num_to_sino_kor_1_99(-5) == ""

    def test_single_digit(self, tp):
        assert tp.num_to_sino_kor_1_99(1) == "일"
        assert tp.num_to_sino_kor_1_99(5) == "오"
        assert tp.num_to_sino_kor_1_99(9) == "구"

    def test_ten(self, tp):
        assert tp.num_to_sino_kor_1_99(10) == "십"

    def test_teens(self, tp):
        assert tp.num_to_sino_kor_1_99(11) == "십일"
        assert tp.num_to_sino_kor_1_99(15) == "십오"
        assert tp.num_to_sino_kor_1_99(19) == "십구"

    def test_twenties(self, tp):
        assert tp.num_to_sino_kor_1_99(20) == "이십"
        assert tp.num_to_sino_kor_1_99(23) == "이십삼"

    def test_large_two_digit(self, tp):
        assert tp.num_to_sino_kor_1_99(50) == "오십"
        assert tp.num_to_sino_kor_1_99(99) == "구십구"


# ============================================================
# 2. num_to_sino_kor_full
# ============================================================

class TestNumToSinoKorFull:
    """0~999 숫자 → 한국어 한자음 변환"""

    def test_zero_returns_empty(self, tp):
        assert tp.num_to_sino_kor_full(0) == ""

    def test_delegates_to_1_99(self, tp):
        assert tp.num_to_sino_kor_full(23) == "이십삼"

    def test_hundreds(self, tp):
        assert tp.num_to_sino_kor_full(100) == "일백"
        assert tp.num_to_sino_kor_full(123) == "일백이십삼"
        assert tp.num_to_sino_kor_full(200) == "이백"
        assert tp.num_to_sino_kor_full(305) == "삼백오"
        assert tp.num_to_sino_kor_full(999) == "구백구십구"

    def test_hundred_with_teens(self, tp):
        assert tp.num_to_sino_kor_full(110) == "일백십"
        assert tp.num_to_sino_kor_full(215) == "이백십오"


# ============================================================
# 3. fix_unit_numbers
# ============================================================

class TestFixUnitNumbers:
    """숫자+단위 → 한국어 변환"""

    def test_empty_string(self, tp):
        assert tp.fix_unit_numbers("") == ""

    def test_none_input(self, tp):
        assert tp.fix_unit_numbers(None) is None

    def test_floor_number(self, tp):
        assert tp.fix_unit_numbers("3층") == "삼층"

    def test_room_number(self, tp):
        assert tp.fix_unit_numbers("201호") == "이백일호"

    def test_building_number(self, tp):
        assert tp.fix_unit_numbers("5동") == "오동"

    def test_mixed_text(self, tp):
        result = tp.fix_unit_numbers("아파트 3동 201호에 살아요")
        assert "삼동" in result
        assert "이백일호" in result

    def test_number_too_large(self, tp):
        """1000 이상은 변환하지 않음"""
        assert "1000층" in tp.fix_unit_numbers("1000층")

    def test_number_with_space(self, tp):
        """숫자와 단위 사이 공백 허용"""
        assert tp.fix_unit_numbers("3 층") == "삼층"

    def test_large_money_units_are_converted_naturally(self, tp):
        assert tp.fix_unit_numbers("5000만원") == "오천만원"
        assert tp.fix_unit_numbers("1억2000만원") == "일억이천만원"


# ============================================================
# 4. clean_text
# ============================================================

class TestCleanText:
    """TTS용 텍스트 정제"""

    def test_empty_string(self, tp):
        result = tp.clean_text("")
        assert result == "네"  # 최소 길이 보장

    def test_none_input(self, tp):
        result = tp.clean_text(None)
        assert result == "네"

    def test_removes_special_chars(self, tp):
        result = tp.clean_text("안녕*하세요~#테스트")
        assert "*" not in result
        assert "~" not in result
        assert "#" not in result

    def test_ellipsis_to_comma(self, tp):
        """말줄임표(...)가 자막용 말줄임표로 정규화"""
        result = tp.clean_text("그런데... 사실은")
        assert "..." not in result
        assert "…" in result

    def test_leading_comma_removed(self, tp):
        result = tp.clean_text(", ...그렇지.")
        assert not result.startswith(",")
        assert "그렇지" in result

    def test_sound_effect_replacement(self, tp):
        """효과음 태그 변환"""
        result = tp.clean_text("(한숨) 힘들다")
        assert "(한숨)" not in result
        assert "하" in result  # "하⋯" → "하," 로 변환됨

    def test_brackets_removed(self, tp):
        result = tp.clean_text("이것은 (설명) 입니다")
        assert "(" not in result
        assert ")" not in result

    def test_unit_numbers_converted(self, tp):
        result = tp.clean_text("3층에서 만나요")
        assert "삼층" in result

    def test_minimum_length(self, tp):
        result = tp.clean_text(".")
        assert result == "네"

    def test_quotes_removed(self, tp):
        result = tp.clean_text('"안녕하세요"라고 말했다')
        assert '"' not in result
        assert '"' not in result

    def test_whitespace_normalized(self, tp):
        result = tp.clean_text("많은    공백이   있다")
        assert "    " not in result
        assert "   " not in result

    def test_clean_text_for_tts_converts_digit_sequences(self, tp):
        result = tp.clean_text_for_tts("주민번호 앞자리는 950324야.")
        assert "950324" not in result
        assert "구오공삼이사" in result

    def test_clean_text_for_tts_turns_ellipsis_into_pause_comma(self, tp):
        result = tp.clean_text_for_tts("...그렇지.")
        assert not result.startswith(",")
        assert "그렇지" in result

    def test_clean_text_for_tts_keeps_large_money_readable(self, tp):
        result = tp.clean_text_for_tts("피해 금액은 5000만원이었어요.")
        assert "오공공공만원" not in result
        assert "오천만원" in result

    def test_clean_text_for_tts_handles_combined_eok_and_man_units(self, tp):
        result = tp.clean_text_for_tts("총액은 1억2000만원입니다.")
        assert "일억이천만원" in result


# ============================================================
# 5. split_into_sentences
# ============================================================

class TestSplitIntoSentences:
    """자막용 문장 분할"""

    def test_empty_string(self, tp):
        assert tp.split_into_sentences("") == []

    def test_none_input(self, tp):
        assert tp.split_into_sentences(None) == []

    def test_short_text(self, tp):
        """10자 미만은 분할 안 함"""
        result = tp.split_into_sentences("짧은 텍스트")
        assert len(result) == 1
        assert result[0] == "짧은 텍스트"

    def test_period_split(self, tp):
        """마침표 기준 분할"""
        text = "첫 번째 문장은 이렇게 길게 써야 합니다. 두 번째 문장도 충분히 길어야 분할이 됩니다. 세 번째 문장도 마찬가지입니다."
        result = tp.split_into_sentences(text)
        assert len(result) >= 2

    def test_question_mark_split(self, tp):
        """물음표 기준 분할"""
        text = "왜 그런 거예요? 도대체 무슨 일이 있었던 건가요? 말해주세요."
        result = tp.split_into_sentences(text)
        assert len(result) >= 2

    def test_max_chars_enforced(self, tp):
        """40자 초과 시 추가 분할"""
        text = "이것은 매우 긴 문장으로서 사십 글자를 초과하는 내용을 포함하고 있으며, 쉼표가 있어서 추가 분할이 가능합니다."
        result = tp.split_into_sentences(text)
        # 각 청크가 합리적 길이인지 확인
        for chunk in result:
            assert len(chunk) <= 55  # MAX_CHARS(40) + 짧은 문장 합침 여유(15)

    def test_single_long_sentence_force_split(self, tp):
        """쉼표 없는 긴 문장은 강제 분할"""
        text = "이것은쉼표없이매우길게쓰여진문장으로서사십글자를훌쩍초과하는내용을담고있습니다다다다다다다다다다다다다다"
        result = tp.split_into_sentences(text)
        assert len(result) >= 2


# ============================================================
# 6. clean_text_for_retry
# ============================================================

class TestCleanTextForRetry:
    """TTS 재시도용 텍스트 단순화"""

    def test_level_0_no_change(self, tp):
        """level 0: 변경 없음"""
        result = tp.clean_text_for_retry("안녕... 하세요, 반갑습니다!", 0)
        assert result == "안녕... 하세요, 반갑습니다!"

    def test_level_1_removes_ellipsis(self, tp):
        """level 1: 말줄임표 제거"""
        result = tp.clean_text_for_retry("안녕... 하세요", 1)
        assert "..." not in result
        assert "안녕" in result

    def test_level_2_removes_comma(self, tp):
        """level 2: 쉼표도 제거"""
        result = tp.clean_text_for_retry("안녕, 하세요, 반갑습니다", 2)
        assert "," not in result

    def test_level_3_removes_punctuation(self, tp):
        """level 3: 문장 부호도 제거"""
        result = tp.clean_text_for_retry("정말요? 네! 그렇습니다.", 3)
        assert "?" not in result
        assert "!" not in result
        assert "." not in result

    def test_minimum_length(self, tp):
        """3자 미만이면 '네' 반환"""
        result = tp.clean_text_for_retry(".", 3)
        assert result == "네"

    def test_level_cumulative(self, tp):
        """level은 누적 적용 (level 3 = 1+2+3)"""
        text = "안녕... 하세요, 반갑습니다!"
        result = tp.clean_text_for_retry(text, 3)
        assert "..." not in result
        assert "," not in result
        assert "!" not in result


# ============================================================
# 7. role_key_normalize
# ============================================================

class TestRoleKeyNormalize:
    """역할명 → 표준 voice_type 정규화"""

    def test_narrator_aliases(self, tp):
        assert tp.role_key_normalize("나레이션") == "narrator"
        assert tp.role_key_normalize("내레이션") == "narrator"
        assert tp.role_key_normalize("해설") == "narrator"
        assert tp.role_key_normalize("narrator") == "narrator"

    def test_grandma_aliases(self, tp):
        assert tp.role_key_normalize("할머니") == "grandma"
        assert tp.role_key_normalize("외할머니") == "grandma"
        assert tp.role_key_normalize("할매") == "grandma"

    def test_grandpa_aliases(self, tp):
        assert tp.role_key_normalize("할아버지") == "grandpa"
        assert tp.role_key_normalize("외할아버지") == "grandpa"

    def test_middle_man_aliases(self, tp):
        assert tp.role_key_normalize("아빠") == "middle_man"
        assert tp.role_key_normalize("아버지") == "middle_man"
        assert tp.role_key_normalize("아저씨") == "middle_man"

    def test_middle_woman_aliases(self, tp):
        assert tp.role_key_normalize("엄마") == "middle_woman"
        assert tp.role_key_normalize("어머니") == "middle_woman"
        assert tp.role_key_normalize("아줌마") == "middle_woman"

    def test_young_man_aliases(self, tp):
        assert tp.role_key_normalize("남자") == "man"
        assert tp.role_key_normalize("아들") == "man"
        assert tp.role_key_normalize("오빠") == "man"

    def test_young_woman_aliases(self, tp):
        assert tp.role_key_normalize("여자") == "woman"
        assert tp.role_key_normalize("딸") == "woman"
        assert tp.role_key_normalize("언니") == "woman"

    def test_korean_male_name(self, tp):
        """한국 남성 이름 추론"""
        assert tp.role_key_normalize("태준") == "man"
        assert tp.role_key_normalize("민혁") == "man"

    def test_korean_female_name(self, tp):
        """한국 여성 이름 추론"""
        assert tp.role_key_normalize("혜미") == "woman"
        assert tp.role_key_normalize("서연") == "woman"

    def test_ending_char_male(self, tp):
        """끝 글자 남성 추론"""
        assert tp.role_key_normalize("상준") == "man"  # 준 = 남성
        assert tp.role_key_normalize("재훈") == "man"  # 훈 = 남성

    def test_ending_char_female(self, tp):
        """끝 글자 여성 추론"""
        assert tp.role_key_normalize("수연") == "woman"  # 연 = 여성
        assert tp.role_key_normalize("서희") == "woman"  # 희 = 여성

    def test_yeong_ending_female(self, tp):
        """'영' 끝나는 이름 — 여성 접두사"""
        assert tp.role_key_normalize("선영") == "woman"
        assert tp.role_key_normalize("민영") == "woman"

    def test_yeong_ending_male(self, tp):
        """'영' 끝나는 이름 — 남성 접두사 (끝글자 추론)"""
        # "태영"은 female_names에 등록되어 있으므로 woman
        # 끝글자 추론으로 male_prefixes 판정을 테스트하려면 등록되지 않은 이름 사용
        assert tp.role_key_normalize("도영") == "man"  # 도 = male_prefixes

    def test_unknown_returns_narrator(self, tp):
        """매핑 안 되면 narrator 반환"""
        assert tp.role_key_normalize("X") == "narrator"
        assert tp.role_key_normalize("") == "narrator"

    def test_case_insensitive(self, tp):
        """영어 역할명 대소문자 무관"""
        assert tp.role_key_normalize("Narrator") == "narrator"
        assert tp.role_key_normalize("MAN") == "man"
        assert tp.role_key_normalize("Woman") == "woman"

    def test_full_name_with_surname(self, tp):
        """성+이름 전체 이름"""
        assert tp.role_key_normalize("강태준") == "man"
        assert tp.role_key_normalize("김혜미") == "woman"
