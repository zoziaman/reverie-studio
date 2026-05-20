"""
Reverie Studio GUI 자동 테스터 v1.0
====================================
실시간 GUI 테스트 + 오류 감지 + 자동 수정 루프

사용법:
    python tests/gui_auto_tester.py --test queue
    python tests/gui_auto_tester.py --test production
    python tests/gui_auto_tester.py --test all
"""

import os
import sys
import time
import json
import subprocess
import threading
import queue
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable, Tuple
from datetime import datetime
from enum import Enum

# 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import pyautogui
import psutil
from PIL import Image, ImageGrab

# PyAutoGUI 안전 설정
pyautogui.FAILSAFE = True  # 마우스를 좌상단으로 이동하면 중지
pyautogui.PAUSE = 0.3  # 각 동작 후 대기


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class TestResult:
    """테스트 결과"""
    name: str
    status: TestStatus
    message: str = ""
    screenshot_path: str = ""
    duration: float = 0.0
    error_log: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ButtonLocation:
    """버튼 위치 정보"""
    name: str
    x: int
    y: int
    width: int = 100
    height: int = 30

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class GUIAutoTester:
    """
    Reverie Studio GUI 자동 테스터

    기능:
    - GUI 프로세스 관리 (실행/종료)
    - 버튼 클릭 테스트
    - 콘솔 로그 실시간 모니터링
    - 오류 감지 및 자동 재시도
    - 스크린샷 기반 검증
    """

    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.gui_process: Optional[subprocess.Popen] = None
        self.log_queue = queue.Queue()
        self.log_thread: Optional[threading.Thread] = None
        self.is_monitoring = False

        # 테스트 결과 저장
        self.results: List[TestResult] = []

        # 버튼 위치 캐시 (수동 매핑 또는 이미지 검색)
        self.button_locations: Dict[str, ButtonLocation] = {}

        # 스크린샷 저장 경로
        self.screenshot_dir = PROJECT_ROOT / "tests" / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)

        # 설정 파일
        self.config_path = PROJECT_ROOT / "tests" / "gui_test_config.json"
        self._load_config()

    def _load_config(self):
        """버튼 위치 등 설정 로드"""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                for name, loc in config.get("buttons", {}).items():
                    self.button_locations[name] = ButtonLocation(
                        name=name, x=loc["x"], y=loc["y"],
                        width=loc.get("width", 100),
                        height=loc.get("height", 30)
                    )

    def _save_config(self):
        """설정 저장"""
        config = {
            "buttons": {
                name: {"x": loc.x, "y": loc.y, "width": loc.width, "height": loc.height}
                for name, loc in self.button_locations.items()
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    # ==================== 프로세스 관리 ====================

    def start_gui(self, wait_seconds: float = 5.0) -> bool:
        """GUI 프로세스 시작"""
        if self.gui_process and self.gui_process.poll() is None:
            print("[TESTER] GUI가 이미 실행 중입니다.")
            return True

        print("[TESTER] GUI 시작 중...")

        try:
            # GUI 실행
            gui_script = self.project_root / "src" / "gui" / "main_window.py"
            self.gui_process = subprocess.Popen(
                [sys.executable, str(gui_script)],
                cwd=str(self.project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONPATH": str(self.project_root / "src")}
            )

            # 로그 모니터링 시작
            self._start_log_monitor()

            # GUI 로딩 대기
            time.sleep(wait_seconds)

            if self.gui_process.poll() is None:
                print(f"[TESTER] GUI 시작 완료 (PID: {self.gui_process.pid})")
                return True
            else:
                print("[TESTER] GUI 시작 실패 - 프로세스 종료됨")
                return False

        except Exception as e:
            print(f"[TESTER] GUI 시작 오류: {e}")
            return False

    def stop_gui(self):
        """GUI 프로세스 종료"""
        self._stop_log_monitor()

        if self.gui_process:
            print("[TESTER] GUI 종료 중...")
            try:
                # 자식 프로세스까지 종료
                parent = psutil.Process(self.gui_process.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()

                self.gui_process.wait(timeout=5)
                print("[TESTER] GUI 종료 완료")
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                print(f"[TESTER] GUI 강제 종료: {e}")
                self.gui_process.kill()

            self.gui_process = None

    def restart_gui(self, wait_seconds: float = 5.0) -> bool:
        """GUI 재시작"""
        self.stop_gui()
        time.sleep(1)
        return self.start_gui(wait_seconds)

    # ==================== 로그 모니터링 ====================

    def _start_log_monitor(self):
        """콘솔 로그 모니터링 스레드 시작"""
        self.is_monitoring = True
        self.log_thread = threading.Thread(target=self._log_monitor_worker, daemon=True)
        self.log_thread.start()

    def _stop_log_monitor(self):
        """로그 모니터링 중지"""
        self.is_monitoring = False
        if self.log_thread:
            self.log_thread.join(timeout=2)
            self.log_thread = None

    def _log_monitor_worker(self):
        """로그 모니터링 워커"""
        while self.is_monitoring and self.gui_process:
            try:
                line = self.gui_process.stdout.readline()
                if line:
                    self.log_queue.put(line.strip())
                    # 오류 감지
                    if any(err in line.lower() for err in ["error", "exception", "traceback"]):
                        print(f"[LOG ERROR] {line.strip()}")
            except Exception:
                break

    def get_recent_logs(self, max_lines: int = 50) -> List[str]:
        """최근 로그 가져오기"""
        logs = []
        while not self.log_queue.empty() and len(logs) < max_lines:
            try:
                logs.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return logs

    def check_for_errors(self) -> Optional[str]:
        """로그에서 오류 확인"""
        logs = self.get_recent_logs()
        error_lines = [l for l in logs if any(err in l.lower() for err in ["error", "exception", "traceback"])]
        return "\n".join(error_lines) if error_lines else None

    # ==================== 화면 제어 ====================

    def take_screenshot(self, name: str = "screen") -> str:
        """스크린샷 촬영"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = self.screenshot_dir / filename

        screenshot = ImageGrab.grab()
        screenshot.save(filepath)

        print(f"[TESTER] 스크린샷 저장: {filepath}")
        return str(filepath)

    def find_button_by_image(self, image_path: str, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
        """이미지로 버튼 위치 찾기"""
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                return (center.x, center.y)
        except Exception as e:
            print(f"[TESTER] 버튼 이미지 검색 실패: {e}")
        return None

    def find_button_by_text(self, text: str) -> Optional[Tuple[int, int]]:
        """
        텍스트로 버튼 위치 찾기 (OCR)
        주의: pytesseract 설치 필요
        """
        try:
            import pytesseract

            screenshot = ImageGrab.grab()
            data = pytesseract.image_to_data(screenshot, lang='kor+eng', output_type=pytesseract.Output.DICT)

            for i, word in enumerate(data['text']):
                if text.lower() in word.lower():
                    x = data['left'][i] + data['width'][i] // 2
                    y = data['top'][i] + data['height'][i] // 2
                    return (x, y)
        except ImportError:
            print("[TESTER] pytesseract가 설치되지 않았습니다.")
        except Exception as e:
            print(f"[TESTER] OCR 검색 실패: {e}")

        return None

    def click_button(self, button_name: str) -> bool:
        """버튼 클릭"""
        # 1. 캐시된 위치 확인
        if button_name in self.button_locations:
            loc = self.button_locations[button_name]
            x, y = loc.center
            print(f"[TESTER] '{button_name}' 클릭 ({x}, {y})")
            pyautogui.click(x, y)
            return True

        # 2. 버튼 이미지로 검색
        button_image = self.project_root / "tests" / "button_images" / f"{button_name}.png"
        if button_image.exists():
            pos = self.find_button_by_image(str(button_image))
            if pos:
                print(f"[TESTER] '{button_name}' 이미지로 찾음 ({pos[0]}, {pos[1]})")
                pyautogui.click(pos[0], pos[1])
                # 위치 캐시
                self.button_locations[button_name] = ButtonLocation(button_name, pos[0]-50, pos[1]-15)
                self._save_config()
                return True

        # 3. 텍스트로 검색 (OCR)
        pos = self.find_button_by_text(button_name)
        if pos:
            print(f"[TESTER] '{button_name}' OCR로 찾음 ({pos[0]}, {pos[1]})")
            pyautogui.click(pos[0], pos[1])
            return True

        print(f"[TESTER] '{button_name}' 버튼을 찾을 수 없습니다.")
        return False

    def click_at(self, x: int, y: int):
        """좌표 클릭"""
        pyautogui.click(x, y)

    def type_text(self, text: str, interval: float = 0.05):
        """텍스트 입력"""
        pyautogui.typewrite(text, interval=interval)

    def press_key(self, key: str):
        """키 입력"""
        pyautogui.press(key)

    def wait(self, seconds: float):
        """대기"""
        time.sleep(seconds)

    # ==================== 테스트 실행 ====================

    def run_test(self, test_func: Callable, test_name: str, max_retries: int = 3) -> TestResult:
        """
        테스트 실행 (자동 재시도 포함)

        Args:
            test_func: 테스트 함수 (True/False 반환)
            test_name: 테스트 이름
            max_retries: 최대 재시도 횟수
        """
        print(f"\n{'='*50}")
        print(f"[TEST] {test_name} 시작")
        print(f"{'='*50}")

        for attempt in range(1, max_retries + 1):
            print(f"\n[ATTEMPT {attempt}/{max_retries}]")

            start_time = time.time()
            screenshot_path = ""
            error_log = ""

            try:
                # 테스트 실행
                success = test_func()
                duration = time.time() - start_time

                # 오류 로그 확인
                error_log = self.check_for_errors() or ""

                if success and not error_log:
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.PASSED,
                        message=f"성공 (시도 {attempt}회)",
                        duration=duration
                    )
                    print(f"[PASSED] {test_name} - {duration:.2f}초")
                    self.results.append(result)
                    return result
                else:
                    # 실패 시 스크린샷
                    screenshot_path = self.take_screenshot(f"fail_{test_name}")

                    if attempt < max_retries:
                        print(f"[RETRY] 오류 감지, GUI 재시작 후 재시도...")
                        self.restart_gui()

            except Exception as e:
                duration = time.time() - start_time
                error_log = str(e)
                screenshot_path = self.take_screenshot(f"error_{test_name}")

                print(f"[ERROR] {e}")

                if attempt < max_retries:
                    print(f"[RETRY] 예외 발생, GUI 재시작 후 재시도...")
                    self.restart_gui()

        # 모든 재시도 실패
        result = TestResult(
            name=test_name,
            status=TestStatus.FAILED,
            message=f"실패 ({max_retries}회 시도)",
            screenshot_path=screenshot_path,
            error_log=error_log,
            duration=duration
        )
        print(f"[FAILED] {test_name}")
        self.results.append(result)
        return result

    def run_test_suite(self, tests: List[Tuple[str, Callable]],
                       stop_on_fail: bool = False) -> List[TestResult]:
        """테스트 스위트 실행"""
        print(f"\n{'#'*60}")
        print(f"# 테스트 스위트 시작: {len(tests)}개 테스트")
        print(f"{'#'*60}")

        # GUI 시작
        if not self.start_gui():
            print("[SUITE] GUI 시작 실패")
            return []

        results = []

        try:
            for test_name, test_func in tests:
                result = self.run_test(test_func, test_name)
                results.append(result)

                if stop_on_fail and result.status != TestStatus.PASSED:
                    print("[SUITE] 테스트 실패로 중단")
                    break
        finally:
            self.stop_gui()

        # 결과 요약
        self._print_summary(results)

        return results

    def _print_summary(self, results: List[TestResult]):
        """테스트 결과 요약 출력"""
        passed = sum(1 for r in results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)

        print(f"\n{'='*60}")
        print(f"테스트 결과 요약")
        print(f"{'='*60}")
        print(f"  통과: {passed}")
        print(f"  실패: {failed}")
        print(f"  오류: {errors}")
        print(f"  전체: {len(results)}")
        print(f"{'='*60}")

        if failed + errors > 0:
            print("\n실패/오류 목록:")
            for r in results:
                if r.status != TestStatus.PASSED:
                    print(f"  - {r.name}: {r.message}")
                    if r.error_log:
                        print(f"    로그: {r.error_log[:200]}...")

    # ==================== 버튼 위치 캘리브레이션 ====================

    def calibrate_button(self, button_name: str):
        """
        버튼 위치 수동 캘리브레이션
        마우스를 버튼 위에 올리고 Enter 누르면 위치 저장
        """
        print(f"\n[CALIBRATE] '{button_name}' 버튼 위에 마우스를 올리고 Enter를 누르세요...")
        input()

        x, y = pyautogui.position()
        self.button_locations[button_name] = ButtonLocation(button_name, x-50, y-15)
        self._save_config()

        print(f"[CALIBRATE] '{button_name}' 저장됨: ({x}, {y})")

    def calibrate_all_buttons(self):
        """모든 주요 버튼 캘리브레이션"""
        buttons = [
            "채널선택",
            "팩선택",
            "큐에추가",
            "큐실행",
            "생산시작",
            "썸네일건너뛰기",
            "자동업로드",
            "토픽입력"
        ]

        print("\n=== 버튼 캘리브레이션 모드 ===")
        print("각 버튼 위에 마우스를 올리고 Enter를 누르세요.\n")

        for btn in buttons:
            self.calibrate_button(btn)

        print("\n[CALIBRATE] 완료! 설정 저장됨.")


# ==================== 테스트 시나리오 ====================

class ReverieGUITests:
    """Reverie Studio GUI 테스트 시나리오"""

    def __init__(self, tester: GUIAutoTester):
        self.tester = tester

    def test_queue_add(self) -> bool:
        """큐 추가 테스트"""
        print("[TEST] 큐 추가 테스트")

        # 1. 채널 선택
        self.tester.click_button("채널선택")
        self.tester.wait(0.5)
        self.tester.press_key("down")
        self.tester.press_key("enter")

        # 2. 옵션 체크
        self.tester.click_button("썸네일건너뛰기")
        self.tester.wait(0.3)
        self.tester.click_button("자동업로드")
        self.tester.wait(0.3)

        # 3. 큐에 추가
        self.tester.click_button("큐에추가")
        self.tester.wait(1)

        # 4. 검증 - 큐 파일 확인
        queue_file = self.tester.project_root / "data" / "batch_queue.json"
        if queue_file.exists():
            with open(queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("jobs"):
                    print(f"[TEST] 큐에 {len(data['jobs'])}개 작업 추가됨")
                    return True

        return False

    def test_queue_options_saved(self) -> bool:
        """큐 옵션 저장 테스트"""
        print("[TEST] 큐 옵션 저장 테스트")

        queue_file = self.tester.project_root / "data" / "batch_queue.json"
        if not queue_file.exists():
            return False

        with open(queue_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data.get("jobs"):
            return False

        latest_job = data["jobs"][-1]

        # 옵션 확인
        checks = [
            ("skip_thumbnail" in latest_job, "skip_thumbnail 필드 존재"),
            ("upload_privacy" in latest_job, "upload_privacy 필드 존재"),
            ("pack_id" in latest_job, "pack_id 필드 존재"),
        ]

        for check, desc in checks:
            if not check:
                print(f"[TEST] 실패: {desc}")
                return False
            print(f"[TEST] 통과: {desc}")

        return True

    def test_production_start(self) -> bool:
        """생산 시작 테스트 (5초 후 중단)"""
        print("[TEST] 생산 시작 테스트")

        # 1. 생산 시작 클릭
        self.tester.click_button("생산시작")

        # 2. 5초 대기
        self.tester.wait(5)

        # 3. 오류 확인
        error = self.tester.check_for_errors()
        if error:
            print(f"[TEST] 오류 발생: {error}")
            return False

        # 4. ESC로 중단
        self.tester.press_key("escape")

        return True


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Reverie Studio GUI 자동 테스터")
    parser.add_argument("--test", choices=["queue", "production", "all", "calibrate"],
                        default="all", help="실행할 테스트")
    parser.add_argument("--retries", type=int, default=3, help="최대 재시도 횟수")

    args = parser.parse_args()

    tester = GUIAutoTester()
    tests = ReverieGUITests(tester)

    if args.test == "calibrate":
        # 버튼 캘리브레이션
        if not tester.start_gui():
            print("GUI 시작 실패")
            return

        try:
            tester.calibrate_all_buttons()
        finally:
            tester.stop_gui()

    elif args.test == "queue":
        tester.run_test_suite([
            ("큐 추가", tests.test_queue_add),
            ("큐 옵션 저장", tests.test_queue_options_saved),
        ])

    elif args.test == "production":
        tester.run_test_suite([
            ("생산 시작", tests.test_production_start),
        ])

    elif args.test == "all":
        tester.run_test_suite([
            ("큐 추가", tests.test_queue_add),
            ("큐 옵션 저장", tests.test_queue_options_saved),
            ("생산 시작", tests.test_production_start),
        ])


if __name__ == "__main__":
    main()
