"""
Claude GUI 테스트 러너 v1.0
============================
Claude가 직접 실행하여 GUI를 테스트하고
오류 발생 시 자동 수정 → 재테스트 무한 루프

사용법:
    python tests/claude_gui_runner.py
"""

import os
import sys
import time
import json
import subprocess
import threading
import queue
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime

# 경로 설정
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pyautogui
import psutil
from PIL import ImageGrab

# 안전 설정
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2


class ClaudeGUIRunner:
    """
    Claude가 직접 사용하는 GUI 테스트 러너

    특징:
    - 간단한 API로 GUI 제어
    - 실시간 오류 감지
    - 상세 로그 출력 (Claude가 분석 가능)
    - 스크린샷 자동 저장
    """

    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.gui_process: Optional[subprocess.Popen] = None
        self.log_lines: List[str] = []
        self.error_lines: List[str] = []
        self._log_thread: Optional[threading.Thread] = None
        self._monitoring = False

        # 스크린샷 경로
        self.screenshot_dir = PROJECT_ROOT / "tests" / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)

        # 버튼 위치 (나중에 calibrate로 설정)
        self.buttons: Dict[str, Tuple[int, int]] = self._load_buttons()

    def _load_buttons(self) -> Dict[str, Tuple[int, int]]:
        """저장된 버튼 위치 로드"""
        config_path = PROJECT_ROOT / "tests" / "gui_test_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return {
                    name: (loc["x"] + loc.get("width", 100)//2,
                           loc["y"] + loc.get("height", 30)//2)
                    for name, loc in config.get("buttons", {}).items()
                }
        return {}

    # ==================== GUI 프로세스 관리 ====================

    def start(self, wait: float = 5.0) -> bool:
        """
        GUI 시작

        Returns:
            bool: 성공 여부
        """
        if self.gui_process and self.gui_process.poll() is None:
            print("[RUNNER] GUI 이미 실행 중")
            return True

        print("[RUNNER] GUI 시작...")
        self.log_lines = []
        self.error_lines = []

        try:
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
            self._start_monitoring()

            time.sleep(wait)

            if self.gui_process.poll() is None:
                print(f"[RUNNER] GUI 시작 완료 (PID: {self.gui_process.pid})")
                return True
            else:
                print("[RUNNER] GUI 시작 실패")
                self._print_errors()
                return False

        except Exception as e:
            print(f"[RUNNER] 오류: {e}")
            return False

    def stop(self):
        """GUI 종료"""
        self._stop_monitoring()

        if self.gui_process:
            print("[RUNNER] GUI 종료...")
            try:
                parent = psutil.Process(self.gui_process.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
                self.gui_process.wait(timeout=3)
            except:
                if self.gui_process:
                    self.gui_process.kill()

            self.gui_process = None
            print("[RUNNER] GUI 종료 완료")

    def restart(self, wait: float = 5.0) -> bool:
        """GUI 재시작"""
        self.stop()
        time.sleep(1)
        return self.start(wait)

    # ==================== 로그 모니터링 ====================

    def _start_monitoring(self):
        self._monitoring = True
        self._log_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self._log_thread.start()

    def _stop_monitoring(self):
        self._monitoring = False
        if self._log_thread:
            self._log_thread.join(timeout=1)

    def _monitor_worker(self):
        while self._monitoring and self.gui_process:
            try:
                line = self.gui_process.stdout.readline()
                if line:
                    line = line.strip()
                    self.log_lines.append(line)

                    # 오류 감지
                    if any(x in line.lower() for x in ["error", "exception", "traceback", "failed"]):
                        self.error_lines.append(line)
                        print(f"[ERROR] {line}")

                    # 최근 로그만 유지 (메모리)
                    if len(self.log_lines) > 1000:
                        self.log_lines = self.log_lines[-500:]

            except:
                break

    def has_errors(self) -> bool:
        """오류 발생 여부"""
        return len(self.error_lines) > 0

    def get_errors(self) -> List[str]:
        """오류 목록"""
        return self.error_lines.copy()

    def clear_errors(self):
        """오류 목록 초기화"""
        self.error_lines = []

    def _print_errors(self):
        """오류 출력"""
        if self.error_lines:
            print("\n=== 오류 로그 ===")
            for line in self.error_lines[-20:]:
                print(f"  {line}")
            print("================\n")

    # ==================== 화면 제어 ====================

    def click(self, button_name: str) -> bool:
        """
        버튼 클릭

        Args:
            button_name: 버튼 이름 (calibrate로 등록)

        Returns:
            bool: 성공 여부
        """
        if button_name not in self.buttons:
            print(f"[RUNNER] 버튼 '{button_name}' 미등록. calibrate 필요")
            return False

        x, y = self.buttons[button_name]
        print(f"[RUNNER] '{button_name}' 클릭 ({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(0.3)
        return True

    def click_at(self, x: int, y: int):
        """좌표 직접 클릭"""
        print(f"[RUNNER] 클릭 ({x}, {y})")
        pyautogui.click(x, y)
        time.sleep(0.3)

    def type_text(self, text: str):
        """텍스트 입력 (한글 미지원, 영문만)"""
        print(f"[RUNNER] 입력: {text}")
        pyautogui.typewrite(text, interval=0.05)

    def press(self, key: str):
        """키 입력 (enter, escape, tab, down, up 등)"""
        print(f"[RUNNER] 키: {key}")
        pyautogui.press(key)
        time.sleep(0.2)

    def wait(self, seconds: float):
        """대기"""
        time.sleep(seconds)

    def screenshot(self, name: str = "screen") -> str:
        """스크린샷 촬영 및 저장"""
        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = self.screenshot_dir / filename

        img = ImageGrab.grab()
        img.save(filepath)

        print(f"[RUNNER] 스크린샷: {filepath}")
        return str(filepath)

    def mouse_position(self) -> Tuple[int, int]:
        """현재 마우스 위치"""
        return pyautogui.position()

    # ==================== 버튼 캘리브레이션 ====================

    def calibrate(self, button_name: str):
        """
        버튼 위치 등록
        마우스를 버튼 위로 이동 후 Enter
        """
        print(f"[CALIBRATE] '{button_name}' 버튼 위에 마우스를 올리고 Enter...")
        input()
        x, y = pyautogui.position()
        self.buttons[button_name] = (x, y)
        self._save_buttons()
        print(f"[CALIBRATE] '{button_name}' = ({x}, {y})")

    def _save_buttons(self):
        """버튼 위치 저장"""
        config_path = PROJECT_ROOT / "tests" / "gui_test_config.json"
        config = {"buttons": {}}

        for name, (x, y) in self.buttons.items():
            config["buttons"][name] = {"x": x-50, "y": y-15, "width": 100, "height": 30}

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def list_buttons(self):
        """등록된 버튼 목록"""
        print("\n=== 등록된 버튼 ===")
        for name, (x, y) in self.buttons.items():
            print(f"  {name}: ({x}, {y})")
        print("==================\n")

    # ==================== 테스트 헬퍼 ====================

    def verify_queue_job(self) -> Optional[Dict]:
        """큐에 추가된 최신 작업 확인"""
        queue_file = self.project_root / "data" / "batch_queue.json"
        if not queue_file.exists():
            return None

        with open(queue_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        jobs = data.get("jobs", [])
        if jobs:
            return jobs[-1]
        return None

    def clear_queue(self):
        """큐 초기화"""
        queue_file = self.project_root / "data" / "batch_queue.json"
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump({"jobs": [], "history": []}, f)
        print("[RUNNER] 큐 초기화 완료")

    def status(self) -> Dict:
        """현재 상태"""
        return {
            "gui_running": self.gui_process is not None and self.gui_process.poll() is None,
            "pid": self.gui_process.pid if self.gui_process else None,
            "error_count": len(self.error_lines),
            "log_lines": len(self.log_lines),
            "buttons_registered": len(self.buttons)
        }


# ==================== 사용 예시 ====================

def example_test():
    """
    테스트 예시

    Claude가 이 패턴으로 테스트 실행:
    1. runner.start() - GUI 시작
    2. runner.click("버튼명") - 버튼 클릭
    3. runner.has_errors() - 오류 확인
    4. 오류 시 → runner.stop() → 코드 수정 → runner.start()
    """
    runner = ClaudeGUIRunner()

    # 1. GUI 시작
    if not runner.start():
        print("GUI 시작 실패!")
        runner._print_errors()
        return

    try:
        # 2. 버튼 목록 확인
        runner.list_buttons()

        # 3. 스크린샷
        runner.screenshot("initial")

        # 4. 상태 확인
        print(f"상태: {runner.status()}")

        # 5. 오류 확인
        runner.wait(3)
        if runner.has_errors():
            print("오류 발생!")
            for err in runner.get_errors():
                print(f"  - {err}")

    finally:
        runner.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true", help="버튼 캘리브레이션")
    parser.add_argument("--test", action="store_true", help="테스트 예시 실행")

    args = parser.parse_args()

    runner = ClaudeGUIRunner()

    if args.calibrate:
        if not runner.start():
            sys.exit(1)

        try:
            buttons = ["채널선택", "팩선택", "큐에추가", "큐실행",
                       "생산시작", "썸네일건너뛰기", "자동업로드"]

            for btn in buttons:
                runner.calibrate(btn)

            print("\n캘리브레이션 완료!")
            runner.list_buttons()

        finally:
            runner.stop()

    elif args.test:
        example_test()

    else:
        print("사용법:")
        print("  python claude_gui_runner.py --calibrate  # 버튼 위치 등록")
        print("  python claude_gui_runner.py --test       # 테스트 예시")
