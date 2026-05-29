# src/gui/mixins/settings_mixin.py
"""
v60.1.0: 설정/유틸리티 Mixin — API 설정, 백업, 다이얼로그, UI 콜백, 패키지 관리

ReverieGUI에서 추출된 37개 메서드:
설정 저장/복원, 테마 전환, 패키지 관리, revpack 로딩,
YouTube 분석, 썸네일 테스트, 템플릿 관리, 드래그&드롭 등

의존하는 self 변수:
- self.settings_manager, self.api_key_entry, self.sd_url_entry
- self.channel_var, self.channel_dropdown, self.template_dropdown
- self.prompt_mode_var, self.tts_engine_var, self.premium_mode_var
- self.test_mode_var, self.vs_toggle_var, self.vs_status_label
- self.recent_projects_list, self.tabview
"""
import json
import os
import threading
from tkinter import messagebox, filedialog

import customtkinter as ctk

from config.settings import config
from utils.logger import get_logger

logger = get_logger("settings_mixin")


class SettingsMixin:
    """설정/유틸리티 횡단 관심사"""

    @staticmethod
    def _resolve_story_llm_model(provider: str, claude_cli_model: str) -> str:
        provider = (provider or "").strip().lower()
        if provider in {"claude", "claude_cli"}:
            return (claude_cli_model or "sonnet").strip()
        return ""

    def _update_story_llm_fields_visibility(self, *_args):
        """스토리 생성 provider에 맞는 입력 필드만 노출한다."""
        provider = "claude_cli"
        if hasattr(self, "story_llm_provider_var"):
            provider = (self.story_llm_provider_var.get() or "claude_cli").strip().lower()

        if hasattr(self, "gemini_settings_frame"):
            if provider == "gemini":
                self.gemini_settings_frame.pack(fill="x", padx=20, pady=5)
            else:
                self.gemini_settings_frame.pack_forget()

        if hasattr(self, "claude_settings_frame"):
            if provider in {"claude", "claude_cli"}:
                self.claude_settings_frame.pack(fill="x", padx=20, pady=5)
            else:
                self.claude_settings_frame.pack_forget()

    @staticmethod
    def _parse_story_llm_timeout(value: str) -> int:
        parsed = int((value or "").strip())
        if parsed <= 0:
            raise ValueError("timeout must be positive")
        return parsed

    def _resolve_auto_optimizer_target(self) -> tuple[str, str | None]:
        """Resolve the optimizer target from the currently selected pack."""
        channel_id = self._safe_get_var("channel_var", "")
        try:
            channel_type, _mode = self._get_channel_mode_from_package(channel_id)
        except Exception as e:
            logger.debug(f"자동 최적화 대상 채널 결정 실패: {e}")
            channel_type = "horror"
        return channel_type or "horror", (channel_id or None)

    def _on_test_thumbnail(self):
        """테스트 썸네일 생성"""
        import threading

        # 진행 중이면 무시
        if self.is_producing:
            messagebox.showwarning("경고", "생산이 이미 진행 중입니다.")
            return

        # 백그라운드 스레드로 실행
        thread = threading.Thread(target=self._test_thumbnail_worker, daemon=True)
        thread.start()

    def _test_thumbnail_worker(self):
        """테스트 썸네일 생성 워커"""
        try:
            self._add_log("🎨 테스트 썸네일 생성 시작...")

            # 현재 채널/모드 가져오기
            channel = self.channel_var.get()
            if channel == "공포":
                channel_name = "horror"
                mode = "horror"
            elif channel == "시니어 (감동)":
                channel_name = "senior"
                mode = "touching"
            else:
                channel_name = "senior"
                mode = "makjang"

            # 썸네일 설정 가져오기
            thumb_settings = self.settings_manager.get_thumbnail_settings(channel_name, mode)

            # 샘플 제목
            sample_top = thumb_settings.get("top_text", {}).get("content", "실화 공포")
            sample_main = thumb_settings.get("main_title", {}).get("content", "충격적인 결말")

            self._add_log(f"   상단: {sample_top}")
            self._add_log(f"   메인: {sample_main}")

            # MediaFactory 초기화 (channel만 전달)
            from modules_pro.media_factory import MediaFactory
            factory = MediaFactory(channel_name)

            # 임시 디렉토리
            import os
            import tempfile
            temp_dir = tempfile.mkdtemp(prefix="reverie_test_")

            # 썸네일 2종 생성
            self._add_log("   [IMG] REAL 스타일 생성 중...")
            real_path = factory.generate_test_thumbnail(
                "REAL",
                sample_top,
                sample_main,
                os.path.join(temp_dir, "test_REAL.jpg"),
                mode
            )

            self._add_log("   [IMG] ART 스타일 생성 중...")
            art_path = factory.generate_test_thumbnail(
                "ART",
                sample_top,
                sample_main,
                os.path.join(temp_dir, "test_ART.jpg"),
                mode
            )

            self._add_log("   [OK] 썸네일 생성 완료!")

            # 조정 팝업 띄우기 (메인 스레드에서)
            self.after(0, lambda: self._show_test_thumbnail_dialog(real_path, art_path))

        except Exception as e:
            self._add_log(f"   [ERROR] 오류: {str(e)}")
            import traceback
            traceback.print_exc()

    def _show_test_thumbnail_dialog(self, real_path: str, art_path: str):
        """테스트 썸네일 조정 다이얼로그 표시"""
        from gui.thumbnail_preview_dialog import ThumbnailPreviewDialog

        dialog = ThumbnailPreviewDialog(self, real_path, art_path, config.FONT_PATH)
        choice = dialog.get_choice()

        if choice == "proceed":
            self._add_log("[OK] 테스트 완료 - 설정이 저장되었습니다.")
        else:
            self._add_log("[CANCEL] 테스트 취소")

    def _save_api_settings(self):
        """API 설정 저장"""
        # 값 가져오기
        sd_url = self.sd_url_entry.get().strip()
        sovits_url = self.sovits_url_entry.get().strip()
        gemini_key = self.gemini_key_entry.get().strip() if hasattr(self, "gemini_key_entry") else ""
        provider = (self.story_llm_provider_var.get().strip().lower()
                    if hasattr(self, "story_llm_provider_var") else "claude_cli")
        if provider == "claude":
            provider = "claude_cli"
        claude_cli_path = self.claude_cli_path_entry.get().strip() if hasattr(self, "claude_cli_path_entry") else ""
        claude_cli_model = self.claude_cli_model_entry.get().strip() if hasattr(self, "claude_cli_model_entry") else ""
        timeout_text = self.story_llm_timeout_entry.get().strip() if hasattr(self, "story_llm_timeout_entry") else ""

        # 검증
        if not sd_url.startswith("http"):
            messagebox.showerror("오류", "SD WebUI 주소는 http:// 또는 https://로 시작해야 합니다.")
            return

        if not sovits_url.startswith("http"):
            messagebox.showerror("오류", "SoVITS 주소는 http:// 또는 https://로 시작해야 합니다.")
            return

        if provider == "claude_cli":
            if not claude_cli_path:
                messagebox.showerror("오류", "Claude CLI 경로를 입력해주세요.")
                return
            if not claude_cli_model:
                messagebox.showerror("오류", "Claude CLI 모델명을 입력해주세요.")
                return
            if not gemini_key:
                gemini_key = "__claude_cli__"

        try:
            story_llm_timeout = self._parse_story_llm_timeout(
                timeout_text or str(getattr(config, "STORY_LLM_TIMEOUT_SEC", 600))
            )
        except ValueError:
            messagebox.showerror("오류", "Story LLM timeout은 1 이상의 정수로 입력해주세요.")
            return

        story_llm_model = self._resolve_story_llm_model(provider, claude_cli_model)

        if provider == "gemini" and not gemini_key:
            messagebox.showerror("오류", "Gemini API 키를 입력해주세요.")
            return

        # 설정 저장
        if provider == "claude_cli" and gemini_key == "__claude_cli__":
            gemini_key = ""

        try:
            settings_path = os.path.join(config.DATA_DIR, "api_settings.json")

            settings = {
                "sd_url": sd_url,
                "sovits_url": sovits_url,
                "gemini_api_key": gemini_key,
                "comfyui_url": config.COMFYUI_URL,
                "story_llm_provider": provider,
                "claude_cli_path": claude_cli_path or getattr(config, "CLAUDE_CLI_PATH", "claude"),
                "claude_cli_model": claude_cli_model or getattr(config, "CLAUDE_CLI_MODEL", "sonnet"),
                "story_llm_model": story_llm_model,
                "story_llm_timeout_sec": story_llm_timeout,
            }

            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

            # config 업데이트
            config.SD_URL = sd_url
            config.SOVITS_URL = sovits_url
            config.GEMINI_API_KEY = gemini_key
            config.STORY_LLM_PROVIDER = provider
            config.CLAUDE_CLI_PATH = settings["claude_cli_path"]
            config.CLAUDE_CLI_MODEL = settings["claude_cli_model"]
            config.STORY_LLM_MODEL = settings["story_llm_model"]
            config.STORY_LLM_TIMEOUT_SEC = story_llm_timeout

            messagebox.showinfo("성공", "API 설정이 저장되었습니다.\n다음 실행 시 자동으로 적용됩니다.")

        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 실패:\n{e}")

    def _save_channel_settings(self):
        """채널 설정 저장 (동적 패키지 기반)"""
        # 기존 설정 로드
        branding_path = os.path.join(config.DATA_DIR, "branding.json")
        try:
            if os.path.exists(branding_path):
                with open(branding_path, "r", encoding="utf-8") as f:
                    branding_data = json.load(f)
            else:
                branding_data = {}
        except Exception as e:
            logger.warning(f"채널 설정 로드 실패: {e}")
            branding_data = {}

        # 동적으로 저장된 입력 필드에서 값 가져오기
        if hasattr(self, 'channel_entries') and hasattr(self, 'greeting_entries'):
            for channel_id, ch_entry in self.channel_entries.items():
                channel_name = ch_entry.get().strip()
                greeting = self.greeting_entries.get(channel_id, None)
                greeting_text = greeting.get().strip() if greeting else ""

                # 채널 데이터 업데이트
                if channel_id not in branding_data:
                    branding_data[channel_id] = {"channel_name": "", "intro_file": "", "openings": []}

                branding_data[channel_id]["channel_name"] = channel_name
                if greeting_text:
                    branding_data[channel_id]["openings"] = [greeting_text]

        # 저장
        try:
            os.makedirs(os.path.dirname(branding_path), exist_ok=True)
            with open(branding_path, "w", encoding="utf-8") as f:
                json.dump(branding_data, f, indent=2, ensure_ascii=False)
            messagebox.showinfo("성공", "채널 설정이 저장되었습니다.\n다음 영상 제작부터 적용됩니다.")
        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 실패:\n{e}")

    def _open_branding_dialog(self):
        """채널 브랜딩 다이얼로그 열기"""
        from gui.branding_dialog import BrandingDialog

        # 최신 브랜딩 정보 로드
        branding_path = os.path.join(config.DATA_DIR, "branding.json")
        try:
            if os.path.exists(branding_path):
                with open(branding_path, "r", encoding="utf-8") as f:
                    branding_data = json.load(f)
            else:
                # 기본값 (VideoToon-only official channels)
                branding_data = {
                    "daily_life_toon": {
                        "channel_name": "",
                        "intro_file": "",
                        "openings": []
                    },
                    "mystery_toon": {
                        "channel_name": "",
                        "intro_file": "",
                        "openings": []
                    }
                }

            dialog = BrandingDialog(self, branding_data)
        except Exception as e:
            messagebox.showerror("오류", f"브랜딩 설정을 불러올 수 없습니다: {e}")

    def _create_backup(self):
        """설정 백업 생성"""
        try:
            backup_path = self.settings_manager.create_backup()
            messagebox.showinfo(
                "백업 완료",
                f"설정이 백업되었습니다.\n\n경로: {backup_path}"
            )
            logger.info(f"설정 백업 생성: {backup_path}")
        except Exception as e:
            messagebox.showerror("오류", f"백업 생성 실패:\n{e}")
            logger.error(f"백업 생성 실패: {e}")

    def _restore_backup(self):
        """백업에서 설정 복구"""
        # 백업 목록 가져오기
        backups = self.settings_manager.list_backups()

        if not backups:
            messagebox.showinfo("알림", "사용 가능한 백업이 없습니다.")
            return

        # 백업 선택 다이얼로그
        dialog = ctk.CTkToplevel(self)
        dialog.title("백업 복구")
        dialog.geometry("500x400")
        dialog.transient(self)
        dialog.grab_set()

        # 중앙 배치
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 500) // 2
        y = (dialog.winfo_screenheight() - 400) // 2
        dialog.geometry(f"500x400+{x}+{y}")

        ctk.CTkLabel(
            dialog,
            text="📤 백업 복구",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=15)

        ctk.CTkLabel(
            dialog,
            text="복구할 백업을 선택하세요:",
            font=ctk.CTkFont(size=13)
        ).pack(pady=5)

        # 백업 리스트
        listbox_frame = ctk.CTkFrame(dialog)
        listbox_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 스크롤 가능한 프레임
        scrollable = ctk.CTkScrollableFrame(listbox_frame)
        scrollable.pack(fill="both", expand=True)

        selected_backup = [None]

        def select_backup(backup):
            selected_backup[0] = backup
            for widget in scrollable.winfo_children():
                if isinstance(widget, ctk.CTkButton):
                    widget.configure(fg_color="transparent" if widget.cget("text") != backup["name"] else "#1f6aa5")

        for backup in backups:
            btn = ctk.CTkButton(
                scrollable,
                text=f"{backup['name']}\n({backup['created_at'][:19] if backup['created_at'] != '알 수 없음' else '알 수 없음'})",
                command=lambda b=backup: select_backup(b),
                fg_color="transparent",
                text_color=("black", "white"),
                anchor="w",
                height=50
            )
            btn.pack(fill="x", pady=2)

        def do_restore():
            if not selected_backup[0]:
                messagebox.showwarning("선택 필요", "복구할 백업을 선택하세요.")
                return

            if messagebox.askyesno("확인", f"'{selected_backup[0]['name']}' 백업으로 복구하시겠습니까?\n\n현재 설정이 덮어씌워집니다."):
                success, msg = self.settings_manager.restore_backup(selected_backup[0]["path"])
                if success:
                    messagebox.showinfo("복구 완료", f"{msg}\n\n프로그램을 다시 시작해주세요.")
                    logger.info(f"설정 복구 완료: {selected_backup[0]['path']}")
                    dialog.destroy()
                else:
                    messagebox.showerror("복구 실패", msg)
                    logger.error(f"설정 복구 실패: {msg}")

        # 버튼 프레임
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill="x", pady=15, padx=20)

        ctk.CTkButton(
            btn_frame,
            text="복구",
            command=do_restore,
            fg_color="green",
            hover_color="darkgreen",
            width=100
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            command=dialog.destroy,
            fg_color="gray",
            width=100
        ).pack(side="left", padx=5)

    def _reset_settings(self):
        """설정 초기화"""
        if messagebox.askyesno(
            "설정 초기화",
            "정말 모든 설정을 초기화하시겠습니까?\n\n자동으로 백업이 생성된 후 초기화됩니다."
        ):
            try:
                # 자동 백업
                backup_path = self.settings_manager.create_backup("auto_before_reset")
                logger.info(f"초기화 전 자동 백업: {backup_path}")

                # 초기화
                self.settings_manager.reset_to_default()

                messagebox.showinfo(
                    "초기화 완료",
                    f"설정이 초기화되었습니다.\n\n자동 백업 경로:\n{backup_path}\n\n프로그램을 다시 시작해주세요."
                )
                logger.info("설정 초기화 완료")
            except Exception as e:
                messagebox.showerror("오류", f"초기화 실패:\n{e}")
                logger.error(f"설정 초기화 실패: {e}")

    def _open_stats_dashboard(self):
        """통계 대시보드 열기"""
        try:
            from gui.stats_dashboard import StatsDashboard
            dialog = StatsDashboard(self, self.production_stats)
        except ImportError:
            messagebox.showinfo("알림", "통계 대시보드 모듈이 없습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"통계 대시보드 오류: {e}")

    def _open_queue_manager(self):
        """큐 관리자 열기"""
        try:
            from gui.queue_manager_dialog import QueueManagerDialog
            # v58.3: 큐 실행 콜백 전달
            dialog = QueueManagerDialog(
                self,
                self.batch_queue,
                on_start_callback=self._run_queue
            )
        except ImportError:
            messagebox.showinfo("알림", "큐 관리 모듈이 없습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"큐 관리 오류: {e}")

    def _open_template_dialog(self):
        """템플릿 관리 다이얼로그 열기"""
        try:
            from gui.template_dialog import TemplateDialog
            dialog = TemplateDialog(self, self.template_manager)
            # 다이얼로그 닫힌 후 템플릿 목록 새로고침
            self.after(100, self._refresh_template_list)
        except ImportError:
            messagebox.showinfo("알림", "템플릿 관리 모듈이 없습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"템플릿 관리 오류: {e}")

    def _refresh_template_list(self):
        """템플릿 드롭다운 새로고침"""
        try:
            templates = self.template_manager.get_template_names()
            template_values = ["기본값"] + templates if templates else ["기본값"]
            self.template_dropdown.configure(values=template_values)
        except Exception as e:
            logger.warning(f"템플릿 목록 새로고침 실패: {e}")

    def _open_package_menu(self):
        """
        v38: 패키지 관리 메뉴 표시
        v56.1: Export는 관리자 전용으로 이동
        v57.7.3: 메뉴 텍스트 개선
        v57.7.6: 팩 생성 기능 제거 (관리자 전용 - license_generator_gui.py)
        """
        import tkinter as tk

        menu = tk.Menu(self, tearoff=0)

        # 팩 가져오기 (가장 자주 사용)
        menu.add_command(
            label="📥 팩 가져오기 (.revpack)",
            command=self._open_package_import
        )

        menu.add_separator()

        # 기타 기능
        # v57.7.6: 팩 생성 기능은 관리자 전용 (license_generator_gui.py)
        menu.add_command(
            label="🔍 팩 미리보기",
            command=self._load_revpack_to_studio
        )
        menu.add_command(
            label="📋 설치된 팩 목록",
            command=self._show_installed_packages
        )

        # 현재 팩 정보 (로드된 경우)
        try:
            from config.pack_config import ACTIVE_PACK
            if ACTIVE_PACK.is_loaded:
                menu.add_separator()
                menu.add_command(
                    label=f"ℹ️ 현재: {ACTIVE_PACK.pack_name}",
                    state="disabled"
                )
        except Exception as e:
            logger.debug(f"팩 정보 메뉴 추가 실패: {e}")

        # 버튼 위치에서 메뉴 표시
        try:
            x = self.package_btn.winfo_rootx()
            y = self.package_btn.winfo_rooty() + self.package_btn.winfo_height()
            menu.tk_popup(x, y)
        except Exception:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def _open_package_import(self):
        """v37: 패키지 가져오기 다이얼로그"""
        try:
            from gui.package_dialogs import PackageImportDialog
            dialog = PackageImportDialog(self, on_import_success=self._on_package_imported)
        except ImportError as e:
            messagebox.showinfo("알림", f"패키지 관리 모듈이 없습니다: {e}")
        except Exception as e:
            messagebox.showerror("오류", f"패키지 가져오기 오류: {e}")
            import traceback
            traceback.print_exc()

    def _show_installed_packages(self):
        """v37: 설치된 패키지 목록 표시"""
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            packages = pm.list_installed_packages()

            if not packages:
                messagebox.showinfo("패키지 목록", "설치된 패키지가 없습니다.")
                return

            # 간단한 목록 표시
            msg = "📦 설치된 패키지 목록:\n\n"
            for pkg_id, pkg_info in packages.items():
                msg += f"• {pkg_info.get('package_name', pkg_id)}\n"
                msg += f"  버전: {pkg_info.get('version', '1.0.0')}\n"
                msg += f"  작성자: {pkg_info.get('author', '알 수 없음')}\n\n"

            messagebox.showinfo("패키지 목록", msg)
        except Exception as e:
            messagebox.showerror("오류", f"패키지 목록 로드 실패: {e}")

    def _on_package_imported(self, result):
        """패키지 가져오기 완료 콜백"""
        self._add_log(f"📦 패키지 '{result.channel_id}' 가져오기 완료!")

        # v37: 채널 목록 자동 새로고침
        self._refresh_channel_list()

        # 새로 추가된 채널 자동 선택
        for ch_id, display, pkg_data in self.channel_options:
            if ch_id == result.channel_id:
                self.channel_dropdown.set(display)
                self.channel_var.set(ch_id)
                if pkg_data:
                    self._apply_package_settings(ch_id, pkg_data)
                break

        messagebox.showinfo("완료", f"채널 '{result.channel_id}'이(가) 성공적으로 추가되었습니다.\n\n채널 목록에서 선택하여 사용하세요.")

    def _load_revpack_to_studio(self):
        """v38: .revpack 파일을 로드하여 ScenarioEditor/ScriptPreview로 연동"""
        from tkinter import filedialog

        # 파일 선택
        filepath = filedialog.askopenfilename(
            title=".revpack 파일 선택",
            filetypes=[
                ("Reverie Pack", "*.revpack"),
                ("모든 파일", "*.*"),
            ],
            initialdir=os.path.join(config.DATA_DIR, "exports")
        )

        if not filepath:
            return

        try:
            # v57.7.0: ACTIVE_PACK에 로드 (프롬프트 시스템용)
            self._load_revpack_to_active(filepath)

            # revpack 로드
            from insight.revpack_generator import get_revpack_generator

            generator = get_revpack_generator()
            success, msg, revpack_data = generator.load_revpack(filepath)

            if not success:
                messagebox.showerror("로드 실패", msg)
                return

            self._add_log(f"[REVPACK] {msg}")

            # 주제 입력 받기
            topic = self._ask_revpack_topic(revpack_data)
            if topic is None:
                return  # 취소됨

            # plan_data로 변환
            plan_data = generator.revpack_to_plan_data(revpack_data, topic)

            self._add_log(f"[REVPACK] 주제: {topic}")
            self._add_log(f"[REVPACK] 채널: {plan_data.get('channel', 'unknown')}")

            # ScenarioEditor 또는 ScriptPreview 열기
            self._open_editor_with_revpack(plan_data)

        except ImportError as e:
            messagebox.showerror("모듈 오류", f"Revpack 모듈을 로드할 수 없습니다.\n\n{e}")
        except Exception as e:
            messagebox.showerror("오류", f".revpack 로드 중 오류가 발생했습니다.\n\n{e}")
            logger.error(f"Revpack 로드 오류: {e}", exc_info=True)

    def _ask_revpack_topic(self, revpack_data: dict) -> str:
        """revpack 로드 시 주제 선택/입력 다이얼로그"""
        from gui.main_window import get_font

        prompts = revpack_data.get("prompts", {})
        topics_data = prompts.get("topics", {})
        templates = topics_data.get("templates", [])

        # 간단한 입력 다이얼로그
        dialog = ctk.CTkToplevel(self)
        dialog.title("주제 선택")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        result = {"topic": None}
        topic_var = ctk.StringVar(value=templates[0] if templates else "")  # 항상 정의

        frame = ctk.CTkFrame(dialog, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="📝 주제를 선택하거나 입력하세요",
            font=get_font("medium", bold=True)
        ).pack(pady=(0, 15))

        # 추천 주제 목록
        if templates:
            ctk.CTkLabel(
                frame, text="추천 주제:", font=get_font("normal")
            ).pack(anchor="w")

            topic_dropdown = ctk.CTkComboBox(
                frame,
                values=templates[:5],  # 최대 5개
                variable=topic_var,
                width=350,
                font=get_font("normal")
            )
            topic_dropdown.pack(fill="x", pady=5)

        # 직접 입력
        ctk.CTkLabel(
            frame, text="또는 직접 입력:" if templates else "주제 입력:",
            font=get_font("normal")
        ).pack(anchor="w", pady=(10, 0))

        manual_entry = ctk.CTkEntry(
            frame,
            placeholder_text="주제를 직접 입력...",
            width=350,
            font=get_font("normal")
        )
        manual_entry.pack(fill="x", pady=5)

        def on_confirm():
            # 직접 입력 우선
            manual = manual_entry.get().strip()
            if manual:
                result["topic"] = manual
            elif topic_var.get():
                result["topic"] = topic_var.get()
            else:
                result["topic"] = "기본 주제"
            dialog.destroy()

        def on_cancel():
            result["topic"] = None
            dialog.destroy()

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))

        ctk.CTkButton(
            btn_frame, text="취소", width=100,
            fg_color="#757575", command=on_cancel
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame, text="확인", width=100,
            fg_color="#4CAF50", command=on_confirm
        ).pack(side="right", padx=5)

        dialog.wait_window()
        return result["topic"]

    def _open_editor_with_revpack(self, plan_data: dict):
        """revpack에서 로드된 plan_data로 에디터 열기"""
        try:
            # ScenarioEditor 시도
            from gui.scenario_editor import ScenarioEditorWindow

            def on_approve(approved_plan):
                """에디터에서 승인됨 → 제작 진행"""
                channel = approved_plan.get("channel", "horror")
                mode = approved_plan.get("mode", "horror")
                self._add_log(f"[REVPACK] 대본 승인됨 - 영상 제작 시작")
                self._start_production_with_plan(approved_plan, channel, mode)

            def on_save(saved_plan):
                """에디터에서 저장만 함"""
                self._add_log(f"[REVPACK] 대본 저장됨: {saved_plan.get('project_name', 'unknown')}")

            editor = ScenarioEditorWindow(
                self,
                plan_data=plan_data,
                on_save=on_save,
                on_approve=on_approve,
            )
            self._add_log(f"[REVPACK] ScenarioEditor 열림")

        except ImportError:
            # ScenarioEditor 없으면 ScriptPreviewDialog 사용
            try:
                from gui.script_preview_dialog import ScriptPreviewDialog

                def on_approve(approved_plan):
                    channel = approved_plan.get("channel", "horror")
                    mode = approved_plan.get("mode", "horror")
                    self._add_log(f"[REVPACK] 대본 승인됨 - 영상 제작 시작")
                    self._start_production_with_plan(approved_plan, channel, mode)

                dialog = ScriptPreviewDialog(
                    self,
                    plan_data,
                    on_approve=on_approve,
                )
                self._add_log(f"[REVPACK] ScriptPreviewDialog 열림")

            except ImportError as e:
                messagebox.showerror("모듈 오류", f"에디터 모듈을 로드할 수 없습니다.\n\n{e}")

    def _open_youtube_analytics(self):
        """YouTube 분석 다이얼로그 열기"""
        try:
            from gui.youtube_analytics_dialog import YouTubeAnalyticsDialog
            from utils.youtube_analytics import YouTubeAnalytics

            analytics = YouTubeAnalytics(config.DATA_DIR)
            dialog = YouTubeAnalyticsDialog(self, analytics)
        except ImportError as e:
            messagebox.showinfo("알림", f"YouTube 분석 모듈이 없습니다: {e}")
        except Exception as e:
            messagebox.showerror("오류", f"YouTube 분석 오류: {e}")

    def _open_auto_optimizer(self):
        """v54.1: 자동 최적화 다이얼로그 열기"""
        try:
            from gui.auto_optimizer_dialog import AutoOptimizerDialog

            channel_type, channel_id = self._resolve_auto_optimizer_target()
            dialog = AutoOptimizerDialog(
                self,
                config.DATA_DIR,
                channel_type,
                channel_id=channel_id,
            )
        except ImportError as e:
            messagebox.showinfo("알림", f"자동 최적화 모듈이 없습니다: {e}")
        except Exception as e:
            messagebox.showerror("오류", f"자동 최적화 오류: {e}")

    def _toggle_theme(self):
        """다크/라이트 테마 전환"""
        if self.current_theme == "dark":
            self.current_theme = "light"
            ctk.set_appearance_mode("light")
            self.theme_btn.configure(text="☀️")
        else:
            self.current_theme = "dark"
            ctk.set_appearance_mode("dark")
            self.theme_btn.configure(text="🌙")

    def _on_prompt_mode_change(self, mode: str):
        """v51: 프롬프트 모드 (Enhanced만 사용)"""
        if self.prompt_mode_desc:
            self.prompt_mode_desc.configure(
                text="✨ Enhanced: 고품질 스토리텔링 프롬프트"
            )

    def _on_tts_engine_change(self, engine: str):
        """v56.5: TTS 엔진 변경"""
        # GUI 설정 저장
        self.settings_manager.set_tts_engine(engine)

        # 런타임 config 업데이트
        config.TTS_ENGINE = engine

        # 설명 업데이트
        if self.tts_desc_label:
            self.tts_desc_label.configure(text=self._get_tts_description(engine))

        # 로그 출력
        if engine == "supertonic":
            self._add_log("[TTS] Supertonic 3 엔진으로 전환 (로컬 프리셋 음성 풀)")
            self._add_log("      ✓ 참조 음성 없이 M1-M5/F1-F5 프리셋 사용")
            self._add_log("      ✓ 쇼츠용 빠른 TTS 경로")
        else:
            self._add_log("[TTS] GPT-SoVITS 엔진으로 전환 (학습 기반)")
            self._add_log("      ✓ 사전 학습된 음성 모델 사용")
            self._add_log("      ✓ 감정별 참조 음성 필요")

    def _get_tts_description(self, engine: str) -> str:
        """TTS 엔진 설명 문자열 반환"""
        if engine == "supertonic":
            return "Supertonic 3: 참조 음성 없이 로컬 프리셋 음성 사용"
        return "SoVITS: 학습 기반, 감정별 참조 음성 사용"

    def _on_premium_mode_change(self):
        """v50: 프리미엄 영상 모드 변경 시 (현재 비활성화)"""
        # 프리미엄 모드 UI가 비활성화되어 호출되지 않지만, 안전을 위해 유지
        if self.premium_options_frame is None:
            return  # UI가 없으면 아무것도 안 함

        is_premium = self.premium_video_var.get()

        if is_premium:
            self.premium_options_frame.pack(fill="x", padx=12, pady=(0, 10))
            self._add_log("[INFO] 프리미엄 영상 모드 활성화 (현재 비활성화됨)")
            threading.Thread(target=self._check_comfyui_status, daemon=True).start()
        else:
            self.premium_options_frame.pack_forget()
            self._add_log("📷 일반 영상 모드 (정지 이미지)")

        self._update_estimated_time()

    def _on_test_mode_change(self):
        """v50: 테스트 모드 변경 시"""
        is_test = self.test_mode_var.get()
        config.TEST_MODE = is_test

        if is_test:
            self._add_log("[TEST] 테스트 모드 활성화 - 약 1분 영상 생성")
            self._add_log(f"   - 턴 수: {config.TEST_TURNS_PER_PART}턴 x 3파트 = {config.TEST_TURNS_PER_PART * 3}턴")
            self._add_log(f"   - 이미지: {config.TEST_IMAGE_COUNT}장")
        else:
            self._add_log("📹 [일반 모드] 활성화 - 전체 영상 생성")
            self._add_log("   - 턴 수: 50턴 x 3파트 = 150턴")
            self._add_log("   - 이미지: 40장")

    def _on_visual_storytelling_change(self):
        """v59.1.2: Visual Storytelling 모드 변경 시"""
        is_enabled = self.visual_storytelling_var.get()

        # 설정 저장
        self.settings_manager.set_visual_storytelling_enabled(is_enabled)

        # config에 반영 (VisualDirector에서 참조)
        if not hasattr(config, 'VISUAL_STORYTELLING_OVERRIDE'):
            config.VISUAL_STORYTELLING_OVERRIDE = None
        config.VISUAL_STORYTELLING_OVERRIDE = is_enabled

        if is_enabled:
            self._add_log("🎬 [v59] Visual Storytelling 활성화")
            self._add_log("   - 캐릭터 일관성 유지")
            self._add_log("   - 씬 분석 기반 프롬프트 생성")
            self._add_log("   - 시각 효과 + 자막 스타일 적용")
        else:
            self._add_log("📷 [일반 모드] Visual Storytelling 비활성화")
            self._add_log("   - 기존 라디오 드라마 방식으로 동작")

        # 팩 지원 여부 업데이트
        self._refresh_pack_feature_statuses()

    def _resolve_videotoon_backend(self, selected_label: str = "") -> str:
        """Resolve a GUI label or raw value into a supported VideoToon backend."""
        backend = selected_label or ""
        backend_map = getattr(self, "videotoon_backend_map", {}) or {}
        if backend in backend_map:
            backend = backend_map[backend]
        normalized = str(backend or "comfyui").strip().lower()
        return normalized if normalized in {"comfyui", "sd_webui"} else "comfyui"

    def _on_videotoon_local_change(self):
        """Persist and reflect the GUI opt-in for local VideoToon mode."""
        backend = self.settings_manager.get_videotoon_generation_backend()
        self.settings_manager.set_videotoon_local_enabled(True)
        config.VIDEOTOON_LOCAL_MODE_OVERRIDE = True
        if hasattr(self, "videotoon_local_var"):
            self.videotoon_local_var.set(True)
        self._add_log(f"[VideoToon] 영상툰 전용 모드 유지 (backend={backend})")

        self._update_videotoon_status()
        self._update_estimated_time()

    def _on_videotoon_backend_change(self, selected_label: str):
        """Persist and reflect the selected local VideoToon image backend."""
        backend = self._resolve_videotoon_backend(selected_label)
        self.settings_manager.set_videotoon_generation_backend(backend)
        config.VIDEOTOON_IMAGE_BACKEND = backend

        if hasattr(self, "videotoon_backend_var") and hasattr(self, "videotoon_backend_map"):
            label = next(
                (key for key, value in self.videotoon_backend_map.items() if value == backend),
                None,
            )
            if label and self.videotoon_backend_var.get() != label:
                self.videotoon_backend_var.set(label)

        self._add_log(f"[VideoToon] 이미지 백엔드 설정: {backend}")
        self._update_videotoon_status()

    def _update_videotoon_status(self):
        """Show local VideoToon GUI/runtime state."""
        if not hasattr(self, "videotoon_status_label") or self.videotoon_status_label is None:
            return

        enabled = self.settings_manager.get_videotoon_local_enabled()
        backend = self.settings_manager.get_videotoon_generation_backend()
        if enabled:
            self.videotoon_status_label.configure(
                text=f"VideoToon ON / {backend}",
                text_color="#4CAF50",
            )
        else:
            self.videotoon_status_label.configure(
                text=f"VideoToon OFF / {backend}",
                text_color="#888888",
            )
        self._update_videotoon_progress_status()

    def _format_videotoon_progress_summary(self, progress: dict | None) -> tuple[str, str]:
        """Return a compact Korean progress summary and label color."""
        if not progress:
            return "최근 VideoToon 진행 없음", "#888888"

        total = int(progress.get("total_scenes") or 0)
        completed = int(progress.get("completed_scenes") or 0)
        counts = dict(progress.get("status_counts") or {})
        failed = int(counts.get("failed") or 0)
        finalized = int(counts.get("finalized") or 0)
        generated = int(counts.get("generated") or 0)
        background_generated = int(counts.get("background_generated") or 0)
        submitted = int(counts.get("submitted") or 0)
        pending = int(counts.get("pending") or 0)

        parts = [f"VideoToon 진행 {completed}/{total}"]
        if finalized:
            parts.append(f"완료 {finalized}")
        if generated:
            parts.append(f"생성 {generated}")
        if background_generated:
            parts.append(f"배경 {background_generated}")
        if submitted:
            parts.append(f"대기중 {submitted}")
        if pending:
            parts.append(f"미시작 {pending}")
        if failed:
            parts.append(f"실패 {failed}")

        if failed:
            color = "#F44336"
        elif total and completed >= total:
            color = "#4CAF50"
        else:
            color = "#FF9800" if submitted or pending else "#AAAAAA"
        return " · ".join(parts), color

    def _update_videotoon_progress_status(self):
        """Show the newest VideoToon bundle progress without opening JSON files."""
        if not hasattr(self, "videotoon_progress_label") or self.videotoon_progress_label is None:
            return

        try:
            self.settings_manager.set_videotoon_local_enabled(True)

            from modules_pro.videotoon_local import VideoToonLocalWorkspace

            workspace = VideoToonLocalWorkspace.from_settings(config)
            progress = workspace.read_latest_bundle_progress()
            text, color = self._format_videotoon_progress_summary(progress)
            self.videotoon_progress_label.configure(text=text, text_color=color)
        except Exception as e:
            logger.debug(f"[VideoToon] progress status update failed: {e}")
            self.videotoon_progress_label.configure(text="VideoToon 진행 상태 확인 실패", text_color="#FF9800")

    def _on_motiontoon_render_mode_change(self, selected_label: str):
        """v63.1: 모션툰 비활성화됨 — 호출되지 않지만 하위호환 유지"""
        pass

    def _apply_motiontoon_render_mode(self, render_mode: str):
        """Persist and reflect the selected render mode."""
        self.settings_manager.set_motiontoon_render_mode(render_mode)
        config.MOTIONTOON_RENDER_MODE_OVERRIDE = render_mode

        if hasattr(self, "motiontoon_render_mode_var") and hasattr(self, "motiontoon_render_mode_map"):
            label = next(
                (key for key, value in self.motiontoon_render_mode_map.items() if value == render_mode),
                None,
            )
            if label and self.motiontoon_render_mode_var.get() != label:
                self.motiontoon_render_mode_var.set(label)

    def _sync_motiontoon_mode_with_pack(self, log_if_downgraded: bool = False):
        """Prevent unsupported pack/mode combinations from drifting silently."""
        try:
            from config.pack_config import get_motiontoon_support_info

            requested_mode = self.settings_manager.get_motiontoon_render_mode()
            support = get_motiontoon_support_info(requested_mode=requested_mode)
            if requested_mode == "classic_dynamic" and support.get("support_level") == "gishini":
                self._apply_motiontoon_render_mode("gishini_motiontoon")
                if log_if_downgraded:
                    self._add_log("[Motiontoon] 현재 팩은 Gishini Ready라서 Gishini Motiontoon으로 전환했습니다.")
                support = get_motiontoon_support_info(requested_mode="gishini_motiontoon")
            elif (
                requested_mode == "gishini_motiontoon"
                and support.get("effective_mode") != "gishini_motiontoon"
            ):
                self._apply_motiontoon_render_mode("classic_dynamic")
                if log_if_downgraded:
                    if support.get("reason") == "pack_basic_only":
                        self._add_log("[Motiontoon] 현재 팩은 Basic Only라서 Classic Dynamic으로 전환했습니다.")
                    elif support.get("reason") == "pack_disabled":
                        self._add_log("[Motiontoon] 현재 팩에서 Motiontoon이 비활성화되어 Classic Dynamic으로 전환했습니다.")
            self._update_motiontoon_status()
            return self.settings_manager.get_motiontoon_render_mode()
        except Exception:
            if getattr(self, "motiontoon_status_label", None) is not None:
                self.motiontoon_status_label.configure(text="", text_color="#888888")
            return "classic_dynamic"

    def _update_motiontoon_status(self):
        """Show pack-side motiontoon support in the GUI."""
        if getattr(self, "motiontoon_status_label", None) is None:
            return

        try:
            from config.pack_config import get_motiontoon_support_info

            requested_mode = self.settings_manager.get_motiontoon_render_mode()
            support = get_motiontoon_support_info(requested_mode=requested_mode)

            label_text = support.get("label", "")
            color = "#888888"
            if support.get("support_level") == "gishini":
                color = "#4CAF50"
            elif support.get("support_level") == "basic":
                color = "#FFA500"
            elif support.get("support_level") == "disabled":
                color = "#FF6B6B"

            if (
                requested_mode == "gishini_motiontoon"
                and support.get("effective_mode") != "gishini_motiontoon"
            ):
                label_text = f"{label_text} -> Classic"

            self.motiontoon_status_label.configure(text=label_text, text_color=color)
        except Exception:
            self.motiontoon_status_label.configure(text="", text_color="#888888")

    def _refresh_pack_feature_statuses(self):
        """Refresh pack-aware feature badges after pack/channel changes."""
        self._update_vs_status()
        self._sync_motiontoon_mode_with_pack(log_if_downgraded=False)
        self._update_videotoon_status()

    def _update_vs_status(self):
        """v59.1.2: Visual Storytelling 상태 라벨 업데이트"""
        try:
            from config import pack_config
            if pack_config.ACTIVE_PACK and hasattr(pack_config.ACTIVE_PACK, 'visual_storytelling'):
                vs_config = pack_config.ACTIVE_PACK.visual_storytelling
                # v59.1.6: dict/객체 양쪽 안전 처리
                vs_enabled = False
                if vs_config:
                    if isinstance(vs_config, dict):
                        vs_enabled = vs_config.get('enabled', False)
                    elif hasattr(vs_config, 'enabled'):
                        vs_enabled = vs_config.enabled
                if vs_enabled:
                    self.vs_status_label.configure(
                        text="✓ 팩 지원",
                        text_color="#4CAF50"
                    )
                else:
                    self.vs_status_label.configure(
                        text="⚠ 팩 미지원 (기본값 사용)",
                        text_color="#FFA500"
                    )
            else:
                self.vs_status_label.configure(
                    text="",
                    text_color="#888888"
                )
        except Exception:
            self.vs_status_label.configure(text="", text_color="#888888")

    def _on_template_select(self, template_name: str):
        """템플릿 선택 시"""
        if template_name == "기본값":
            return

        template = self.template_manager.get_template(template_name)
        if template:
            # 템플릿 설정 적용
            settings = template.get("settings", {})

            if "channel" in settings:
                self.channel_var.set(settings["channel"])

            if "quantity" in settings:
                self.quantity_var.set(settings["quantity"])

            if "topic_mode" in settings:
                self.topic_mode_var.set(settings["topic_mode"])

            if "auto_upload" in settings:
                self.auto_upload_var.set(settings["auto_upload"])

            # v53: 업로드 공개 설정
            if "upload_privacy" in settings:
                self.upload_privacy_var.set(settings["upload_privacy"])

            if "resume_from_checkpoint" in settings and hasattr(self, "resume_from_checkpoint_var"):
                self.resume_from_checkpoint_var.set(settings["resume_from_checkpoint"])

            # v37: 프롬프트 모드 적용
            if "prompt_mode" in settings:
                self.prompt_mode_var.set(settings["prompt_mode"])
                self._on_prompt_mode_change(settings["prompt_mode"])

            self._add_log(f"📄 템플릿 '{template_name}' 적용됨")

    def _update_estimated_time(self):
        """예상 시간 업데이트"""
        try:
            quantity = self.quantity_var.get()
            if isinstance(quantity, str):
                quantity = int(quantity.strip() or "1")
            if quantity < 1:
                quantity = 1

            # 예상 시간 계산
            estimated_seconds = self.production_stats.estimate_time(quantity)

            if estimated_seconds > 0:
                hours = estimated_seconds // 3600
                minutes = (estimated_seconds % 3600) // 60

                if hours > 0:
                    time_str = f"{hours}시간 {minutes}분"
                else:
                    time_str = f"{minutes}분"

                self.estimated_time_label.configure(
                    text=f"⏱️ 예상 시간: {time_str} ({quantity}개)",
                    text_color="lightblue"
                )
            else:
                self.estimated_time_label.configure(
                    text="⏱️ 예상 시간: 데이터 부족",
                    text_color="gray"
                )
        except Exception as e:
            logger.debug(f"예상 시간 업데이트 실패: {e}")

    def _load_recent_projects(self):
        """최근 프로젝트 목록 로드"""
        # 기존 위젯 삭제
        for widget in self.recent_projects_frame.winfo_children():
            widget.destroy()

        # 최근 성공한 프로젝트 가져오기
        recent = self.production_stats.get_recent_projects(5)

        if not recent:
            ctk.CTkLabel(
                self.recent_projects_frame,
                text="최근 프로젝트가 없습니다.",
                text_color="gray",
                font=ctk.CTkFont(size=11)
            ).pack(pady=10)
            return

        for project in recent:
            row = ctk.CTkFrame(self.recent_projects_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            # 프로젝트명
            name = project.get("project_name", "알 수 없음")[:30]
            ctk.CTkLabel(
                row,
                text=f"📹 {name}",
                font=ctk.CTkFont(size=11),
                anchor="w",
                width=200
            ).pack(side="left")

            # 채널
            channel = project.get("channel", "")
            ctk.CTkLabel(
                row,
                text=channel,
                font=ctk.CTkFont(size=10),
                text_color="gray",
                width=60
            ).pack(side="left")

            # 날짜
            date = project.get("date", "")[:10]
            ctk.CTkLabel(
                row,
                text=date,
                font=ctk.CTkFont(size=10),
                text_color="gray"
            ).pack(side="right")

    def _setup_drag_drop(self):
        """드래그앤드롭 설정"""
        # tkinterdnd2 사용 시도
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            # 드롭 대상 설정 (수동 주제 입력 필드)
            self.manual_topic_entry.drop_target_register(DND_FILES)
            self.manual_topic_entry.dnd_bind('<<Drop>>', self._on_file_drop)
        except ImportError:
            # tkinterdnd2가 없으면 안내 표시
            pass
        except Exception as e:
            logger.debug(f"드래그&드롭 설정 실패: {e}")

    def _on_file_drop(self, event):
        """파일 드롭 이벤트 처리"""
        try:
            file_path = event.data

            # 중괄호 제거 (Windows)
            if file_path.startswith('{') and file_path.endswith('}'):
                file_path = file_path[1:-1]

            if file_path.endswith('.txt'):
                # 텍스트 파일에서 주제 읽기
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()

                self.manual_topic_entry.delete(0, 'end')
                self.manual_topic_entry.insert(0, content[:200])
                self.topic_mode_var.set("manual")
                self._add_log(f"📂 파일에서 주제 로드: {os.path.basename(file_path)}")

            elif file_path.endswith('.json'):
                # JSON 파일에서 기획안 로드
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if "title" in data or "topic" in data:
                    topic = data.get("title") or data.get("topic", "")
                    self.manual_topic_entry.delete(0, 'end')
                    self.manual_topic_entry.insert(0, topic[:200])
                    self.topic_mode_var.set("manual")
                    self._add_log(f"📂 JSON에서 주제 로드: {os.path.basename(file_path)}")

        except Exception as e:
            self._add_log(f"[ERROR] 파일 로드 실패: {e}")

    def _save_current_as_template(self):
        """현재 설정을 템플릿으로 저장"""
        dialog = ctk.CTkInputDialog(
            text="템플릿 이름을 입력하세요:",
            title="템플릿 저장"
        )
        name = dialog.get_input()

        if name:
            settings = {
                "channel": self.channel_var.get(),
                "quantity": self.quantity_var.get(),
                "topic_mode": self.topic_mode_var.get(),
                "auto_upload": self.auto_upload_var.get(),
                "resume_from_checkpoint": self.resume_from_checkpoint_var.get(),
                "upload_privacy": self.upload_privacy_var.get()  # v53
            }

            self.template_manager.save_template(name, settings)
            self._refresh_template_list()
            messagebox.showinfo("저장 완료", f"템플릿 '{name}'이(가) 저장되었습니다.")

    def _show_language_dialog(self):
        """언어 선택 다이얼로그"""
        try:
            from utils.i18n import (
                get_current_lang, set_lang, get_available_languages,
                LANGUAGE_NAMES, save_language_setting, t
            )
        except ImportError:
            messagebox.showerror("오류", "다국어 모듈을 불러올 수 없습니다.")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("언어 선택 / Language / 言語")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()

        # 중앙 배치
        dialog.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 300) // 2
        dialog.geometry(f"400x300+{x}+{y}")

        ctk.CTkLabel(
            dialog,
            text="언어 선택",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(20, 10))

        # 현재 라이센스 타입
        license_type = 'A'
        if self.license_info:
            license_type = self.license_info.get('license_type', 'A') or self.license_info.get('type_code', 'A')

        available_langs = get_available_languages(license_type)
        current_lang = get_current_lang()

        # 언어 선택 라디오 버튼
        lang_var = ctk.StringVar(value=current_lang)
        lang_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        lang_frame.pack(pady=20)

        all_langs = ['ko', 'en', 'ja']

        for lang_code in all_langs:
            lang_name = LANGUAGE_NAMES.get(lang_code, lang_code)
            is_available = lang_code in available_langs

            frame = ctk.CTkFrame(lang_frame, fg_color="transparent")
            frame.pack(fill="x", pady=5)

            radio = ctk.CTkRadioButton(
                frame,
                text=lang_name,
                variable=lang_var,
                value=lang_code,
                font=ctk.CTkFont(size=14),
                state="normal" if is_available else "disabled"
            )
            radio.pack(side="left", padx=10)

            if not is_available:
                ctk.CTkLabel(
                    frame,
                    text="🔒 전체 라이센스 필요",
                    font=ctk.CTkFont(size=10),
                    text_color="orange"
                ).pack(side="left", padx=5)

        # 안내 메시지
        if license_type != 'A':
            ctk.CTkLabel(
                dialog,
                text="영어/일본어는 전체 이용 라이센스(A)가 필요합니다",
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(pady=10)

        def apply_language():
            selected_lang = lang_var.get()
            if set_lang(selected_lang, license_type):
                save_language_setting(config.DATA_DIR)
                # 버튼 텍스트 업데이트
                if self.lang_btn:
                    self.lang_btn.configure(text=f"🌐 {LANGUAGE_NAMES[selected_lang]}")
                dialog.destroy()
                messagebox.showinfo(
                    t("success"),
                    "언어가 변경되었습니다.\n일부 변경사항은 프로그램 재시작 후 적용됩니다."
                )
            else:
                messagebox.showerror("오류", "언어 변경에 실패했습니다.")

        # 버튼
        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=20)

        ctk.CTkButton(
            btn_frame,
            text="적용",
            width=100,
            command=apply_language
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_frame,
            text="취소",
            width=100,
            fg_color="gray",
            command=dialog.destroy
        ).pack(side="left", padx=10)
