# src/gui/setup_wizard.py
"""
첫 실행 설정 마법사

프로그램 첫 실행 시 필수 설정을 안내합니다.
"""
import os
import json
import logging
import customtkinter as ctk
from tkinter import messagebox

logger = logging.getLogger(__name__)

# GPU 체크 (선택적 — 없어도 마법사 동작)
try:
    from utils.gpu_checker import check_gpu_vram, get_gpu_summary_text
    GPU_CHECKER_AVAILABLE = True
except ImportError:
    GPU_CHECKER_AVAILABLE = False


class SetupWizard(ctk.CTkToplevel):
    """
    첫 실행 설정 마법사

    단계:
    1. 환영 + 프로그램 소개
    2. API 설정 (SD WebUI, SoVITS, Story LLM)
    3. 채널 브랜딩 설정
    4. 완료
    """

    def __init__(self, parent, data_dir: str):
        super().__init__(parent)

        self.data_dir = data_dir
        self.current_step = 0
        self.total_steps = 4
        self.completed = False

        # 창 설정
        self.title("🚀 Reverie Automation 설정 마법사")
        self.geometry("750x650")
        self.resizable(True, True)
        self.minsize(700, 600)

        # 중앙 배치
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 750) // 2
        y = (self.winfo_screenheight() - 650) // 2
        self.geometry(f"750x650+{x}+{y}")

        self.transient(parent)
        self.grab_set()

        # 입력값 저장용 (3개 독립 채널 구조)
        self.inputs = {
            "sd_url": "",
            "sovits_url": "",
            "gemini_key": "",
            "story_llm_provider": "claude_cli",
            "claude_cli_path": "claude",
            "claude_cli_model": "sonnet",
            "story_llm_timeout_sec": "600",
            "horror_channel": "",
            "horror_greeting": "",
            "touching_channel": "",
            "touching_greeting": "",
            "makjang_channel": "",
            "makjang_greeting": ""
        }

        # UI 구성
        self._create_ui()
        self._show_step(0)

    def _update_story_llm_visibility(self, *_args):
        provider = (self.story_llm_provider_var.get() or "claude_cli").strip().lower()

        if hasattr(self, "wizard_gemini_frame"):
            if provider == "gemini":
                self.wizard_gemini_frame.pack(fill="x", padx=40, pady=5)
            else:
                self.wizard_gemini_frame.pack_forget()

        if hasattr(self, "wizard_claude_frame"):
            if provider in {"claude", "claude_cli"}:
                self.wizard_claude_frame.pack(fill="x", padx=40, pady=5)
            else:
                self.wizard_claude_frame.pack_forget()

    def _create_ui(self):
        """UI 생성"""
        # 상단 진행 표시
        self.progress_frame = ctk.CTkFrame(self, height=60)
        self.progress_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.progress_frame.pack_propagate(False)

        self.step_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=ctk.CTkFont(size=14)
        )
        self.step_label.pack(pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=600)
        self.progress_bar.pack(pady=5)
        self.progress_bar.set(0)

        # 메인 콘텐츠 영역 (스크롤 가능)
        self.content_frame = ctk.CTkScrollableFrame(self)
        self.content_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 하단 버튼
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(fill="x", padx=20, pady=20)

        self.back_btn = ctk.CTkButton(
            self.button_frame,
            text="◀ 이전",
            command=self._prev_step,
            width=100,
            state="disabled"
        )
        self.back_btn.pack(side="left")

        self.skip_btn = ctk.CTkButton(
            self.button_frame,
            text="건너뛰기",
            command=self._skip,
            width=100,
            fg_color="gray"
        )
        self.skip_btn.pack(side="left", padx=10)

        self.next_btn = ctk.CTkButton(
            self.button_frame,
            text="다음 ▶",
            command=self._next_step,
            width=100
        )
        self.next_btn.pack(side="right")

    def _clear_content(self):
        """콘텐츠 영역 초기화"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _show_step(self, step: int):
        """단계별 화면 표시"""
        self.current_step = step
        self._clear_content()

        # 진행률 업데이트
        progress = (step + 1) / self.total_steps
        self.progress_bar.set(progress)
        self.step_label.configure(text=f"단계 {step + 1} / {self.total_steps}")

        # 버튼 상태
        self.back_btn.configure(state="normal" if step > 0 else "disabled")

        if step == 0:
            self._show_welcome()
        elif step == 1:
            self._show_api_setup()
        elif step == 2:
            self._show_branding_setup()
        elif step == 3:
            self._show_complete()

    def _show_welcome(self):
        """1단계: 환영 화면"""
        self.skip_btn.pack_forget()  # 첫 화면에서는 건너뛰기 숨김

        ctk.CTkLabel(
            self.content_frame,
            text="🎬 Reverie Automation에 오신 것을 환영합니다!",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(40, 20))

        welcome_text = """
이 프로그램은 AI를 활용하여 자동으로 영상을 제작합니다.

시작하기 전에 몇 가지 설정이 필요합니다:

    🔧 API 설정
       - Stable Diffusion WebUI (이미지 생성)
       - GPT-SoVITS (음성 합성)
       - Google Gemini (시나리오 생성)

    📺 채널 브랜딩
       - 채널명 및 인사말 설정

설정은 나중에 '시스템' 탭에서 언제든지 변경할 수 있습니다.

준비되셨으면 '다음'을 클릭하세요!
        """

        ctk.CTkLabel(
            self.content_frame,
            text=welcome_text,
            font=ctk.CTkFont(size=14),
            justify="left"
        ).pack(pady=20, padx=40)

        # GPU VRAM 자동 체크 (AC8)
        if GPU_CHECKER_AVAILABLE:
            try:
                gpu_info = check_gpu_vram()
                gpu_text = get_gpu_summary_text()

                if gpu_info.get("warning"):
                    # VRAM 부족 또는 미감지 시 경고 표시
                    warn_frame = ctk.CTkFrame(self.content_frame, fg_color="#4a1a1a")
                    warn_frame.pack(fill="x", padx=40, pady=10)

                    warn_icon = "⚠️" if gpu_info.get("available") else "🚫"
                    ctk.CTkLabel(
                        warn_frame,
                        text=f"{warn_icon} GPU 사양 체크",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color="#ff6b6b"
                    ).pack(pady=(10, 5), padx=15, anchor="w")

                    ctk.CTkLabel(
                        warn_frame,
                        text=gpu_info["warning"],
                        font=ctk.CTkFont(size=12),
                        text_color="#ffaaaa",
                        justify="left",
                        wraplength=600
                    ).pack(pady=(0, 10), padx=15, anchor="w")
                else:
                    # 정상
                    ok_frame = ctk.CTkFrame(self.content_frame, fg_color="#1a3a1a")
                    ok_frame.pack(fill="x", padx=40, pady=10)

                    ctk.CTkLabel(
                        ok_frame,
                        text=f"✅ {gpu_text}",
                        font=ctk.CTkFont(size=13),
                        text_color="#88ff88"
                    ).pack(pady=10, padx=15, anchor="w")

            except Exception as e:
                logger.debug(f"GPU 체크 표시 실패 (무시): {e}")

    def _show_api_setup(self):
        """2단계: API 설정"""
        self.skip_btn.pack(side="left", padx=10)

        ctk.CTkLabel(
            self.content_frame,
            text="🔧 API 설정",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(20, 10))

        ctk.CTkLabel(
            self.content_frame,
            text="영상 제작에 필요한 AI 서비스 주소를 입력하세요.\n이미 실행 중인 서비스의 주소를 입력합니다.",
            font=ctk.CTkFont(size=13),
            text_color="gray"
        ).pack(pady=(0, 20))

        # SD WebUI
        sd_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        sd_frame.pack(fill="x", padx=40, pady=5)

        ctk.CTkLabel(sd_frame, text="🎨 SD WebUI 주소:", width=150, anchor="w").pack(side="left")
        self.sd_entry = ctk.CTkEntry(sd_frame, width=350, placeholder_text="http://127.0.0.1:7860")
        self.sd_entry.pack(side="left", padx=10)
        if self.inputs["sd_url"]:
            self.sd_entry.insert(0, self.inputs["sd_url"])

        # SoVITS
        sovits_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        sovits_frame.pack(fill="x", padx=40, pady=5)

        ctk.CTkLabel(sovits_frame, text="🎤 SoVITS 주소:", width=150, anchor="w").pack(side="left")
        self.sovits_entry = ctk.CTkEntry(sovits_frame, width=350, placeholder_text="http://127.0.0.1:9880")
        self.sovits_entry.pack(side="left", padx=10)
        if self.inputs["sovits_url"]:
            self.sovits_entry.insert(0, self.inputs["sovits_url"])

        provider_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        provider_frame.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(provider_frame, text="🤖 Story LLM:", width=150, anchor="w").pack(side="left")
        self.story_llm_provider_var = ctk.StringVar(value=self.inputs["story_llm_provider"])
        self.story_llm_provider_dropdown = ctk.CTkOptionMenu(
            provider_frame,
            variable=self.story_llm_provider_var,
            values=["gemini", "claude_cli"],
            width=200,
            command=self._update_story_llm_visibility
        )
        self.story_llm_provider_dropdown.pack(side="left", padx=10)

        self.wizard_gemini_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.wizard_gemini_frame.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(self.wizard_gemini_frame, text="🤖 Gemini API 키:", width=150, anchor="w").pack(side="left")
        self.gemini_entry = ctk.CTkEntry(self.wizard_gemini_frame, width=350, placeholder_text="AIza...", show="*")
        self.gemini_entry.pack(side="left", padx=10)
        if self.inputs["gemini_key"]:
            self.gemini_entry.insert(0, self.inputs["gemini_key"])

        self.wizard_claude_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")

        claude_path_frame = ctk.CTkFrame(self.wizard_claude_frame, fg_color="transparent")
        claude_path_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(claude_path_frame, text="🧭 Claude CLI 경로:", width=150, anchor="w").pack(side="left")
        self.claude_path_entry = ctk.CTkEntry(claude_path_frame, width=350, placeholder_text="claude")
        self.claude_path_entry.pack(side="left", padx=10)
        if self.inputs["claude_cli_path"]:
            self.claude_path_entry.insert(0, self.inputs["claude_cli_path"])

        claude_model_frame = ctk.CTkFrame(self.wizard_claude_frame, fg_color="transparent")
        claude_model_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(claude_model_frame, text="모델:", width=150, anchor="w").pack(side="left")
        self.claude_model_entry = ctk.CTkEntry(claude_model_frame, width=200, placeholder_text="sonnet")
        self.claude_model_entry.pack(side="left", padx=10)
        if self.inputs["claude_cli_model"]:
            self.claude_model_entry.insert(0, self.inputs["claude_cli_model"])

        claude_timeout_frame = ctk.CTkFrame(self.wizard_claude_frame, fg_color="transparent")
        claude_timeout_frame.pack(fill="x", pady=3)
        ctk.CTkLabel(claude_timeout_frame, text="Timeout(sec):", width=150, anchor="w").pack(side="left")
        self.story_llm_timeout_entry = ctk.CTkEntry(claude_timeout_frame, width=120, placeholder_text="600")
        self.story_llm_timeout_entry.pack(side="left", padx=10)
        if self.inputs["story_llm_timeout_sec"]:
            self.story_llm_timeout_entry.insert(0, self.inputs["story_llm_timeout_sec"])

        self._update_story_llm_visibility()

        # 도움말
        help_frame = ctk.CTkFrame(self.content_frame, fg_color="#2b2b2b")
        help_frame.pack(fill="x", padx=40, pady=20)

        help_text = """
💡 도움말:
• SD WebUI: Stable Diffusion WebUI를 --api 옵션과 함께 실행하세요
• SoVITS: GPT-SoVITS API 서버를 실행하세요
• Gemini API 키: Google AI Studio에서 발급받을 수 있습니다
• Claude CLI: 로컬에 설치하고 로그인한 뒤 경로/모델을 입력하면 됩니다
        """
        ctk.CTkLabel(
            help_frame,
            text=help_text,
            font=ctk.CTkFont(size=12),
            justify="left",
            text_color="gray"
        ).pack(pady=10, padx=10)

    def _show_branding_setup(self):
        """3단계: 채널 브랜딩 (3개 독립 채널)"""
        self.skip_btn.pack(side="left", padx=10)

        ctk.CTkLabel(
            self.content_frame,
            text="📺 채널 브랜딩 설정",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            self.content_frame,
            text="영상에 표시될 채널명과 인사말을 설정하세요. (3개 독립 채널)",
            font=ctk.CTkFont(size=13),
            text_color="gray"
        ).pack(pady=(0, 15))

        # 1. 공포 채널
        horror_label = ctk.CTkLabel(
            self.content_frame,
            text="👻 공포 채널",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        horror_label.pack(anchor="w", padx=40, pady=(5, 3))

        horror_name_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        horror_name_frame.pack(fill="x", padx=40, pady=1)
        ctk.CTkLabel(horror_name_frame, text="채널명:", width=60, anchor="w").pack(side="left")
        self.horror_name_entry = ctk.CTkEntry(horror_name_frame, width=200, placeholder_text="포시즌호러이야기")
        self.horror_name_entry.pack(side="left", padx=5)
        ctk.CTkLabel(horror_name_frame, text="인사말:", width=50, anchor="w").pack(side="left", padx=(10, 0))
        self.horror_greeting_entry = ctk.CTkEntry(horror_name_frame, width=250, placeholder_text="안녕하세요, 포시즌입니다.")
        self.horror_greeting_entry.pack(side="left", padx=5)
        if self.inputs["horror_channel"]:
            self.horror_name_entry.insert(0, self.inputs["horror_channel"])
        if self.inputs["horror_greeting"]:
            self.horror_greeting_entry.insert(0, self.inputs["horror_greeting"])

        # 2. 감동 시니어 채널
        touching_label = ctk.CTkLabel(
            self.content_frame,
            text="💕 감동 시니어 채널",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        touching_label.pack(anchor="w", padx=40, pady=(12, 3))

        touching_name_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        touching_name_frame.pack(fill="x", padx=40, pady=1)
        ctk.CTkLabel(touching_name_frame, text="채널명:", width=60, anchor="w").pack(side="left")
        self.touching_name_entry = ctk.CTkEntry(touching_name_frame, width=200, placeholder_text="세월정거장")
        self.touching_name_entry.pack(side="left", padx=5)
        ctk.CTkLabel(touching_name_frame, text="인사말:", width=50, anchor="w").pack(side="left", padx=(10, 0))
        self.touching_greeting_entry = ctk.CTkEntry(touching_name_frame, width=250, placeholder_text="안녕하십니까, 세월정거장입니다.")
        self.touching_greeting_entry.pack(side="left", padx=5)
        if self.inputs["touching_channel"]:
            self.touching_name_entry.insert(0, self.inputs["touching_channel"])
        if self.inputs["touching_greeting"]:
            self.touching_greeting_entry.insert(0, self.inputs["touching_greeting"])

        # 3. 막장 시니어 채널
        makjang_label = ctk.CTkLabel(
            self.content_frame,
            text="🔥 막장 시니어 채널",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        makjang_label.pack(anchor="w", padx=40, pady=(12, 3))

        makjang_name_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        makjang_name_frame.pack(fill="x", padx=40, pady=1)
        ctk.CTkLabel(makjang_name_frame, text="채널명:", width=60, anchor="w").pack(side="left")
        self.makjang_name_entry = ctk.CTkEntry(makjang_name_frame, width=200, placeholder_text="세월정거장")
        self.makjang_name_entry.pack(side="left", padx=5)
        ctk.CTkLabel(makjang_name_frame, text="인사말:", width=50, anchor="w").pack(side="left", padx=(10, 0))
        self.makjang_greeting_entry = ctk.CTkEntry(makjang_name_frame, width=250, placeholder_text="사이다 극장! 세월정거장입니다.")
        self.makjang_greeting_entry.pack(side="left", padx=5)
        if self.inputs["makjang_channel"]:
            self.makjang_name_entry.insert(0, self.inputs["makjang_channel"])
        if self.inputs["makjang_greeting"]:
            self.makjang_greeting_entry.insert(0, self.inputs["makjang_greeting"])

    def _show_complete(self):
        """4단계: 완료"""
        self.skip_btn.pack_forget()
        self.next_btn.configure(text="완료 ✓", fg_color="green", hover_color="darkgreen")

        ctk.CTkLabel(
            self.content_frame,
            text="🎉 설정 완료!",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(pady=(50, 20))

        complete_text = """
모든 설정이 완료되었습니다!

이제 영상 제작을 시작할 수 있습니다.

    📋 시작 방법:
       1. 채널 선택 (공포/시니어)
       2. 모드 선택 (감동/막장)
       3. 주제 입력 또는 자동 생성
       4. '제작 시작' 클릭

    💡 팁:
       • 설정은 '시스템' 탭에서 언제든 변경 가능
       • 문제 발생 시 로그를 확인하세요
       • 정기적으로 설정을 백업하세요

즐거운 영상 제작 되세요! 🎬
        """

        ctk.CTkLabel(
            self.content_frame,
            text=complete_text,
            font=ctk.CTkFont(size=14),
            justify="left"
        ).pack(pady=20, padx=40)

    def _save_current_inputs(self):
        """현재 단계의 입력값 저장"""
        if self.current_step == 1:  # API 설정
            self.inputs["sd_url"] = self.sd_entry.get().strip()
            self.inputs["sovits_url"] = self.sovits_entry.get().strip()
            self.inputs["gemini_key"] = self.gemini_entry.get().strip()
            self.inputs["story_llm_provider"] = self.story_llm_provider_var.get().strip()
            self.inputs["claude_cli_path"] = self.claude_path_entry.get().strip()
            self.inputs["claude_cli_model"] = self.claude_model_entry.get().strip()
            self.inputs["story_llm_timeout_sec"] = self.story_llm_timeout_entry.get().strip()
        elif self.current_step == 2:  # 브랜딩 (3개 독립 채널)
            self.inputs["horror_channel"] = self.horror_name_entry.get().strip()
            self.inputs["horror_greeting"] = self.horror_greeting_entry.get().strip()
            self.inputs["touching_channel"] = self.touching_name_entry.get().strip()
            self.inputs["touching_greeting"] = self.touching_greeting_entry.get().strip()
            self.inputs["makjang_channel"] = self.makjang_name_entry.get().strip()
            self.inputs["makjang_greeting"] = self.makjang_greeting_entry.get().strip()

    def _next_step(self):
        """다음 단계로"""
        self._save_current_inputs()

        if self.current_step < self.total_steps - 1:
            self._show_step(self.current_step + 1)
        else:
            self._finish()

    def _prev_step(self):
        """이전 단계로"""
        self._save_current_inputs()

        if self.current_step > 0:
            self._show_step(self.current_step - 1)

    def _skip(self):
        """현재 단계 건너뛰기"""
        if self.current_step < self.total_steps - 1:
            self._show_step(self.current_step + 1)

    def _finish(self):
        """설정 저장 및 완료"""
        try:
            # API 설정 저장
            if any([
                self.inputs["sd_url"],
                self.inputs["sovits_url"],
                self.inputs["gemini_key"],
                self.inputs["claude_cli_path"],
            ]):
                api_path = os.path.join(self.data_dir, "api_settings.json")
                api_settings = {}

                if os.path.exists(api_path):
                    try:
                        with open(api_path, "r", encoding="utf-8") as f:
                            api_settings = json.load(f)
                    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                        logger.debug(f"API 설정 JSON 로드 실패: {e}")

                if self.inputs["sd_url"]:
                    api_settings["sd_url"] = self.inputs["sd_url"]
                if self.inputs["sovits_url"]:
                    api_settings["sovits_url"] = self.inputs["sovits_url"]
                if self.inputs["gemini_key"]:
                    api_settings["gemini_api_key"] = self.inputs["gemini_key"]
                if self.inputs["story_llm_provider"]:
                    api_settings["story_llm_provider"] = self.inputs["story_llm_provider"]
                if self.inputs["claude_cli_path"]:
                    api_settings["claude_cli_path"] = self.inputs["claude_cli_path"]
                if self.inputs["claude_cli_model"]:
                    api_settings["claude_cli_model"] = self.inputs["claude_cli_model"]
                if self.inputs["story_llm_timeout_sec"]:
                    try:
                        timeout_value = int(self.inputs["story_llm_timeout_sec"])
                        if timeout_value <= 0:
                            raise ValueError
                    except ValueError:
                        timeout_value = 600
                    api_settings["story_llm_timeout_sec"] = timeout_value
                provider = (self.inputs.get("story_llm_provider") or "claude_cli").strip().lower()
                if provider == "claude":
                    provider = "claude_cli"
                api_settings["story_llm_model"] = (
                    (self.inputs.get("claude_cli_model") or "sonnet").strip()
                    if provider == "claude_cli" else ""
                )

                os.makedirs(os.path.dirname(api_path), exist_ok=True)
                with open(api_path, "w", encoding="utf-8") as f:
                    json.dump(api_settings, f, indent=2, ensure_ascii=False)

            # 브랜딩 설정 저장 (3개 독립 채널)
            if any([self.inputs["horror_channel"], self.inputs["touching_channel"], self.inputs["makjang_channel"]]):
                branding_path = os.path.join(self.data_dir, "branding.json")
                branding = {
                    "daily_life_toon": {"channel_name": "", "intro_file": "", "openings": []},
                    "mystery_toon": {"channel_name": "", "intro_file": "", "openings": []}
                }

                if os.path.exists(branding_path):
                    try:
                        with open(branding_path, "r", encoding="utf-8") as f:
                            branding = json.load(f)
                    except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                        logger.debug(f"브랜딩 JSON 로드 실패: {e}")

                # Former horror input now configures the mystery VideoToon pack.
                if "mystery_toon" not in branding:
                    branding["mystery_toon"] = {"channel_name": "", "intro_file": "", "openings": []}
                if self.inputs["horror_channel"]:
                    branding["mystery_toon"]["channel_name"] = self.inputs["horror_channel"]
                if self.inputs["horror_greeting"]:
                    branding["mystery_toon"]["openings"] = [self.inputs["horror_greeting"]]

                # Former senior inputs now configure the daily-life VideoToon pack.
                if "daily_life_toon" not in branding:
                    branding["daily_life_toon"] = {"channel_name": "", "intro_file": "", "openings": []}
                if self.inputs["touching_channel"]:
                    branding["daily_life_toon"]["channel_name"] = self.inputs["touching_channel"]
                elif self.inputs["makjang_channel"]:
                    branding["daily_life_toon"]["channel_name"] = self.inputs["makjang_channel"]
                if self.inputs["touching_greeting"]:
                    branding["daily_life_toon"]["openings"] = [self.inputs["touching_greeting"]]
                elif self.inputs["makjang_greeting"]:
                    branding["daily_life_toon"]["openings"] = [self.inputs["makjang_greeting"]]

                os.makedirs(os.path.dirname(branding_path), exist_ok=True)
                with open(branding_path, "w", encoding="utf-8") as f:
                    json.dump(branding, f, indent=2, ensure_ascii=False)

            # 첫 실행 완료 표시
            first_run_path = os.path.join(self.data_dir, ".first_run_complete")
            with open(first_run_path, "w") as f:
                f.write("1")

            self.completed = True
            self.destroy()

        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 중 오류 발생:\n{e}")

    def is_completed(self) -> bool:
        """마법사 완료 여부"""
        return self.completed


def should_show_wizard(data_dir: str) -> bool:
    """
    설정 마법사를 표시해야 하는지 확인

    Args:
        data_dir: 데이터 디렉토리 경로

    Returns:
        bool: 마법사 표시 여부
    """
    first_run_path = os.path.join(data_dir, ".first_run_complete")
    return not os.path.exists(first_run_path)
