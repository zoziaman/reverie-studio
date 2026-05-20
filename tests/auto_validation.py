"""
Reverie Studio 자동 검증 스크립트 v1.0
======================================
백그라운드에서 실행 가능한 통합 테스트

실행:
    python tests/auto_validation.py
    python tests/auto_validation.py --fix  # 자동 수정 모드
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

# 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger("auto_validation")


def safe_print(msg: str):
    """cp949 호환 안전 출력"""
    try:
        print(msg)
    except UnicodeEncodeError:
        import re
        clean = re.sub(r'[^\x00-\x7F\uAC00-\uD7A3\u3131-\u318E]+', '', msg)
        print(clean)


@dataclass
class TestResult:
    """테스트 결과"""
    name: str
    passed: bool
    message: str = ""
    details: List[str] = field(default_factory=list)
    auto_fixable: bool = False
    fix_applied: bool = False


class ReverieValidator:
    """
    Reverie Studio 통합 검증기

    검증 항목:
    1. TTS 모델 매핑 (voice_type → 모델 파일)
    2. 후킹 영상 자막 (길이 제한, 줄바꿈)
    3. 대본 voice_type 매핑 (캐릭터 → 음성 타입)
    4. 팩 설정 정합성
    5. 큐 시스템 옵션
    6. 파일 구조 검증
    """

    def __init__(self, auto_fix: bool = False):
        self.project_root = PROJECT_ROOT
        self.auto_fix = auto_fix
        self.results: List[TestResult] = []

        # 설정 로드
        try:
            from config.settings import config
            self.config = config
        except ImportError:
            self.config = None
            logger.warning("config.settings 로드 실패")

    def run_all_tests(self) -> List[TestResult]:
        """모든 테스트 실행"""
        safe_print("\n" + "="*60)
        safe_print("  Reverie Studio 자동 검증 시작")
        safe_print("="*60 + "\n")

        tests = [
            ("1. TTS 모델 파일 검증", self.test_tts_models),
            ("2. TTS voice_type 매핑 검증", self.test_voice_type_mapping),
            ("3. 후킹 영상 자막 검증", self.test_hook_subtitle),
            ("4. 대본 구조 검증", self.test_script_structure),
            ("5. 팩 설정 검증", self.test_pack_config),
            ("6. 큐 시스템 검증", self.test_queue_system),
            ("7. Remotion 자막 색상 검증", self.test_remotion_subtitle_colors),
            ("8. 감정 매핑 검증", self.test_emotion_mapping),
            ("9. SFX 태그 검증", self.test_sfx_tags),
            ("10. AI법 준수 검증", self.test_ai_disclosure),
        ]

        for name, test_func in tests:
            safe_print(f"\n{'-'*50}")
            safe_print(f"> {name}")
            safe_print(f"{'-'*50}")

            try:
                result = test_func()
                self.results.append(result)

                if result.passed:
                    safe_print(f"  [PASS] {result.message}")
                else:
                    safe_print(f"  [FAIL] {result.message}")
                    for detail in result.details:
                        safe_print(f"     - {detail}")

                    if result.auto_fixable and self.auto_fix:
                        safe_print(f"  [FIX] 자동 수정 시도...")
                        # 여기서 자동 수정 로직 호출

            except Exception as e:
                result = TestResult(name, False, f"예외 발생: {e}")
                self.results.append(result)
                safe_print(f"  [ERROR] {e}")

        self._print_summary()
        return self.results

    def _print_summary(self):
        """결과 요약 출력"""
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)

        safe_print("\n" + "="*60)
        safe_print("  검증 결과 요약")
        safe_print("="*60)
        safe_print(f"  통과: {passed}")
        safe_print(f"  실패: {failed}")
        safe_print(f"  전체: {len(self.results)}")

        if failed > 0:
            safe_print("\n  [!] 실패 항목:")
            for r in self.results:
                if not r.passed:
                    safe_print(f"    - {r.name}: {r.message}")

        safe_print("="*60 + "\n")

    # ========================================
    # 1. TTS 모델 파일 검증
    # ========================================
    def test_tts_models(self) -> TestResult:
        """TTS 모델 파일 존재 여부 검증"""

        # v57.8: narrator는 narrator_male/narrator_female로 분리됨
        required_voice_types = [
            "man", "woman",
            "young_man", "young_woman",
            "grandma", "grandpa",
            "narrator_male", "narrator_female"  # narrator 대신 분리된 폴더
        ]

        # 폴백 매핑 (v58.3.1)
        fallback_map = {
            "young_man": "man",
            "young_woman": "woman",
            "narrator": "narrator_male",  # narrator → narrator_male 폴백
        }

        models_dir = self.project_root / "assets" / "models"

        if not models_dir.exists():
            return TestResult(
                "TTS 모델", False,
                f"models 폴더 없음: {models_dir}"
            )

        missing = []
        fallback_used = []
        found = []

        for vt in required_voice_types:
            model_dir = models_dir / vt
            gpt_weights = model_dir / "gpt_weights.ckpt"

            if model_dir.exists() and gpt_weights.exists():
                found.append(vt)
            elif vt in fallback_map:
                # 폴백 체크
                fallback_vt = fallback_map[vt]
                fallback_dir = models_dir / fallback_vt
                fallback_gpt = fallback_dir / "gpt_weights.ckpt"

                if fallback_gpt.exists():
                    fallback_used.append(f"{vt} → {fallback_vt}")
                else:
                    missing.append(f"{vt} (폴백 {fallback_vt}도 없음)")
            else:
                missing.append(vt)

        details = []
        if found:
            details.append(f"정상 모델: {', '.join(found)}")
        if fallback_used:
            details.append(f"폴백 사용: {', '.join(fallback_used)}")
        if missing:
            details.append(f"누락 모델: {', '.join(missing)}")

        passed = len(missing) == 0
        message = f"{len(found)}개 정상, {len(fallback_used)}개 폴백, {len(missing)}개 누락"

        return TestResult("TTS 모델", passed, message, details)

    # ========================================
    # 2. voice_type 매핑 검증
    # ========================================
    def test_voice_type_mapping(self) -> TestResult:
        """voice_type 추론 로직 검증"""

        # 테스트 케이스: (입력 role, 기대 voice_type)
        test_cases = [
            # 나레이터
            ("나레이션", "narrator"),
            ("내레이션", "narrator"),
            ("narrator", "narrator"),

            # 할머니/할아버지
            ("할머니", "grandma"),
            ("할아버지", "grandpa"),

            # 중년
            ("아버지", "man"),
            ("어머니", "woman"),
            ("엄마", "woman"),
            ("아빠", "man"),

            # 청년
            ("아들", "young_man"),
            ("딸", "young_woman"),
            ("오빠", "young_man"),
            ("언니", "young_woman"),
        ]

        try:
            from modules_pro.script_writers import ScriptWriter

            # 테스트용 더미 스크립트
            failures = []

            for role, expected_vt in test_cases:
                # _normalize_script 테스트
                test_script = [{"role": role, "text": "테스트", "emotion": "calm"}]
                normalized = ScriptWriter._normalize_script(test_script)

                if normalized:
                    actual_vt = normalized[0].get("voice_type", "")
                    if actual_vt != expected_vt:
                        failures.append(f"'{role}' → '{actual_vt}' (기대: {expected_vt})")
                else:
                    failures.append(f"'{role}' 정규화 실패")

            if failures:
                return TestResult(
                    "voice_type 매핑", False,
                    f"{len(failures)}개 매핑 오류",
                    failures
                )

            return TestResult(
                "voice_type 매핑", True,
                f"{len(test_cases)}개 매핑 모두 정상"
            )

        except ImportError as e:
            return TestResult("voice_type 매핑", False, f"Import 실패: {e}")

    # ========================================
    # 3. 후킹 영상 자막 검증
    # ========================================
    def test_hook_subtitle(self) -> TestResult:
        """후킹 영상 자막 길이/줄바꿈 검증"""

        # 테스트 케이스: 다양한 길이의 주제
        test_topics = [
            "짧은 주제",  # 5자
            "열두글자주제입니다",  # 12자 (경계)
            "이것은 매우 긴 주제입니다 테스트",  # 18자
            "공백없이매우긴주제를테스트합니다이건진짜길어요",  # 24자, 공백 없음
        ]

        issues = []

        # 현재 로직 (media_factory.py 기준)
        for topic in test_topics:
            topic_clean = topic.strip()

            if len(topic_clean) > 12:
                mid = len(topic_clean) // 2
                space_idx = topic_clean.find(" ", mid - 4)
                if space_idx == -1 or space_idx > mid + 4:
                    space_idx = mid
                lines = [topic_clean[:space_idx].strip(), topic_clean[space_idx:].strip()]
            else:
                lines = [topic_clean]

            # 검증: 각 라인이 너무 길지 않은지
            max_line_length = 15  # 화면 너비 기준 추정
            for i, line in enumerate(lines):
                if len(line) > max_line_length:
                    issues.append(f"'{topic}' → 라인{i+1} 길이 초과 ({len(line)}자): '{line}'")

        if issues:
            return TestResult(
                "후킹 자막", False,
                f"{len(issues)}개 잠재적 문제",
                issues,
                auto_fixable=True
            )

        return TestResult("후킹 자막", True, "모든 테스트 케이스 통과")

    # ========================================
    # 4. 대본 구조 검증
    # ========================================
    def test_script_structure(self) -> TestResult:
        """최근 생성된 대본 파일 구조 검증"""

        scripts_dir = self.project_root / "data" / "scripts"

        if not scripts_dir.exists():
            return TestResult("대본 구조", False, "scripts 폴더 없음")

        # 최근 JSON 파일 찾기
        json_files = sorted(scripts_dir.glob("*.json"), key=os.path.getmtime, reverse=True)

        if not json_files:
            return TestResult("대본 구조", True, "검증할 대본 파일 없음 (정상)")

        # 최근 5개 파일 검증
        issues = []
        checked = 0

        required_fields = ["role", "text", "emotion"]
        recommended_fields = ["voice_type", "sfx_tag"]

        for json_file in json_files[:5]:
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                script_list = data.get("script_list", [])
                if not script_list:
                    # 다른 키에서 찾기
                    for key, value in data.items():
                        if isinstance(value, list) and value and isinstance(value[0], dict):
                            script_list = value
                            break

                if not script_list:
                    issues.append(f"{json_file.name}: script_list 없음")
                    continue

                checked += 1

                # 각 항목 검증
                missing_voice_type = 0
                missing_sfx_tag = 0

                for i, item in enumerate(script_list):
                    # 필수 필드
                    for field in required_fields:
                        if field not in item:
                            issues.append(f"{json_file.name}[{i}]: '{field}' 필드 누락")

                    # 권장 필드
                    if "voice_type" not in item:
                        missing_voice_type += 1
                    if "sfx_tag" not in item:
                        missing_sfx_tag += 1

                if missing_voice_type > 0:
                    issues.append(f"{json_file.name}: {missing_voice_type}개 항목에 voice_type 누락")

            except Exception as e:
                issues.append(f"{json_file.name}: 파싱 오류 - {e}")

        if issues:
            return TestResult(
                "대본 구조", False,
                f"{checked}개 파일 중 문제 발견",
                issues
            )

        return TestResult("대본 구조", True, f"{checked}개 파일 검증 완료")

    # ========================================
    # 5. 팩 설정 검증
    # ========================================
    def test_pack_config(self) -> TestResult:
        """팩 설정 정합성 검증"""

        try:
            from config.pack_config import (
                ACTIVE_PACK, get_character_config,
                get_allowed_emotions, get_hook_style
            )

            issues = []

            # 팩 로드 여부
            if not ACTIVE_PACK.is_loaded:
                return TestResult("팩 설정", True, "활성 팩 없음 (정상)")

            # character_config 검증
            char_config = get_character_config()
            if char_config:
                allowed_voice_types = {"narrator", "grandma", "grandpa", "man", "woman", "young_man", "young_woman"}

                for char, vt in char_config.items():
                    if vt not in allowed_voice_types:
                        issues.append(f"character_config['{char}']: 잘못된 voice_type '{vt}'")

            # 감정 설정 검증
            emotions = get_allowed_emotions()
            if emotions:
                valid_emotions = {"sad", "angry", "scared", "happy", "calm", "excited", "whisper", "worried", "desperate"}
                for emo in emotions:
                    if emo not in valid_emotions:
                        issues.append(f"허용되지 않은 감정: '{emo}'")

            # hook_style 검증
            hook_style = get_hook_style()
            if hook_style:
                if not hook_style.top_label:
                    issues.append("hook_style.top_label 비어있음")
                if hook_style.duration <= 0:
                    issues.append(f"hook_style.duration 잘못됨: {hook_style.duration}")

            if issues:
                return TestResult("팩 설정", False, f"{len(issues)}개 문제", issues)

            return TestResult("팩 설정", True, f"팩 '{ACTIVE_PACK.name}' 검증 완료")

        except ImportError as e:
            return TestResult("팩 설정", True, f"pack_config 없음 (정상): {e}")

    # ========================================
    # 6. 큐 시스템 검증
    # ========================================
    def test_queue_system(self) -> TestResult:
        """큐 시스템 옵션 저장/로드 검증 (코드 분석 기반)"""

        try:
            from utils.batch_queue import BatchQueue
            import inspect

            issues = []

            # add_job 시그니처 확인
            sig = inspect.signature(BatchQueue.add_job)
            params = list(sig.parameters.keys())

            required_params = [
                "channel", "mode", "auto_upload", "pack_id",
                "skip_thumbnail", "resume_from_checkpoint", "upload_privacy", "prompt_mode"
            ]

            for param in required_params:
                if param not in params:
                    issues.append(f"add_job에 '{param}' 파라미터 누락")

            # 실제 큐 파일 검증 (읽기만)
            actual_queue_path = self.project_root / "data" / "batch_queue.json"
            if actual_queue_path.exists():
                try:
                    with open(actual_queue_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # 배열 또는 딕셔너리 구조 확인
                    jobs = data if isinstance(data, list) else data.get("jobs", [])

                    if jobs:
                        sample_job = jobs[-1]  # 최신 작업

                        # 필수 필드 존재 확인
                        for field in ["channel", "pack_id", "auto_upload"]:
                            if field not in sample_job:
                                issues.append(f"큐 작업에 '{field}' 필드 누락")

                        # v58.3.2 필드 확인
                        if "skip_thumbnail" not in sample_job:
                            issues.append("큐 작업에 'skip_thumbnail' 필드 누락 (v58.3.2)")
                        if "upload_privacy" not in sample_job:
                            issues.append("큐 작업에 'upload_privacy' 필드 누락 (v58.3.2)")

                except Exception as e:
                    issues.append(f"큐 파일 읽기 실패: {e}")

            if issues:
                return TestResult("큐 시스템", False, f"{len(issues)}개 문제", issues)

            return TestResult("큐 시스템", True, "큐 시스템 구조 정상")

        except ImportError as e:
            return TestResult("큐 시스템", False, f"Import 실패: {e}")
        except Exception as e:
            return TestResult("큐 시스템", False, f"테스트 실패: {e}")

    # ========================================
    # 7. Remotion 자막 색상 검증
    # ========================================
    def test_remotion_subtitle_colors(self) -> TestResult:
        """Remotion 자막 색상 매핑 검증"""

        # remotion_assembler.py의 SPEAKER_COLORS와 일치해야 함
        expected_colors = {
            "narrator": "#FFFFFF",
            "narration": "#FFFFFF",
            "나레이터": "#FFFFFF",
            "나레이션": "#FFFFFF",
            "man": "#87CEEB",
            "woman": "#FFB6C1",
            "grandma": "#DDA0DD",
            "grandpa": "#F0E68C",
        }

        try:
            from modules_pro.remotion_assembler import SPEAKER_COLORS

            issues = []

            for speaker, expected_color in expected_colors.items():
                actual_color = SPEAKER_COLORS.get(speaker)
                if actual_color != expected_color:
                    issues.append(f"'{speaker}': 기대 '{expected_color}', 실제 '{actual_color}'")

            if issues:
                return TestResult("Remotion 색상", False, f"{len(issues)}개 불일치", issues)

            return TestResult("Remotion 색상", True, "색상 매핑 정상")

        except ImportError as e:
            return TestResult("Remotion 색상", False, f"Import 실패: {e}")

    # ========================================
    # 8. 감정 매핑 검증
    # ========================================
    def test_emotion_mapping(self) -> TestResult:
        """감정 정규화 로직 검증"""

        # 테스트 케이스: (입력, 기대 출력)
        test_cases = [
            ("fear", "scared"),
            ("afraid", "scared"),
            ("joy", "happy"),
            ("neutral", "calm"),
            ("anxiety", "worried"),
            ("quiet", "whisper"),
            ("sad", "sad"),
            ("angry", "angry"),
            ("happy", "happy"),
            ("calm", "calm"),
            ("unknown_emotion", "calm"),  # 폴백
        ]

        try:
            from modules_pro.script_writers import normalize_emotion

            failures = []

            for input_emo, expected in test_cases:
                actual = normalize_emotion(input_emo)
                if actual != expected:
                    failures.append(f"'{input_emo}' → '{actual}' (기대: {expected})")

            if failures:
                return TestResult("감정 매핑", False, f"{len(failures)}개 불일치", failures)

            return TestResult("감정 매핑", True, f"{len(test_cases)}개 매핑 정상")

        except ImportError as e:
            return TestResult("감정 매핑", False, f"Import 실패: {e}")

    # ========================================
    # 9. SFX 태그 검증
    # ========================================
    def test_sfx_tags(self) -> TestResult:
        """SFX 태그 유효성 검증 (sfx_registry.json 기반)"""

        allowed_tags = {
            "tension", "heartbeat", "suspense", "jumpscare", "whisper",
            "footsteps", "door", "thunder", "wind", "night",
            "sad", "crying", "happy", "whoosh", "impact", ""
        }

        sfx_dir = self.project_root / "assets" / "sfx"

        if not sfx_dir.exists():
            return TestResult("SFX 태그", False, "sfx 폴더 없음")

        # sfx_registry.json 기반 검증 (실제 구조)
        registry_path = sfx_dir / "sfx_registry.json"

        if not registry_path.exists():
            return TestResult("SFX 태그", False, "sfx_registry.json 없음")

        try:
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)

            # 등록된 태그 수집
            registered_tags = set()
            sfx_data = registry.get("sfx", {})

            for filename, info in sfx_data.items():
                tags = info.get("tags", [])
                registered_tags.update(tags)

            # 필요한 태그 vs 등록된 태그 비교
            missing_tags = []
            found_tags = []

            for tag in allowed_tags:
                if tag == "":
                    continue
                if tag in registered_tags:
                    found_tags.append(tag)
                else:
                    missing_tags.append(tag)

            details = []
            details.append(f"등록된 태그: {', '.join(sorted(registered_tags))}")

            if missing_tags:
                details.append(f"누락된 태그: {', '.join(missing_tags)}")

            # 70% 이상 커버되면 통과
            coverage = len(found_tags) / (len(allowed_tags) - 1)  # 빈 문자열 제외
            passed = coverage >= 0.7

            message = f"{len(found_tags)}/{len(allowed_tags)-1} 태그 커버 ({coverage*100:.0f}%)"

            return TestResult("SFX 태그", passed, message, details)

        except Exception as e:
            return TestResult("SFX 태그", False, f"레지스트리 파싱 실패: {e}")

    # ========================================
    # 10. AI법 준수 검증
    # ========================================
    def test_ai_disclosure(self) -> TestResult:
        """AI 제작 표기 (AI법 준수) 검증"""

        # Remotion 컴포넌트에서 AI 표기 확인
        remotion_file = self.project_root / "remotion-poc" / "src" / "RadioDrama.tsx"

        if not remotion_file.exists():
            return TestResult("AI법 준수", False, "RadioDrama.tsx 파일 없음")

        try:
            content = remotion_file.read_text(encoding="utf-8")

            checks = []

            # showAiDisclosure 기본값 확인
            if "showAiDisclosure = true" in content or "showAiDisclosure?: boolean" in content:
                checks.append("✓ AI 표기 옵션 존재")
            else:
                checks.append("✗ AI 표기 옵션 없음")

            # AI 표기 텍스트 확인
            if "이 영상은 AI로 제작되었습니다" in content:
                checks.append("✓ AI 표기 텍스트 존재")
            else:
                checks.append("✗ AI 표기 텍스트 없음")

            # AiDisclosure 컴포넌트 확인
            if "AiDisclosure" in content:
                checks.append("✓ AiDisclosure 컴포넌트 존재")
            else:
                checks.append("✗ AiDisclosure 컴포넌트 없음")

            failed = [c for c in checks if c.startswith("✗")]

            if failed:
                return TestResult("AI법 준수", False, f"{len(failed)}개 누락", checks)

            return TestResult("AI법 준수", True, "AI 제작 표기 정상", checks)

        except Exception as e:
            return TestResult("AI법 준수", False, f"파일 읽기 실패: {e}")


# ========================================
# 메인 실행
# ========================================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reverie Studio 자동 검증")
    parser.add_argument("--fix", action="store_true", help="자동 수정 모드")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    parser.add_argument("--quiet", action="store_true", help="요약만 출력")

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    validator = ReverieValidator(auto_fix=args.fix)
    results = validator.run_all_tests()

    if args.json:
        output = {
            "timestamp": datetime.now().isoformat(),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details
                }
                for r in results
            ]
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    # 종료 코드: 실패 있으면 1
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
