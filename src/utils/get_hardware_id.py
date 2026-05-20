# get_hardware_id.py
"""
하드웨어 ID 확인 도구 (사용자용)

사용자가 이 스크립트를 실행하면
하드웨어 ID를 확인할 수 있습니다.
"""
import customtkinter as ctk
from tkinter import messagebox
from utils.hardware_id import get_hardware_id, get_system_info


class HardwareIDWindow(ctk.CTk):
    """하드웨어 ID 확인 창"""
    
    def __init__(self):
        super().__init__()
        
        self.title("하드웨어 ID 확인")
        self.geometry("500x400")
        self.resizable(False, False)
        
        # 중앙 정렬
        self.center_window()
        
        self._create_ui()
    
    def center_window(self):
        """창을 화면 중앙에 배치"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
    
    def _create_ui(self):
        """UI 생성"""
        # 타이틀
        title = ctk.CTkLabel(
            self,
            text="💻 하드웨어 ID 확인",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title.pack(pady=30)
        
        # 설명
        desc = ctk.CTkLabel(
            self,
            text="라이센스 발급을 위해 아래 하드웨어 ID를 개발자에게 전달하세요.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        desc.pack(pady=(0, 20))
        
        # 하드웨어 ID 프레임
        id_frame = ctk.CTkFrame(self)
        id_frame.pack(pady=20, padx=40, fill="x")
        
        ctk.CTkLabel(
            id_frame,
            text="하드웨어 ID:",
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(pady=(10, 5))
        
        # 하드웨어 ID 가져오기
        self.hw_id = get_hardware_id()
        
        # ID 표시 (읽기 전용)
        id_entry = ctk.CTkEntry(
            id_frame,
            width=400,
            height=50,
            font=ctk.CTkFont(size=18, weight="bold"),
            justify="center"
        )
        id_entry.insert(0, self.hw_id)
        id_entry.configure(state="readonly")
        id_entry.pack(pady=10, padx=10)
        
        # 복사 버튼
        copy_btn = ctk.CTkButton(
            id_frame,
            text="📋 클립보드에 복사",
            height=40,
            font=ctk.CTkFont(size=14),
            command=self._copy_to_clipboard
        )
        copy_btn.pack(pady=(10, 20))
        
        # 시스템 정보 (접기/펼치기)
        info_label = ctk.CTkLabel(
            self,
            text="▼ 시스템 정보 보기",
            font=ctk.CTkFont(size=11),
            text_color="blue",
            cursor="hand2"
        )
        info_label.pack(pady=10)
        info_label.bind("<Button-1>", lambda e: self._toggle_info())
        
        # 시스템 정보 프레임 (숨김 상태)
        self.info_frame = ctk.CTkFrame(self)
        self.info_visible = False
        
        info_text = ctk.CTkTextbox(self.info_frame, height=100)
        info_text.pack(padx=10, pady=10, fill="both", expand=True)
        
        # 시스템 정보 가져오기
        sys_info = get_system_info()
        for key, value in sys_info.items():
            info_text.insert("end", f"{key}: {value}\n")
        
        info_text.configure(state="disabled")
        
        # 안내 메시지
        guide = ctk.CTkLabel(
            self,
            text="※ 이 ID를 이메일이나 메신저로 개발자에게 전달하세요.",
            font=ctk.CTkFont(size=11),
            text_color="orange"
        )
        guide.pack(pady=(20, 10))
        
        # 닫기 버튼
        close_btn = ctk.CTkButton(
            self,
            text="닫기",
            width=200,
            height=40,
            command=self.destroy
        )
        close_btn.pack(pady=10)
    
    def _copy_to_clipboard(self):
        """클립보드에 복사"""
        try:
            import pyperclip
            pyperclip.copy(self.hw_id)
            messagebox.showinfo(
                "복사 완료",
                f"하드웨어 ID가 클립보드에 복사되었습니다!\n\n{self.hw_id}\n\n이제 개발자에게 전달하세요."
            )
        except ImportError:
            # pyperclip 없으면 기본 방법
            self.clipboard_clear()
            self.clipboard_append(self.hw_id)
            messagebox.showinfo(
                "복사 완료",
                f"하드웨어 ID가 클립보드에 복사되었습니다!\n\n{self.hw_id}\n\n이제 개발자에게 전달하세요."
            )
    
    def _toggle_info(self):
        """시스템 정보 표시/숨김"""
        if self.info_visible:
            self.info_frame.pack_forget()
            self.info_visible = False
            self.geometry("500x400")
        else:
            self.info_frame.pack(pady=10, padx=40, fill="both", expand=True)
            self.info_visible = True
            self.geometry("500x600")


def main():
    """실행"""
    # customtkinter 설정
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    
    app = HardwareIDWindow()
    app.mainloop()


if __name__ == "__main__":
    main()