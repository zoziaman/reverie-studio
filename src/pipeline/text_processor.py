# src/pipeline/text_processor.py
"""
v60.1.0 Phase 2: 한국어 텍스트 처리 모듈

media_factory.py에서 추출한 7개 순수 텍스트 처리 메서드.
외부 의존 0 — re 모듈만 사용.

원본 위치: media_factory.py L1104-1402
"""
import re
from typing import List


class TextProcessor:
    """
    한국어 텍스트 처리 — TTS/자막용 텍스트 정제

    모든 메서드는 stateless (인스턴스 변수 없음).
    """

    _SPOKEN_DIGITS = {
        "0": "공",
        "1": "일",
        "2": "이",
        "3": "삼",
        "4": "사",
        "5": "오",
        "6": "육",
        "7": "칠",
        "8": "팔",
        "9": "구",
    }

    _NATIVE_KOREAN_HOURS = {
        1: "\ud55c",
        2: "\ub450",
        3: "\uc138",
        4: "\ub124",
        5: "\ub2e4\uc12f",
        6: "\uc5ec\uc12f",
        7: "\uc77c\uacf1",
        8: "\uc5ec\ub35f",
        9: "\uc544\ud649",
        10: "\uc5f4",
        11: "\uc5f4\ud55c",
        12: "\uc5f4\ub450",
    }

    # ============================================================
    # 숫자 → 한국어 변환
    # ============================================================

    def num_to_sino_kor_1_99(self, n: int) -> str:
        """1~99 숫자를 한국어 한자음으로 변환 (예: 23 → "이십삼")

        원본: media_factory._num_to_sino_kor_1_99() L1104
        """
        ones = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
        if n <= 0:
            return ""
        if n < 10:
            return ones[n]
        tens = n // 10
        one = n % 10
        if n == 10:
            return "십"
        if tens == 1:
            return "십" + (ones[one] if one else "")
        return ones[tens] + "십" + (ones[one] if one else "")

    def num_to_sino_kor_full(self, n: int) -> str:
        """0~999 숫자를 한국어 한자음으로 변환 (예: 123 → "일백이십삼")

        원본: media_factory._num_to_sino_kor_full() L1118
        """
        if n <= 0:
            return ""
        if n < 100:
            return self.num_to_sino_kor_1_99(n)

        hundreds = n // 100
        rest = n % 100
        ones = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
        result = ones[hundreds] + "백"
        if rest > 0:
            result += self.num_to_sino_kor_1_99(rest)
        return result

    def _num_to_sino_kor_under_10000(self, n: int) -> str:
        """1~9999 숫자를 자연스러운 한자음으로 변환 (예: 100 -> "백", 5000 -> "오천")"""
        if n <= 0:
            return ""
        if n < 100:
            return self.num_to_sino_kor_1_99(n)

        ones = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
        units = [
            (1000, "천"),
            (100, "백"),
            (10, "십"),
            (1, ""),
        ]
        parts = []
        remaining = n
        for value, label in units:
            digit = remaining // value
            remaining %= value
            if digit <= 0:
                continue
            if value == 1:
                parts.append(ones[digit])
                continue
            prefix = "" if digit == 1 else ones[digit]
            parts.append(prefix + label)
        return "".join(parts)

    def num_to_sino_kor_large(self, n: int) -> str:
        """1 이상 큰 숫자를 만/억/조 단위 한자음으로 변환"""
        if n <= 0:
            return ""

        major_units = [
            (10**12, "조"),
            (10**8, "억"),
            (10**4, "만"),
        ]
        parts = []
        remaining = n
        for value, label in major_units:
            group = remaining // value
            remaining %= value
            if group <= 0:
                continue
            parts.append(self._num_to_sino_kor_under_10000(group) + label)
        if remaining > 0:
            parts.append(self._num_to_sino_kor_under_10000(remaining))
        return "".join(parts)

    # ============================================================
    # 단위 숫자 변환
    # ============================================================

    def fix_unit_numbers(self, t: str) -> str:
        """숫자+단위(층/호/동 등)를 한국어로 변환 (예: "3층" → "삼층")

        원본: media_factory._fix_unit_numbers() L1132
        """
        if not t:
            return t
        money_units = ["조원", "억원", "천만원", "백만원", "만원", "조", "억", "천만", "백만", "만", "원"]
        money_unit_pat = "(" + "|".join(money_units) + ")"

        def money_repl(m):
            token = m.group(0)
            chunks = re.findall(r"(\d[\d,]*)\s*" + money_unit_pat, token)
            if not chunks:
                return token
            return "".join(
                self.num_to_sino_kor_large(int(num.replace(",", ""))) + unit
                for num, unit in chunks
            )

        t = re.sub(r"(?:\d[\d,]*\s*" + money_unit_pat + r")+", money_repl, t)

        units = ["천만원", "백만원", "억원", "만원", "천만", "백만", "원", "억", "만", "층", "호", "동", "번지", "번", "관", "단지"]
        unit_pat = "(" + "|".join(units) + ")"

        def repl(m):
            num = int(m.group(1).replace(",", ""))
            unit = m.group(2)
            if num <= 0:
                return m.group(0)
            if unit in {"천만원", "백만원", "억원", "만원", "천만", "백만", "원", "억", "만"}:
                return self.num_to_sino_kor_large(num) + unit
            if 1 <= num <= 999:
                return self.num_to_sino_kor_full(num) + unit
            return m.group(0)

        return re.sub(r"(\d[\d,]*)\s*" + unit_pat + r"(?!\d)", repl, t)

    # ============================================================
    # TTS용 텍스트 정제
    # ============================================================

    def clean_text(self, text: str) -> str:
        """
        TTS용 텍스트 정제 — 특수문자 제거, 말줄임표 처리, 효과음 변환.

        처리 순서:
        1. 단위 숫자 한국어 변환 (3층→삼층)
        2. 특수문자 제거 (*, ~, #, @ 등)
        3. 말줄임표 보호 (...→…)
        4. 효과음 변환 ((한숨)→하⋯)
        5. 괄호/따옴표 제거
        6. 공백 정리
        7. 최소 길이 보장 (2자 미만 → "네")

        원본: media_factory._clean_text() L1147
        """
        t = (text or "").strip()
        t = self.fix_unit_numbers(t)

        # v50: GPT-SoVITS 호환성 강화 - 특수문자 제거
        t = t.replace("…", "...")
        t = t.replace("*", "")
        t = t.replace("~", "")
        t = t.replace("_", " ")
        t = re.sub(r'[#@$%^&+=|\\<>{}]', '', t)

        # v54: 말줄임표(...) 보호
        t = re.sub(r'\.{3,}', '⋯', t)
        t = re.sub(r'\.\s*\.\s*\.', '⋯', t)
        t = re.sub(r'\.{2}', '⋯', t)

        replacements = {
            "(한숨)": "하⋯", "(숨)": "후⋯", "(비명)": "으악!",
            "(소리침)": "야!!", "(울음)": "흑⋯", "(웃음)": "하하⋯",
            "(흐느낌)": "흑⋯ 흑⋯", "(기침)": "콜록⋯", "(속삭임)": "",
        }
        for k, v in replacements.items():
            t = t.replace(k, v)

        t = re.sub(r"\([^)]*\)", " ", t)
        t = re.sub(r"\[[^\]]*\]", " ", t)
        t = re.sub(r"[""\"']", "", t)
        t = re.sub(r"\s*,\s*", ", ", t)
        t = re.sub(r"(?<![⋯])\.\s*(?![⋯])", ". ", t)
        t = re.sub(r"\s*\?\s*", "? ", t)
        t = re.sub(r"\s*!\s*", "! ", t)
        t = re.sub(r"[,\s]+$", "", t)
        t = re.sub(r"\s{2,}", " ", t).strip()

        # 자막에서는 말줄임표를 그대로 유지하고, TTS에서만 별도 처리한다.
        t = t.replace('⋯', '…')
        t = re.sub(r"^[,\s]+", "", t)
        t = re.sub(r"\s+([,?.!…])", r"\1", t)

        # v50: 최소 길이 보장
        if len(t) < 2:
            t = "네"
        return t

    def _spoken_digit_sequence(self, seq: str) -> str:
        """숫자 시퀀스를 TTS용 한국어 발음으로 변환한다."""
        return "".join(self._SPOKEN_DIGITS[ch] for ch in seq if ch.isdigit())

    def _spoken_hour(self, hour: int, meridiem: str = "") -> str:
        """시간은 자연스러운 한국어 읽기를 우선하고, 범위를 벗어나면 한자어로 읽는다."""
        if 1 <= hour <= 12:
            return self._NATIVE_KOREAN_HOURS[hour]
        return self.num_to_sino_kor_large(hour)

    def _spoken_minute(self, minute: int) -> str:
        """분 단위는 0도 명시적으로 읽어야 TTS에서 누락되지 않는다."""
        if minute == 0:
            return "\uc601"
        return self.num_to_sino_kor_large(minute)

    def _convert_datetime_expressions_for_tts(self, text: str) -> str:
        """날짜/시간 표현을 자릿수 읽기 전에 자연스러운 한국어 발음으로 바꾼다."""
        year_token = "\ub144"
        month_token = "\uc6d4"
        day_token = "\uc77c"
        hour_token = "\uc2dc"
        minute_token = "\ubd84"
        am_token = "\uc624\uc804"
        pm_token = "\uc624\ud6c4"

        converted = text

        def replace_full_date(match):
            year = self.num_to_sino_kor_large(int(match.group(1)))
            month = self.num_to_sino_kor_large(int(match.group(2)))
            day = self.num_to_sino_kor_large(int(match.group(3)))
            return f"{year}{year_token} {month}{month_token} {day}{day_token}"

        def replace_year_month(match):
            year = self.num_to_sino_kor_large(int(match.group(1)))
            month = self.num_to_sino_kor_large(int(match.group(2)))
            return f"{year}{year_token} {month}{month_token}"

        def replace_iso_date(match):
            year = self.num_to_sino_kor_large(int(match.group(1)))
            month = self.num_to_sino_kor_large(int(match.group(2)))
            day = self.num_to_sino_kor_large(int(match.group(3)))
            return f"{year}{year_token} {month}{month_token} {day}{day_token}"

        def replace_meridiem_clock(match):
            meridiem = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3))
            spoken_hour = self._spoken_hour(hour, meridiem)
            spoken_minute = self._spoken_minute(minute)
            return f"{meridiem} {spoken_hour}{hour_token} {spoken_minute}{minute_token}"

        def replace_meridiem_hour_only(match):
            meridiem = match.group(1)
            hour = int(match.group(2))
            spoken_hour = self._spoken_hour(hour, meridiem)
            return f"{meridiem} {spoken_hour}{hour_token}"

        def replace_clock(match):
            hour = int(match.group(1))
            minute = int(match.group(2))
            spoken_hour = self._spoken_hour(hour)
            spoken_minute = self._spoken_minute(minute)
            return f"{spoken_hour}{hour_token} {spoken_minute}{minute_token}"

        converted = re.sub(r"(\d{4})\s*" + year_token + r"\s*(\d{1,2})\s*" + month_token + r"\s*(\d{1,2})\s*" + day_token, replace_full_date, converted)
        converted = re.sub(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", replace_iso_date, converted)
        converted = re.sub(r"(\d{4})\s*" + year_token + r"\s*(\d{1,2})\s*" + month_token, replace_year_month, converted)
        converted = re.sub(r"(" + am_token + "|" + pm_token + r")\s*(\d{1,2})\s*:\s*(\d{1,2})", replace_meridiem_clock, converted)
        converted = re.sub(r"(" + am_token + "|" + pm_token + r")\s*(\d{1,2})\s*" + hour_token + r"\s*(\d{1,2})\s*" + minute_token, replace_meridiem_clock, converted)
        converted = re.sub(r"(" + am_token + "|" + pm_token + r")\s*(\d{1,2})\s*" + hour_token, replace_meridiem_hour_only, converted)
        converted = re.sub(r"(?<!\d)(\d{1,2})\s*:\s*(\d{1,2})(?!\d)", replace_clock, converted)
        converted = re.sub(r"(?<!\d)(\d{1,2})\s*" + hour_token + r"\s*(\d{1,2})\s*" + minute_token, replace_clock, converted)

        return converted

    def clean_text_for_tts(self, text: str) -> str:
        """
        TTS용 전용 텍스트 정제.

        자막 가독성을 위한 표기는 유지하되, TTS에서는:
        1. 말줄임표를 짧은 쉼표로 변환
        2. 남아 있는 숫자를 한국어 발음으로 변환
        3. 선두 쉼표/불필요 구두점을 제거
        """
        t = self.clean_text(text)
        if not t:
            return "네"

        t = t.replace("…", ", ")
        t = self._convert_datetime_expressions_for_tts(t)
        t = re.sub(r"\d[\d\-]*", lambda m: self._spoken_digit_sequence(m.group(0)), t)
        t = re.sub(r"^[,\s]+", "", t)
        t = re.sub(r"\s*,\s*", ", ", t)
        t = re.sub(r"\s{2,}", " ", t).strip()

        if len(t) < 2:
            return "네"
        return t

    # ============================================================
    # 문장 분할 (자막용)
    # ============================================================

    def split_into_sentences(self, text: str) -> List[str]:
        """
        텍스트를 자막용 문장 단위로 분할.

        v57.6.8: 마침표/물음표/느낌표 기준 분할
        v58.2.3: 글자 수 기준 추가 분할 (한 자막 최대 40자)

        분할 순서:
        1. 문장 부호(. ? !) 기준 분할
        2. 40자 초과 시 쉼표(,) 기준 추가 분할
        3. 쉼표 없으면 강제 분할
        4. 15자 미만 짧은 문장은 이전 문장에 합침

        원본: media_factory._split_into_sentences() L1190
        """
        MAX_CHARS = 40

        if not text or len(text) < 10:
            return [text] if text else []

        # 문장 부호 기준 분할
        pattern = r'(?<=[.?!])\s+'
        parts = re.split(pattern, text.strip())
        parts = [p.strip() for p in parts if p.strip()]

        # v58.2.3: 긴 문장은 쉼표 기준 추가 분할
        expanded_parts = []
        for part in parts:
            if len(part) > MAX_CHARS:
                comma_parts = part.split(',')
                if len(comma_parts) > 1:
                    current_chunk = ""
                    for cp in comma_parts:
                        cp = cp.strip()
                        if not cp:
                            continue
                        test_chunk = current_chunk + (", " if current_chunk else "") + cp
                        if len(test_chunk) <= MAX_CHARS:
                            current_chunk = test_chunk
                        else:
                            if current_chunk:
                                expanded_parts.append(current_chunk)
                            current_chunk = cp
                    if current_chunk:
                        expanded_parts.append(current_chunk)
                else:
                    for i in range(0, len(part), MAX_CHARS):
                        chunk = part[i:i+MAX_CHARS].strip()
                        if chunk:
                            expanded_parts.append(chunk)
            else:
                expanded_parts.append(part)

        parts = expanded_parts

        if len(parts) <= 1:
            return parts

        # 짧은 문장(15자 미만) 합침
        result = []
        for part in parts:
            if result and len(part) < 15 and len(result[-1]) + len(part) + 1 <= MAX_CHARS + 10:
                result[-1] = result[-1] + " " + part
            else:
                result.append(part)

        return result if result else [text]

    # ============================================================
    # TTS 재시도용 텍스트 단순화
    # ============================================================

    def clean_text_for_retry(self, text: str, level: int) -> str:
        """
        TTS 실패 시 단계별 텍스트 단순화.

        level 1: 말줄임표(...) 제거
        level 2: 쉼표(,) 제거
        level 3: 문장 부호(. ! ?) 제거

        원본: media_factory._clean_text_for_retry() L1268
        """
        t = text
        if level >= 1:
            t = t.replace("...", " ")
            t = re.sub(r"\s{2,}", " ", t).strip()
        if level >= 2:
            t = t.replace(",", " ")
            t = re.sub(r"\s{2,}", " ", t).strip()
        if level >= 3:
            t = re.sub(r"[.!?]", " ", t)
            t = re.sub(r"\s{2,}", " ", t).strip()
        if len(t) < 3:
            t = "네"
        return t

    # ============================================================
    # 역할명 정규화 (한국어 이름 → 음성 타입)
    # ============================================================

    def role_key_normalize(self, role: str) -> str:
        """
        역할명을 표준 voice_type으로 정규화.

        v57.3.1: 엄마/아빠/청년남녀 등 역할 매핑
        v59.5.12: man/woman=청년(20-30대), middle_man/middle_woman=중년(40-50대)

        Returns:
            str: 표준 voice_type
                (narrator, man, woman, middle_man, middle_woman, grandma, grandpa)

        원본: media_factory._role_key_normalize() L1283
        """
        r = (role or "").strip().lower()

        alias = {
            # 나레이터
            "내레이션": "narrator", "나레이션": "narrator", "narration": "narrator",
            "narrator": "narrator", "해설": "narrator", "내레이터": "narrator",

            # 할머니 (여성 노인 70대+)
            "할머니": "grandma", "grandma": "grandma", "외할머니": "grandma",
            "친할머니": "grandma", "grandmother": "grandma", "할매": "grandma",

            # 할아버지 (남성 노인 70대+)
            "할아버지": "grandpa", "grandpa": "grandpa", "외할아버지": "grandpa",
            "친할아버지": "grandpa", "grandfather": "grandpa", "할배": "grandpa",

            # 중년 남성 (40-50대)
            "아빠": "middle_man", "아버지": "middle_man", "father": "middle_man", "dad": "middle_man",
            "남편": "middle_man", "삼촌": "middle_man", "아저씨": "middle_man",
            "중년남자": "middle_man", "중년남성": "middle_man",
            "middle_man": "middle_man",

            # 중년 여성 (40-50대)
            "엄마": "middle_woman", "어머니": "middle_woman", "mother": "middle_woman", "mom": "middle_woman",
            "아내": "middle_woman", "이모": "middle_woman", "아줌마": "middle_woman",
            "중년여자": "middle_woman", "중년여성": "middle_woman",
            "middle_woman": "middle_woman",

            # 청년 남성 (20-30대)
            "남자": "man", "man": "man", "청년": "man",
            "아들": "man", "젊은남자": "man", "청년남자": "man",
            "오빠": "man", "형": "man", "남동생": "man", "son": "man",
            # v62.10: young_man은 young_man으로 명시 매핑 (이름 추론 로직에 의해 narrator로 떨어지는 버그 방지)
            "young_man": "young_man",

            # 청년 여성 (20-30대)
            "여자": "woman", "woman": "woman", "처녀": "woman",
            "딸": "woman", "젊은여자": "woman", "청년여자": "woman",
            "언니": "woman", "누나": "woman", "여동생": "woman", "daughter": "woman",
            # v62.10: young_woman은 young_woman으로 명시 매핑 (이름 추론 로직에 의해 narrator로 떨어지는 버그 방지)
            "young_woman": "young_woman",

            # 임시 child 보이스는 TTS 단계에서 young_woman으로 대체된다.
            "child": "child", "kid": "child", "boy": "child", "girl": "child",
            "아이": "child", "어린이": "child", "손주": "child",
        }

        # 직접 매핑 확인
        if role in alias:
            return alias[role]
        if r in alias:
            return alias[r]

        # v57.6.7: 한국 이름 성별 추론
        male_names = (
            "태준", "민혁", "지훈", "성우", "강민", "동현", "준호", "영수", "철수", "민수",
            "현우", "지호", "승현", "재민", "도윤", "시우", "주원", "하준", "은우", "건우",
            "태진", "성민", "정호", "재호", "민호", "승우", "진우", "현준", "영호", "상철",
            "기철", "용수", "용호", "명수", "명호", "광수", "광호", "종수", "종호", "병철",
            "강태준", "서민혁", "박지훈", "김성우", "이동현", "한태준", "이민혁",
        )
        female_names = (
            "혜미", "지우", "수아", "민지", "서연", "지은", "유나", "하은", "소희", "예린",
            "민주", "수진", "영희", "순자", "영자", "정숙", "미숙", "미영", "은주", "미선",
            "은정", "지영", "수영", "미정", "현정", "지현", "수현", "유진", "소연", "혜진",
            "지원", "민서", "수빈", "예은", "하영", "소영", "미래", "보라", "나영", "다영",
            "선영", "민영", "수영", "은영", "미영", "혜영", "진영", "현영", "주영", "보영",
            "세영", "유영", "지영", "소영", "하영", "나영", "다영", "가영", "채영", "태영",
            "서지우", "김혜미", "박민지", "이서연", "최유나", "정하은", "강소희", "한서연",
            "김민주", "이수진", "박영희", "최은정", "김선영", "이민영", "박수영", "최은영",
        )

        if role in male_names or r in male_names:
            return "man"
        if role in female_names or r in female_names:
            return "woman"

        # 끝 글자 성별 추론
        if len(role) >= 2:
            last_char = role[-1]
            first_char = role[0] if len(role) >= 2 else ""

            male_endings = ("준", "혁", "민", "훈", "우", "진", "호", "석", "수", "철",
                          "현", "규", "태", "성", "섭", "웅", "환", "기", "원")
            female_endings = ("미", "아", "희", "연", "은", "지", "서", "린", "나", "윤",
                            "빈", "주", "숙", "순", "정", "선", "경", "라")

            # "영"으로 끝나는 이름 성별 판단
            if last_char == "영":
                female_prefixes = ("선", "민", "수", "은", "미", "혜", "진", "현", "주", "보",
                                 "세", "유", "지", "소", "하", "나", "다", "가", "채")
                male_prefixes = ("태", "성", "도", "광", "용")
                if first_char in female_prefixes:
                    return "woman"
                if first_char in male_prefixes:
                    return "man"
                return "woman"

            if last_char in male_endings:
                return "man"
            if last_char in female_endings:
                return "woman"

        return "narrator"
