# src/utils/ai_content_enhancer.py
"""
AI 제목/태그 추천 강화
- YouTube SEO 최적화 제목 생성
- 관련 태그 자동 생성
- 설명문 개선
"""
import os
import json
from typing import List, Dict, Any, Optional

from utils.gemini_compat import configure_gemini, get_gemini_model


class AIContentEnhancer:
    """AI 기반 콘텐츠 최적화"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key

        if api_key:
            configure_gemini(api_key)

        # 채널별 키워드 풀
        self.keyword_pools = {
            "daily_life_toon": {
                "main": ["일상툰", "영상툰", "웹툰드라마", "생활드라마", "반전툰"],
                "sub": ["동네이야기", "캐릭터툰", "감성툰", "짧은드라마", "웹툰애니"],
                "trending": ["퇴근길", "아파트", "편의점", "카페", "관계반전"]
            },
            "mystery_toon": {
                "main": ["미스터리툰", "영상툰", "생활미스터리", "추리툰", "반전툰"],
                "sub": ["아파트괴담", "복도끝", "단서", "웹툰드라마", "캐릭터툰"],
                "trending": ["새벽2시", "젖은우산", "옥상문", "편의점CCTV", "관리인"]
            }
        }

    def generate_optimized_title(self,
                                  original_title: str,
                                  channel: str,
                                  mode: str,
                                  scenario_summary: str = "") -> Dict[str, Any]:
        """
        SEO 최적화 제목 생성

        Args:
            original_title: 원본 제목
            channel: 채널 (horror, senior)
            mode: 모드 (horror, touching, makjang)
            scenario_summary: 시나리오 요약

        Returns:
            Dict with titles and recommendations
        """
        channel_key = f"{channel}_{mode}" if channel == "senior" else channel

        # AI를 사용할 수 없으면 기본 최적화
        if not self.api_key:
            return self._basic_title_optimization(original_title, channel_key)

        try:
            model = get_gemini_model("gemini-3-flash-preview")
            if model is None:
                return self._basic_title_optimization(original_title, channel_key)

            prompt = f"""당신은 YouTube SEO 전문가입니다. 다음 정보를 바탕으로 클릭률(CTR)이 높은 제목 3개를 추천해주세요.

원본 제목: {original_title}
채널 유형: {channel_key}
시나리오 요약: {scenario_summary[:300] if scenario_summary else "없음"}

요구사항:
1. 40자 이내로 작성
2. 호기심을 자극하는 표현 사용
3. 숫자나 구체적 표현 활용
4. 감정을 자극하는 단어 포함
5. 채널 특성에 맞는 톤 유지

JSON 형식으로만 응답하세요:
{{"titles": ["제목1", "제목2", "제목3"], "best_choice": 0, "reason": "추천 이유"}}"""

            response = model.generate_content(prompt)
            text = response.text.strip()

            # JSON 파싱
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            result = json.loads(text)
            result["original"] = original_title
            return result

        except Exception as e:
            print(f"AI 제목 생성 오류: {e}")
            return self._basic_title_optimization(original_title, channel_key)

    def _basic_title_optimization(self, title: str, channel_key: str) -> Dict[str, Any]:
        """기본 제목 최적화"""
        keywords = self.keyword_pools.get(channel_key, self.keyword_pools["horror"])

        # 제목에 키워드가 없으면 추가
        optimized_titles = []

        # 원본 유지
        optimized_titles.append(title)

        # 앞에 키워드 추가
        main_kw = keywords["main"][0]
        if main_kw not in title:
            optimized_titles.append(f"[{main_kw}] {title}")

        # 뒤에 반응 추가
        optimized_titles.append(f"{title} (사례 재구성)")

        return {
            "titles": optimized_titles[:3],
            "best_choice": 1,
            "reason": "키워드 추가로 검색 노출 향상",
            "original": title
        }

    def generate_tags(self,
                      title: str,
                      channel: str,
                      mode: str,
                      description: str = "",
                      max_tags: int = 15) -> List[str]:
        """
        관련 태그 생성

        Args:
            title: 제목
            channel: 채널
            mode: 모드
            description: 설명
            max_tags: 최대 태그 수

        Returns:
            List of tags
        """
        channel_key = f"{channel}_{mode}" if channel == "senior" else channel
        keywords = self.keyword_pools.get(channel_key, self.keyword_pools["horror"])

        # 기본 태그 수집
        tags = set()

        # 메인 키워드
        tags.update(keywords["main"])

        # 서브 키워드
        tags.update(keywords["sub"][:5])

        # 트렌딩 키워드
        tags.update(keywords["trending"][:3])

        # 제목에서 키워드 추출
        title_words = [w for w in title.replace(",", " ").replace(".", " ").split() if len(w) >= 2]
        for word in title_words[:5]:
            if word not in ["의", "을", "를", "이", "가", "에", "에서", "으로", "로"]:
                tags.add(word)

        # AI로 추가 태그 생성
        if self.api_key:
            ai_tags = self._generate_ai_tags(title, channel_key, description)
            tags.update(ai_tags)

        return list(tags)[:max_tags]

    def _generate_ai_tags(self, title: str, channel_key: str, description: str) -> List[str]:
        """AI로 태그 생성"""
        try:
            model = get_gemini_model("gemini-3-flash-preview")
            if model is None:
                return []

            prompt = f"""다음 YouTube 영상에 적합한 태그 10개를 생성해주세요.

제목: {title}
채널 유형: {channel_key}
설명: {description[:200] if description else "없음"}

요구사항:
- 검색에 잘 걸리는 키워드
- 2-6글자 사이의 단어
- 해시태그 없이 단어만

쉼표로 구분하여 응답하세요 (예: 공포, 사례재구성, 미스터리)"""

            response = model.generate_content(prompt)
            text = response.text.strip()

            # 태그 파싱
            tags = [t.strip() for t in text.split(",")]
            return [t for t in tags if 2 <= len(t) <= 10][:10]

        except Exception as e:
            print(f"AI 태그 생성 오류: {e}")
            return []

    def enhance_description(self,
                            original_description: str,
                            title: str,
                            channel: str,
                            mode: str,
                            tags: List[str] = None) -> str:
        """
        설명문 개선

        Args:
            original_description: 원본 설명
            title: 제목
            channel: 채널
            mode: 모드
            tags: 태그 목록

        Returns:
            Enhanced description
        """
        channel_key = f"{channel}_{mode}" if channel == "senior" else channel

        # 해시태그 생성
        if tags:
            hashtags = " ".join([f"#{t}" for t in tags[:10]])
        else:
            keywords = self.keyword_pools.get(channel_key, self.keyword_pools["horror"])
            hashtags = " ".join([f"#{t}" for t in keywords["main"][:5]])

        # 채널별 CTA (Call to Action)
        cta_templates = {
            "daily_life_toon": "다음 영상툰도 보고 싶다면 구독으로 함께해 주세요.",
            "mystery_toon": "다음 단서가 궁금하다면 구독으로 이어서 봐 주세요."
        }

        cta = cta_templates.get(channel_key, cta_templates["daily_life_toon"])

        # 설명문 템플릿
        enhanced = f"""
{original_description}

━━━━━━━━━━━━━━━━━━━━━━━

{cta}

{hashtags}
"""

        return enhanced.strip()

    def get_thumbnail_text_suggestions(self,
                                        title: str,
                                        channel: str,
                                        mode: str) -> Dict[str, List[str]]:
        """
        썸네일 텍스트 추천

        Returns:
            Dict with top_text and main_text suggestions
        """
        channel_key = f"{channel}_{mode}" if channel == "senior" else channel

        # 기본 추천
        suggestions = {
            "daily_life_toon": {
                "top_text": ["일상툰", "짧은 웹툰", "생활 반전", "동네 이야기"],
                "main_text": ["그날의 한마디", "이상한 아침", "퇴근길에", "옆집 이야기"]
            },
            "mystery_toon": {
                "top_text": ["미스터리툰", "생활 미스터리", "단서 발견", "복도 끝"],
                "main_text": ["새벽 2시", "젖은 우산", "옥상 문", "관리인은"]
            }
        }

        return suggestions.get(channel_key, suggestions["daily_life_toon"])

    def analyze_title_quality(self, title: str) -> Dict[str, Any]:
        """
        제목 품질 분석

        Returns:
            Dict with score and recommendations
        """
        score = 0
        recommendations = []

        # 길이 체크 (30-50자 최적)
        length = len(title)
        if 30 <= length <= 50:
            score += 25
        elif 20 <= length <= 60:
            score += 15
            recommendations.append("제목을 30-50자로 조정하면 더 좋습니다.")
        else:
            recommendations.append("제목 길이를 30-50자로 조정하세요.")

        # 숫자 포함 여부
        if any(c.isdigit() for c in title):
            score += 15
        else:
            recommendations.append("숫자를 포함하면 클릭률이 올라갑니다.")

        # 감정 키워드 체크
        emotion_words = ["반전", "감동", "눈물", "긴장", "통쾌", "비밀", "사례"]
        if any(w in title for w in emotion_words):
            score += 20
        else:
            recommendations.append("감정을 자극하는 키워드를 추가하세요.")

        # 괄호/특수문자 사용
        if any(c in title for c in "[]()!?"):
            score += 10

        # 질문형 체크
        if "?" in title or title.endswith("다?") or "왜" in title:
            score += 15

        # 호기심 유발 단어
        curiosity_words = ["비밀", "진실", "숨겨진", "몰랐던", "결국"]
        if any(w in title for w in curiosity_words):
            score += 15

        return {
            "score": min(score, 100),
            "grade": "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D",
            "recommendations": recommendations
        }
