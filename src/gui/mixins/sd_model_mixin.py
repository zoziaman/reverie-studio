# src/gui/mixins/sd_model_mixin.py
"""
v60.1.0: SD 모델 관리 Mixin — SD WebUI 모델 선택/로딩/새로고침

ReverieGUI에서 추출된 8개 메서드:
- _ensure_sd_webui_and_refresh: SD WebUI 자동 시작 + 모델 목록
- _refresh_sd_models: 모델 목록 새로고침
- _update_sd_model_dropdown: 드롭다운 UI 업데이트
- _update_sd_model_status: 팩 필수 모델 상태 표시
- _on_sd_model_selected: 모델 선택 콜백
- _open_model_manager: 모델 관리 다이얼로그
- _on_model_changed: 모델 변경 콜백
- _open_sd_model_manager: SD 모델 관리 다이얼로그

의존하는 self 변수:
- self.sd_model_var, self.sd_model_dropdown, self.sd_model_status_label
"""
import threading
from tkinter import messagebox

from utils.logger import get_logger

logger = get_logger("sd_model_mixin")


class SDModelMixin:
    """SD 모델 관리 횡단 관심사"""

    def _ensure_sd_webui_and_refresh(self):
        """
        v59.1.0: SD WebUI 자동 시작 + 모델 목록 새로고침

        GUI 시작 시 SD WebUI가 실행 중인지 확인하고,
        실행 중이 아니면 자동으로 시작한 후 모델 목록을 가져옴
        """
        def safe_after(delay, callback):
            """스레드 안전한 after 호출"""
            try:
                if self.winfo_exists():
                    self.after(delay, callback)
            except Exception as e:
                logger.debug(f"safe_after 호출 실패: {e}")

        def ensure_task():
            try:
                import requests

                # 1. SD WebUI 연결 확인
                try:
                    from config.settings import config
                    sd_url = config.SD_URL
                except Exception:
                    sd_url = "http://127.0.0.1:7860"

                safe_after(0, lambda: self.sd_model_status_label.configure(
                    text="SD WebUI 연결 확인 중...",
                    text_color="#888888"
                ))

                try:
                    res = requests.get(f"{sd_url}/sdapi/v1/sd-models", timeout=3)
                    if res.status_code == 200:
                        # 이미 실행 중 → 바로 모델 목록 새로고침
                        safe_after(0, lambda: self._add_log("[SD] SD WebUI 이미 실행 중"))
                        safe_after(100, self._refresh_sd_models)
                        return
                except (requests.RequestException, OSError):
                    pass

                # 2. SD WebUI 자동 시작
                safe_after(0, lambda: self.sd_model_status_label.configure(
                    text="SD WebUI 시작 중... (최대 3분)",
                    text_color="#FFA500"
                ))
                safe_after(0, lambda: self._add_log("[SD] SD WebUI 자동 시작 시도..."))

                try:
                    from utils.server_manager import get_server_manager
                    sm = get_server_manager()

                    # SD WebUI 시작 (start_server 사용)
                    success = sm.start_server("SD WebUI")

                    if success:
                        safe_after(0, lambda: self._add_log("[SD] SD WebUI 시작 완료!"))
                        safe_after(0, lambda: self.sd_model_status_label.configure(
                            text="SD WebUI 시작됨",
                            text_color="#4CAF50"
                        ))
                        # 시작 후 잠시 대기 후 모델 목록 새로고침
                        import time
                        time.sleep(2)
                        safe_after(0, self._refresh_sd_models)
                    else:
                        # 실패해도 일단 미연결 상태로 표시 (사용자가 수동 시작 가능)
                        safe_after(0, lambda: self._add_log("[SD] SD WebUI 자동시작 실패 - 새로고침 버튼으로 재시도"))
                        safe_after(0, lambda: self.sd_model_status_label.configure(
                            text="SD WebUI 미연결 - 새로고침 클릭",
                            text_color="#FFA500"
                        ))
                        safe_after(0, lambda: self._update_sd_model_dropdown(["SD WebUI 미연결"], ""))

                except ImportError as e:
                    logger.warning(f"[sd_model_mixin] server_manager import 실패: {e}")
                    safe_after(0, lambda: self._add_log("[SD] 수동으로 SD WebUI를 시작하세요"))
                    safe_after(0, lambda: self.sd_model_status_label.configure(
                        text="수동으로 SD WebUI를 시작하세요",
                        text_color="#FFA500"
                    ))
                    safe_after(0, lambda: self._update_sd_model_dropdown(["SD WebUI 미연결"], ""))
                except Exception as e:
                    logger.error(f"[sd_model_mixin] SD WebUI 시작 오류: {e}")
                    safe_after(0, lambda: self._add_log(f"[SD] 시작 오류: {str(e)[:30]}"))
                    safe_after(0, lambda: self.sd_model_status_label.configure(
                        text="SD WebUI 시작 오류 - 새로고침 클릭",
                        text_color="#FFA500"
                    ))
                    safe_after(0, lambda: self._update_sd_model_dropdown(["SD WebUI 미연결"], ""))

            except Exception as e:
                logger.error(f"[sd_model_mixin] SD WebUI 자동 시작 전체 오류: {e}")
                try:
                    safe_after(0, lambda: self._update_sd_model_dropdown(["오류"], ""))
                except Exception as e:
                    logger.debug(f"SD 오류 드롭다운 업데이트 실패: {e}")

        threading.Thread(target=ensure_task, daemon=True).start()

    def _refresh_sd_models(self):
        """
        v59.1.0: SD 모델 목록 새로고침

        SD WebUI에서 설치된 모델 목록을 조회하여 드롭다운 업데이트
        """
        def refresh_task():
            try:
                from config.pack_config import get_installed_sd_models, get_current_sd_model

                models = get_installed_sd_models()
                current = get_current_sd_model()

                if models:
                    model_titles = [m.get("title", m.get("model_name", "unknown")) for m in models]

                    # UI 업데이트 (메인 스레드)
                    self.after(0, lambda: self._update_sd_model_dropdown(model_titles, current))
                    self.after(0, lambda: self._add_log(f"[SD] 모델 {len(models)}개 감지"))
                else:
                    self.after(0, lambda: self._update_sd_model_dropdown(["SD WebUI 미연결"], ""))
                    self.after(0, lambda: self.sd_model_status_label.configure(
                        text="⚠️ SD WebUI에 연결할 수 없습니다",
                        text_color="#FFA500"
                    ))

            except Exception as e:
                logger.error(f"[sd_model_mixin] SD 모델 새로고침 실패: {e}")
                self.after(0, lambda: self._update_sd_model_dropdown(["오류"], ""))

        threading.Thread(target=refresh_task, daemon=True).start()

    def _update_sd_model_dropdown(self, model_titles: list, current_model: str):
        """SD 모델 드롭다운 업데이트"""
        self.sd_model_dropdown.configure(values=model_titles)

        if current_model:
            # 현재 모델을 찾아서 선택
            for title in model_titles:
                if current_model in title or title in current_model:
                    self.sd_model_var.set(title)
                    break
            else:
                # 정확히 일치하는 것 없으면 현재 모델 그대로 표시
                self.sd_model_var.set(current_model[:40] if len(current_model) > 40 else current_model)
        elif model_titles and model_titles[0] not in ["로딩 중...", "SD WebUI 미연결", "오류"]:
            self.sd_model_var.set(model_titles[0])

        # 팩의 필수 SD 모델 정보 표시
        self._update_sd_model_status()

    def _update_sd_model_status(self):
        """팩의 필수 SD 모델 상태 업데이트"""
        try:
            # SD WebUI 미연결 상태면 스킵 (불필요한 API 호출 방지)
            current_dropdown = self.sd_model_var.get()
            if current_dropdown in ["로딩 중...", "SD WebUI 미연결", "오류", ""]:
                return

            from config.pack_config import get_required_sd_model_info

            info = get_required_sd_model_info()

            if info.get("required"):
                message = info.get("message", "")
                color = "#4CAF50" if info.get("installed") else (
                    "#FFA500" if info.get("alternative_installed") else "#F44336"
                )
                self.sd_model_status_label.configure(text=message, text_color=color)

                # 필수 모델이 설치되어 있고 현재 다른 모델이면 자동 선택 제안
                if info.get("installed"):
                    required_name = info.get("filename", "").replace(".safetensors", "")
                    current = self.sd_model_var.get().lower()
                    if required_name.lower() not in current:
                        # 드롭다운에서 필수 모델 찾아서 자동 선택
                        for title in self.sd_model_dropdown.cget("values"):
                            if required_name.lower() in title.lower():
                                self.sd_model_var.set(title)
                                self._add_log(f"[SD] 권장 모델 자동 선택: {title[:30]}...")
                                break
            else:
                self.sd_model_status_label.configure(text="", text_color="#888888")

        except Exception as e:
            logger.debug(f"[sd_model_mixin] SD 모델 상태 업데이트 실패: {e}")

    def _on_sd_model_selected(self, selected: str):
        """
        v59.1.0: SD 모델 선택 시 콜백

        선택한 모델로 SD WebUI 옵션 변경
        """
        if selected in ["로딩 중...", "SD WebUI 미연결", "오류"]:
            return

        def change_task():
            try:
                from config.pack_config import set_sd_model

                self.after(0, lambda: self.sd_model_status_label.configure(
                    text="⏳ 모델 로딩 중...",
                    text_color="#FFA500"
                ))

                success = set_sd_model(selected)

                if success:
                    self.after(0, lambda: self._add_log(f"[SD] 모델 변경 완료: {selected[:30]}..."))
                    self.after(0, lambda: self.sd_model_status_label.configure(
                        text=f"✅ {selected[:25]}... 로드됨",
                        text_color="#4CAF50"
                    ))
                else:
                    self.after(0, lambda: self._add_log(f"[SD] ⚠️ 모델 변경 실패"))
                    self.after(0, lambda: self.sd_model_status_label.configure(
                        text="❌ 모델 변경 실패",
                        text_color="#F44336"
                    ))

            except Exception as e:
                logger.error(f"[sd_model_mixin] SD 모델 변경 오류: {e}")
                self.after(0, lambda: self.sd_model_status_label.configure(
                    text=f"❌ 오류: {str(e)[:30]}",
                    text_color="#F44336"
                ))

        threading.Thread(target=change_task, daemon=True).start()

    def _open_model_manager(self):
        """v33: 모델 관리 다이얼로그 열기"""
        try:
            from gui.model_manager_dialog import ModelManagerDialog
            dialog = ModelManagerDialog(self, on_change_callback=self._on_model_changed)
        except ImportError as e:
            messagebox.showinfo("알림", f"모델 관리 모듈이 없습니다: {e}")
        except Exception as e:
            messagebox.showerror("오류", f"모델 관리 오류: {e}")
            import traceback
            traceback.print_exc()

    def _on_model_changed(self):
        """모델 변경 시 콜백 (필요시 MediaFactory 재초기화)"""
        self._add_log("🎤 모델 설정이 변경되었습니다.")

    def _open_sd_model_manager(self):
        """v36: SD 모델 관리 다이얼로그 열기"""
        try:
            from gui.sd_model_dialog import SDModelDialog
            dialog = SDModelDialog(self)
        except ImportError as e:
            messagebox.showinfo("알림", f"SD 모델 관리 모듈이 없습니다: {e}")
        except Exception as e:
            messagebox.showerror("오류", f"SD 모델 관리 오류: {e}")
