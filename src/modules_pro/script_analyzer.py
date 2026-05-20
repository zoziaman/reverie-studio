# src/modules_pro/script_analyzer.py
# ============================================================
# v56.1: 대본 분석 및 편집 도구
# scenario_planner.py에서 분리
# ============================================================
from typing import Dict, List, Any
from collections import Counter


class ScriptAnalyzer:
    """
    대본 분석 및 통계 도구
    """

    @staticmethod
    def analyze(script_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        대본 분석 및 통계 생성

        Args:
            script_list: 대본 리스트

        Returns:
            분석 결과 딕셔너리
        """
        if not script_list:
            return {"error": "대본이 비어있습니다."}

        # 기본 통계
        total_turns = len(script_list)
        total_chars = sum(len(s.get("text", "")) for s in script_list)

        # 역할별 통계
        role_counts = Counter(s.get("role", "unknown") for s in script_list)
        role_chars = {}
        for s in script_list:
            role = s.get("role", "unknown")
            role_chars[role] = role_chars.get(role, 0) + len(s.get("text", ""))

        # 감정별 통계
        emotion_counts = Counter(s.get("emotion", "calm") for s in script_list)

        # 감정 흐름 분석 (10구간으로 나눔)
        emotion_flow = []
        chunk_size = max(1, total_turns // 10)
        for i in range(0, total_turns, chunk_size):
            chunk = script_list[i:i+chunk_size]
            chunk_emotions = Counter(s.get("emotion", "calm") for s in chunk)
            dominant = chunk_emotions.most_common(1)[0][0] if chunk_emotions else "calm"
            emotion_flow.append(dominant)

        # 대사 길이 분석
        text_lengths = [len(s.get("text", "")) for s in script_list]
        avg_length = sum(text_lengths) / len(text_lengths) if text_lengths else 0
        max_length = max(text_lengths) if text_lengths else 0
        min_length = min(text_lengths) if text_lengths else 0

        # 예상 TTS 시간 (평균 초당 4글자 기준)
        estimated_duration_sec = total_chars / 4
        estimated_duration_min = estimated_duration_sec / 60

        return {
            "summary": {
                "total_turns": total_turns,
                "total_characters": total_chars,
                "estimated_duration_min": round(estimated_duration_min, 1),
                "avg_text_length": round(avg_length, 1),
                "max_text_length": max_length,
                "min_text_length": min_length,
            },
            "role_distribution": {
                "counts": dict(role_counts),
                "percentages": {k: round(v / total_turns * 100, 1) for k, v in role_counts.items()},
                "character_counts": role_chars,
            },
            "emotion_distribution": {
                "counts": dict(emotion_counts),
                "percentages": {k: round(v / total_turns * 100, 1) for k, v in emotion_counts.items()},
                "flow": emotion_flow,
            },
            "quality_checks": ScriptAnalyzer._quality_checks(script_list, role_counts, emotion_counts),
        }

    @staticmethod
    def _quality_checks(script_list: List[Dict], role_counts: Counter, emotion_counts: Counter) -> Dict[str, Any]:
        """품질 체크"""
        issues = []
        warnings = []

        total = len(script_list)

        # 1. 나레이터 비율 체크 (50% 초과 시 경고)
        narrator_ratio = role_counts.get("narrator", 0) / total if total > 0 else 0
        if narrator_ratio > 0.6:
            warnings.append(f"나레이터 비율이 {narrator_ratio*100:.0f}%로 높습니다. 대사를 더 추가하세요.")

        # 2. 감정 다양성 체크
        if len(emotion_counts) < 3:
            warnings.append(f"감정 종류가 {len(emotion_counts)}개로 단조롭습니다. 다양한 감정을 추가하세요.")

        # 3. calm 감정 과다 체크
        calm_ratio = emotion_counts.get("calm", 0) / total if total > 0 else 0
        if calm_ratio > 0.7:
            warnings.append(f"calm 감정이 {calm_ratio*100:.0f}%로 많습니다. 감정 변화를 추가하세요.")

        # 4. 대사 길이 체크
        short_texts = sum(1 for s in script_list if len(s.get("text", "")) < 5)
        if short_texts > total * 0.2:
            warnings.append(f"5자 미만의 짧은 대사가 {short_texts}개 있습니다.")

        # 5. 연속 동일 역할 체크
        max_consecutive = 1
        current_consecutive = 1
        for i in range(1, len(script_list)):
            if script_list[i].get("role") == script_list[i-1].get("role"):
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 1

        if max_consecutive > 5:
            warnings.append(f"동일 역할이 {max_consecutive}번 연속됩니다. 역할을 섞어주세요.")

        return {
            "issues": issues,
            "warnings": warnings,
            "is_healthy": len(issues) == 0 and len(warnings) <= 2,
        }

    @staticmethod
    def get_preview(script_list: List[Dict[str, Any]], start: int = 0, count: int = 10) -> List[Dict[str, Any]]:
        """
        대본 미리보기

        Args:
            script_list: 대본 리스트
            start: 시작 인덱스
            count: 가져올 개수

        Returns:
            미리보기 대본 리스트
        """
        return script_list[start:start + count]

    @staticmethod
    def format_for_display(script_list: List[Dict[str, Any]], include_index: bool = True) -> str:
        """
        대본을 표시용 문자열로 포맷팅

        Args:
            script_list: 대본 리스트
            include_index: 인덱스 포함 여부

        Returns:
            포맷팅된 문자열
        """
        lines = []
        for i, s in enumerate(script_list):
            role = s.get("role", "unknown")
            text = s.get("text", "")
            emotion = s.get("emotion", "calm")

            role_emoji = {
                "narrator": "[N]",
                "grandma": "[GM]",
                "grandpa": "[GP]",
                "man": "[M]",
                "woman": "[W]",
            }.get(role, "[?]")

            emotion_mark = {
                "calm": "-",
                "happy": "+",
                "sad": "~",
                "angry": "!",
                "fear": "*",
            }.get(emotion, "-")

            if include_index:
                lines.append(f"[{i+1:03d}] {role_emoji} {role} ({emotion_mark}): {text}")
            else:
                lines.append(f"{role_emoji} {role} ({emotion_mark}): {text}")

        return "\n".join(lines)


class ScriptEditor:
    """
    대본 편집 도구
    """

    @staticmethod
    def edit_turn(script_list: List[Dict[str, Any]], index: int,
                  text: str = None, role: str = None, emotion: str = None) -> List[Dict[str, Any]]:
        """
        특정 턴 수정

        Args:
            script_list: 대본 리스트
            index: 수정할 인덱스
            text: 새 텍스트 (None이면 유지)
            role: 새 역할 (None이면 유지)
            emotion: 새 감정 (None이면 유지)

        Returns:
            수정된 대본 리스트
        """
        if index < 0 or index >= len(script_list):
            raise IndexError(f"인덱스 {index}가 범위를 벗어났습니다. (0-{len(script_list)-1})")

        result = [s.copy() for s in script_list]

        if text is not None:
            result[index]["text"] = text
        if role is not None:
            result[index]["role"] = role
        if emotion is not None:
            result[index]["emotion"] = emotion

        return result

    @staticmethod
    def insert_turn(script_list: List[Dict[str, Any]], index: int,
                    text: str, role: str = "narrator", emotion: str = "calm") -> List[Dict[str, Any]]:
        """
        특정 위치에 턴 삽입

        Args:
            script_list: 대본 리스트
            index: 삽입할 위치
            text: 텍스트
            role: 역할
            emotion: 감정

        Returns:
            수정된 대본 리스트
        """
        result = [s.copy() for s in script_list]
        new_turn = {"role": role, "text": text, "emotion": emotion}
        result.insert(index, new_turn)
        return result

    @staticmethod
    def delete_turn(script_list: List[Dict[str, Any]], index: int) -> List[Dict[str, Any]]:
        """
        특정 턴 삭제

        Args:
            script_list: 대본 리스트
            index: 삭제할 인덱스

        Returns:
            수정된 대본 리스트
        """
        if index < 0 or index >= len(script_list):
            raise IndexError(f"인덱스 {index}가 범위를 벗어났습니다.")

        result = [s.copy() for s in script_list]
        del result[index]
        return result

    @staticmethod
    def delete_range(script_list: List[Dict[str, Any]], start: int, end: int) -> List[Dict[str, Any]]:
        """
        범위 삭제

        Args:
            script_list: 대본 리스트
            start: 시작 인덱스
            end: 끝 인덱스 (포함)

        Returns:
            수정된 대본 리스트
        """
        result = [s.copy() for s in script_list]
        del result[start:end+1]
        return result

    @staticmethod
    def replace_emotion_bulk(script_list: List[Dict[str, Any]],
                             old_emotion: str, new_emotion: str) -> List[Dict[str, Any]]:
        """
        특정 감정을 일괄 변경

        Args:
            script_list: 대본 리스트
            old_emotion: 변경할 감정
            new_emotion: 새 감정

        Returns:
            수정된 대본 리스트
        """
        result = []
        for s in script_list:
            new_s = s.copy()
            if new_s.get("emotion") == old_emotion:
                new_s["emotion"] = new_emotion
            result.append(new_s)
        return result
