# src/modules_pro/script_utils.py
# ============================================================
# v56.1: 시나리오 유틸리티 클래스 모음
# scenario_planner.py에서 분리
# ============================================================
import os
import re
import json
import time
import random
import hashlib
import logging
from typing import Any, Callable, Optional

# 로거 설정
try:
    from utils.logger import get_logger
    logger = get_logger("script_utils")
except ImportError:
    logger = logging.getLogger("script_utils")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(handler)


# ============================================================
# 유틸리티 함수
# ============================================================
# v60.1.0: safe_print를 pipeline_utils 정식 버전으로 통합 (중복 제거)
from utils.runtime_utils import safe_print


def _safe_strip(s: str) -> str:
    """None 안전 strip"""
    return (s or "").strip()


def _first_line(text: str) -> str:
    """첫 번째 줄 추출"""
    t = _safe_strip(text).replace('"', "").replace("#", "")
    return t.split("\n")[0].strip()[:100] if t else ""


# ============================================================
# API 재시도 헬퍼
# ============================================================
class APIRetryHelper:
    """
    API 호출 재시도 헬퍼 클래스
    """

    @staticmethod
    def call_with_retry(
        func: Callable,
        *args,
        max_retries: int = 5,
        base_delay: float = 1.0,
        on_retry: Callable[[int, Exception], None] = None,
        **kwargs
    ) -> Any:
        """
        API 호출을 지수 백오프로 재시도

        Args:
            func: 호출할 함수
            max_retries: 최대 재시도 횟수
            base_delay: 기본 대기 시간
            on_retry: 재시도 시 호출할 콜백 (attempt, exception)
            *args, **kwargs: 함수에 전달할 인자

        Returns:
            함수 반환값
        """
        last_exception = None

        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt == max_retries - 1:
                    logger.error(f"API 호출 실패 (최대 재시도 도달): {e}")
                    raise

                delay = min(base_delay * (2 ** attempt), 60.0)
                delay = delay * (0.5 + random.random())  # 지터

                if on_retry:
                    on_retry(attempt + 1, e)

                logger.warning(f"API 재시도 {attempt + 1}/{max_retries}, {delay:.1f}초 대기")
                time.sleep(delay)

        raise last_exception


# ============================================================
# 진행률 콜백 시스템
# ============================================================
class ProgressCallback:
    """
    진행률 콜백 관리자
    GUI에서 진행 상황을 표시할 수 있도록 콜백 제공
    """

    def __init__(self):
        self._callback: Optional[Callable[[str, int, int, str], None]] = None
        self._current_step = 0
        self._total_steps = 10

    def set_callback(self, callback: Callable[[str, int, int, str], None]):
        """
        콜백 함수 설정

        Args:
            callback: (단계명, 현재단계, 총단계, 상세메시지) -> None
        """
        self._callback = callback

    def clear_callback(self):
        """콜백 해제"""
        self._callback = None

    def set_total_steps(self, total: int):
        """총 단계 수 설정"""
        self._total_steps = total
        self._current_step = 0

    def update(self, step_name: str, detail: str = ""):
        """
        진행 상황 업데이트

        Args:
            step_name: 현재 단계 이름
            detail: 상세 메시지
        """
        self._current_step += 1
        if self._callback:
            try:
                self._callback(step_name, self._current_step, self._total_steps, detail)
            except Exception as e:
                safe_print(f"[ProgressCallback] 콜백 오류: {e}")

        progress = int((self._current_step / self._total_steps) * 100)
        safe_print(f"[{progress}%] {step_name}" + (f" - {detail}" if detail else ""))

    def reset(self):
        """진행률 초기화"""
        self._current_step = 0


# 전역 진행률 콜백 인스턴스
progress_callback = ProgressCallback()


# ============================================================
# 다양성 메모리 (중복 방지)
# ============================================================
class DiversityMemory:
    """
    주제/스토리 중복 방지를 위한 메모리
    """

    def __init__(self, data_dir: str, filename: str = "diversity_memory.json", keep: int = 40):
        self.keep = keep
        self.path = os.path.join(data_dir, filename)
        self.data = {"topics": [], "fingerprints": []}
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
        except Exception:
            self.data = {"topics": [], "fingerprints": []}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError) as e:
            logging.getLogger(__name__).warning(f"[ScriptUtils] 토픽 메모리 저장 실패: {self.path}: {e}")

    @staticmethod
    def _fingerprint(text: str) -> str:
        base = " ".join(re.findall(r"[가-힣]{2,}", text or ""))[:220]
        return hashlib.md5(base.encode("utf-8")).hexdigest()

    def push(self, topic: str, story_bible: str):
        fp = self._fingerprint(topic + " " + story_bible)
        self.data["topics"].append(_safe_strip(topic)[:220])
        self.data["fingerprints"].append(fp)
        self.data["topics"] = self.data["topics"][-self.keep:]
        self.data["fingerprints"] = self.data["fingerprints"][-self.keep:]
        self.save()

    def is_similar(self, text: str) -> bool:
        fp = self._fingerprint(text)
        return fp in set(self.data.get("fingerprints", []))

    def get_bans_for_senior(self) -> str:
        recent = " ".join(self.data.get("topics", [])[-10:])
        terms = ["치매", "첫사랑", "마지막 소원", "병원", "재회", "유산", "불륜", "장례"]
        bans = []
        for t in terms:
            if t.replace(" ", "") in recent.replace(" ", ""):
                bans.append(t)
        bans = bans[:3]
        if not bans:
            return ""
        return " / ".join([f"'{b}' 패턴은 최근에 많이 사용됨 → 이번에는 피할 것" for b in bans])
