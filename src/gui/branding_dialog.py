# src/gui/branding_dialog.py
"""
채널 브랜딩 설정 다이얼로그 (v38)
- 동적 채널 관리: 설치된 패키지 기반 자동 탭 생성
- 채널 추가/삭제 기능
- 각 채널별 인사말, 인트로 설정
"""
import customtkinter as ctk
import os
import json
import logging
from tkinter import filedialog, messagebox
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# 폰트 설정
FONT_FAMILY = "맑은 고딕"

def get_font(size: str = "normal", bold: bool = False) -> ctk.CTkFont:
    sizes = {"small": 12, "normal": 13, "medium": 14, "large": 16, "title": 20}
    return ctk.CTkFont(
        family=FONT_FAMILY,
        size=sizes.get(size, 13),
        weight="bold" if bold else "normal"
    )


class BrandingDialog(ctk.CTkToplevel):
    """동적 채널 브랜딩 설정 다이얼로그"""

    def __init__(self, parent, config_data: Dict[str, Any]):
        super().__init__(parent)

        self.title("📺 채널 브랜딩 설정")
        self.geometry("750x750")
        self.config_data = config_data if config_data else {}

        # 부모 창에 종속 + 모달
        self.transient(parent)
        self.grab_set()
        # 최소화 가능하도록 topmost 제거

        # 채널 입력 데이터 저장
        self.channel_inputs: Dict[str, Dict[str, Any]] = {}
        self.channel_tabs: Dict[str, Any] = {}

        self._create_ui()

    def _create_ui(self):
        """UI 구성"""
        # 메인 컨테이너
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 제목
        title_label = ctk.CTkLabel(
            main_frame,
            text="📺 채널 브랜딩 설정",
            font=get_font("title", bold=True)
        )
        title_label.pack(pady=(0, 10))

        # 설명
        desc_label = ctk.CTkLabel(
            main_frame,
            text="각 채널별로 채널명, 인트로 영상, 오프닝 인사말을 설정할 수 있습니다.",
            font=get_font("normal"),
            text_color="#aaaaaa"
        )
        desc_label.pack(pady=(0, 15))

        # 채널 추가 버튼 프레임
        add_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        add_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkButton(
            add_frame,
            text="➕ 새 채널 추가",
            font=get_font("normal"),
            width=140,
            height=32,
            fg_color="#00796B",
            hover_color="#00695C",
            command=self._add_new_channel
        ).pack(side="left")

        ctk.CTkButton(
            add_frame,
            text="🔄 패키지에서 불러오기",
            font=get_font("normal"),
            width=170,
            height=32,
            fg_color="#1565C0",
            hover_color="#0D47A1",
            command=self._load_from_packages
        ).pack(side="left", padx=(10, 0))

        # 탭뷰 생성
        self.tabview = ctk.CTkTabview(main_frame)
        self.tabview.pack(fill="both", expand=True, pady=(0, 15))

        # 기존 채널 데이터로 탭 생성
        self._load_existing_channels()

        # 하단 버튼
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", side="bottom")

        ctk.CTkButton(
            button_frame,
            text="💾 설정 저장",
            font=get_font("normal"),
            width=120,
            height=36,
            fg_color="green",
            hover_color="darkgreen",
            command=self._on_save
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            button_frame,
            text="취소",
            font=get_font("normal"),
            width=100,
            height=36,
            fg_color="gray40",
            command=self.destroy
        ).pack(side="right", padx=5)

    def _load_existing_channels(self):
        """기존 채널 데이터로 탭 생성"""
        if not self.config_data:
            return

        for channel_id, channel_data in self.config_data.items():
            if isinstance(channel_data, dict):
                channel_name = channel_data.get("channel_name", channel_id)
                display_name = channel_name if channel_name else channel_id
                self._create_channel_tab(channel_id, display_name, channel_data)

    def _load_from_packages(self):
        """설치된 패키지에서 채널 정보 불러오기"""
        try:
            from utils.package_manager import get_package_manager
            pm = get_package_manager()
            installed = pm.list_installed_packages()

            if not installed:
                messagebox.showinfo("알림", "설치된 패키지가 없습니다.")
                return

            added_count = 0
            for pkg_id, pkg_info in installed.items():
                channel_id = pkg_info.get('channel_id', pkg_id)

                # 이미 있는 채널은 건너뛰기
                if channel_id in self.channel_tabs:
                    continue

                pkg_name = pkg_info.get('package_name', pkg_id)

                # 새 탭 생성
                self._create_channel_tab(channel_id, f"📦 {pkg_name}", {})
                added_count += 1

            if added_count > 0:
                messagebox.showinfo("완료", f"{added_count}개의 채널이 추가되었습니다.")
            else:
                messagebox.showinfo("알림", "추가할 새 채널이 없습니다.\n(이미 모든 패키지가 등록되어 있습니다)")

        except Exception as e:
            messagebox.showerror("오류", f"패키지 로드 실패: {e}")

    def _add_new_channel(self):
        """새 채널 추가 다이얼로그"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("새 채널 추가")
        dialog.geometry("400x200")
        dialog.transient(self)
        dialog.grab_set()

        # 중앙 배치
        dialog.update_idletasks()
        x = (self.winfo_screenwidth() - 400) // 2
        y = (self.winfo_screenheight() - 200) // 2
        dialog.geometry(f"400x200+{x}+{y}")

        frame = ctk.CTkFrame(dialog)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="새 채널 추가",
            font=get_font("medium", bold=True)
        ).pack(pady=(0, 15))

        # 채널 ID
        id_frame = ctk.CTkFrame(frame, fg_color="transparent")
        id_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(id_frame, text="채널 ID:", width=80, font=get_font("normal")).pack(side="left")
        id_entry = ctk.CTkEntry(id_frame, width=200, height=32, font=get_font("normal"),
                                 placeholder_text="영문, 숫자, 언더스코어")
        id_entry.pack(side="left", padx=5)

        # 채널명
        name_frame = ctk.CTkFrame(frame, fg_color="transparent")
        name_frame.pack(fill="x", pady=5)

        ctk.CTkLabel(name_frame, text="채널명:", width=80, font=get_font("normal")).pack(side="left")
        name_entry = ctk.CTkEntry(name_frame, width=200, height=32, font=get_font("normal"),
                                   placeholder_text="표시될 채널 이름")
        name_entry.pack(side="left", padx=5)

        def add_channel():
            channel_id = id_entry.get().strip()
            channel_name = name_entry.get().strip()

            if not channel_id:
                messagebox.showerror("오류", "채널 ID를 입력하세요.")
                return

            # 영문, 숫자, 언더스코어만 허용
            import re
            if not re.match(r'^[a-zA-Z0-9_]+$', channel_id):
                messagebox.showerror("오류", "채널 ID는 영문, 숫자, 언더스코어만 사용 가능합니다.")
                return

            if channel_id in self.channel_tabs:
                messagebox.showerror("오류", f"'{channel_id}' 채널이 이미 존재합니다.")
                return

            display_name = channel_name if channel_name else channel_id
            self._create_channel_tab(channel_id, display_name, {"channel_name": channel_name})
            dialog.destroy()
            messagebox.showinfo("완료", f"'{display_name}' 채널이 추가되었습니다.")

        # 버튼
        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(15, 0))

        ctk.CTkButton(
            btn_frame, text="추가", width=80, height=32,
            font=get_font("normal"),
            fg_color="green", hover_color="darkgreen",
            command=add_channel
        ).pack(side="right", padx=5)

        ctk.CTkButton(
            btn_frame, text="취소", width=80, height=32,
            font=get_font("normal"),
            fg_color="gray40",
            command=dialog.destroy
        ).pack(side="right")

    def _create_channel_tab(self, channel_id: str, display_name: str, data: Dict):
        """채널 탭 생성"""
        try:
            tab = self.tabview.add(display_name)
        except Exception:
            # 같은 이름의 탭이 있으면 ID 추가
            tab = self.tabview.add(f"{display_name} ({channel_id})")

        self.channel_tabs[channel_id] = tab
        self.channel_inputs[channel_id] = {"display_name": display_name}

        # 스크롤 가능한 프레임
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # 채널 삭제 버튼
        del_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        del_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            del_frame,
            text=f"채널 ID: {channel_id}",
            font=get_font("small"),
            text_color="#888888"
        ).pack(side="left")

        ctk.CTkButton(
            del_frame,
            text="🗑️ 이 채널 삭제",
            font=get_font("small"),
            width=120,
            height=28,
            fg_color="#C62828",
            hover_color="#B71C1C",
            command=lambda cid=channel_id, dn=display_name: self._delete_channel(cid, dn)
        ).pack(side="right")

        # 1. 채널명
        ctk.CTkLabel(
            scroll, text="채널명:",
            font=get_font("normal", bold=True)
        ).pack(anchor="w", pady=(10, 5))

        name_entry = ctk.CTkEntry(scroll, width=400, height=32, font=get_font("normal"))
        name_entry.insert(0, data.get("channel_name", ""))
        name_entry.pack(anchor="w", pady=(0, 10))
        self.channel_inputs[channel_id]["channel_name"] = name_entry

        # 2. 인트로 영상
        ctk.CTkLabel(
            scroll, text="인트로 영상 파일:",
            font=get_font("normal", bold=True)
        ).pack(anchor="w", pady=(10, 5))

        intro_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        intro_frame.pack(fill="x", pady=(0, 10))

        intro_entry = ctk.CTkEntry(intro_frame, width=320, height=32, font=get_font("normal"))
        intro_entry.insert(0, data.get("intro_file", ""))
        intro_entry.pack(side="left", padx=(0, 10))
        self.channel_inputs[channel_id]["intro_file"] = intro_entry

        def browse_intro(entry=intro_entry):
            path = filedialog.askopenfilename(
                filetypes=[("Video files", "*.mp4 *.mov *.avi *.mkv")]
            )
            if path:
                entry.delete(0, "end")
                entry.insert(0, path)

        ctk.CTkButton(
            intro_frame, text="찾아보기",
            width=90, height=32, font=get_font("normal"),
            command=browse_intro
        ).pack(side="left")

        # 3. 오프닝 인사말
        ctk.CTkLabel(
            scroll, text="오프닝 인사말 (랜덤 선택):",
            font=get_font("normal", bold=True)
        ).pack(anchor="w", pady=(10, 5))

        openings_frame = ctk.CTkFrame(scroll)
        openings_frame.pack(fill="x", pady=(0, 10))

        openings_scroll = ctk.CTkScrollableFrame(openings_frame, height=120)
        openings_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        opening_entries = []
        self.channel_inputs[channel_id]["opening_entries"] = opening_entries

        def add_opening_field(text="", container=openings_scroll, entries=opening_entries):
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", pady=2)

            entry = ctk.CTkEntry(row, width=380, height=30, font=get_font("normal"))
            entry.insert(0, text)
            entry.pack(side="left", padx=(0, 5))
            entries.append(entry)

            def remove():
                row.destroy()
                if entry in entries:
                    entries.remove(entry)

            ctk.CTkButton(
                row, text="X", width=30, height=30,
                fg_color="#C62828", hover_color="#B71C1C",
                command=remove
            ).pack(side="left")

        # 기존 인사말 로드
        for opening in data.get("openings", []):
            add_opening_field(opening)

        ctk.CTkButton(
            scroll, text="➕ 인사말 추가",
            width=140, height=32, font=get_font("normal"),
            command=lambda: add_opening_field()
        ).pack(anchor="w", pady=(5, 15))

    def _delete_channel(self, channel_id: str, display_name: str):
        """채널 삭제"""
        if not messagebox.askyesno("확인", f"'{display_name}' 채널을 삭제하시겠습니까?\n\n이 작업은 브랜딩 설정만 삭제하며,\n설치된 패키지는 유지됩니다."):
            return

        try:
            # 탭 삭제
            self.tabview.delete(display_name)
        except Exception:
            # display_name으로 삭제 실패 시 다른 방법 시도
            try:
                self.tabview.delete(f"{display_name} ({channel_id})")
            except Exception as e:
                logger.debug(f"탭 삭제 실패 (무시): {e}")

        # 데이터 삭제
        if channel_id in self.channel_tabs:
            del self.channel_tabs[channel_id]
        if channel_id in self.channel_inputs:
            del self.channel_inputs[channel_id]

        messagebox.showinfo("완료", f"'{display_name}' 채널이 삭제되었습니다.")

    def _on_save(self):
        """설정 저장"""
        new_config = {}

        for channel_id, inputs in self.channel_inputs.items():
            channel_name_entry = inputs.get("channel_name")
            intro_entry = inputs.get("intro_file")
            opening_entries = inputs.get("opening_entries", [])

            new_config[channel_id] = {
                "channel_name": channel_name_entry.get().strip() if channel_name_entry else "",
                "intro_file": intro_entry.get().strip() if intro_entry else "",
                "openings": [e.get().strip() for e in opening_entries if e.get().strip()]
            }

        # 저장
        from config.settings import config
        path = os.path.join(config.DATA_DIR, "branding.json")

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new_config, f, indent=2, ensure_ascii=False)

            messagebox.showinfo("성공", "채널 브랜딩 설정이 저장되었습니다.\n다음 영상 제작부터 적용됩니다.")
            self.destroy()

        except Exception as e:
            messagebox.showerror("오류", f"설정 저장 중 오류가 발생했습니다: {e}")
