# Reverie Factory - GUI 탭 컴포넌트
# Version: 1.2.0

"""
Factory 탭 - 팩 설계 AI GUI

기능:
1. 수동 설정으로 채널 팩 설계
2. Insight 분석 결과 불러와서 설계
3. SD 모델 추천 + Civitai 링크
4. 목소리 가이드 생성
5. .revpack 내보내기 (라이센스 검증 포함)
6. 채널 클론 팩 생성 (채널 분석 기반)

v1.2.0:
- ClonePackGenerator 연동
- 채널 분석 → 클론 팩 자동 생성

v1.1.0:
- 라이센스 검증 추가 (.revpack 내보내기 시)
- 암호화 옵션 추가
"""

import os
import sys
import json
import threading
import webbrowser
from datetime import datetime
from typing import Optional, List, Dict, Callable
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox, filedialog

# 경로 설정
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

# 로컬 모듈
try:
    from factory.pack_designer import (
        PackDesigner, ChannelPackDesign,
        format_design_summary, ChannelGenre
    )
    DESIGNER_AVAILABLE = True
except ImportError:
    DESIGNER_AVAILABLE = False

# 클론 팩 생성기
try:
    from factory.clone_pack_generator import ClonePackGenerator, ClonePackContent
    CLONE_GENERATOR_AVAILABLE = True
except ImportError:
    CLONE_GENERATOR_AVAILABLE = False
    ClonePackContent = None  # 타입 힌트용 폴백

# 폰트 유틸리티
try:
    from utils.font_utils import get_font
except ImportError:
    def get_font(size="medium", bold=False):
        sizes = {"small": 11, "medium": 13, "large": 16, "title": 20}
        return ctk.CTkFont(size=sizes.get(size, 13), weight="bold" if bold else "normal")


class FactoryTab(ctk.CTkFrame):
    """Factory 탭 - 팩 설계 AI"""

    def __init__(
        self,
        parent,
        settings_path: str = None,
        **kwargs
    ):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.settings_path = settings_path

        # 상태
        self.designer: Optional[PackDesigner] = None
        self.current_design: Optional[ChannelPackDesign] = None
        self.is_designing = False

        # 클론 팩 관련
        self.clone_generator: Optional[ClonePackGenerator] = None
        self.current_clone_pack: Optional[ClonePackContent] = None
        self.channel_analysis_data: Optional[Dict] = None  # 채널 분석 데이터

        # API 키 로드
        self.api_key = self._load_api_key()

        # Designer 초기화
        if DESIGNER_AVAILABLE:
            try:
                self.designer = PackDesigner(gemini_api_key=self.api_key)
            except Exception as e:
                print(f"[Factory] Designer 초기화 실패: {e}")

        # ClonePackGenerator 초기화
        if CLONE_GENERATOR_AVAILABLE:
            try:
                self.clone_generator = ClonePackGenerator(gemini_api_key=self.api_key)
            except Exception as e:
                print(f"[Factory] ClonePackGenerator 초기화 실패: {e}")

        # UI 구성
        self._create_ui()

    def _load_api_key(self) -> str:
        """API 키 로드"""
        if self.settings_path and os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    return settings.get("gemini_api_key", "")
            except (json.JSONDecodeError, OSError):
                pass
        return os.environ.get("GEMINI_API_KEY", "")

    # ============================================================
    # UI 구성
    # ============================================================

    def _create_ui(self):
        """UI 생성"""
        # 메인 스크롤 프레임
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_scroll.pack(fill="both", expand=True, padx=10, pady=10)

        # 헤더
        self._create_header()

        # 입력 섹션
        self._create_input_section()

        # 액션 버튼
        self._create_action_buttons()

        # 결과 섹션
        self._create_result_section()

    def _create_header(self):
        """헤더 생성"""
        header_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_frame,
            text="🏭 Factory - 팩 설계 AI",
            font=get_font("title", bold=True)
        ).pack(side="left")

        # 상태 표시
        self.status_label = ctk.CTkLabel(
            header_frame,
            text="✅ 준비" if DESIGNER_AVAILABLE else "⚠️ Designer 모듈 없음",
            font=get_font("small"),
            text_color="#4CAF50" if DESIGNER_AVAILABLE else "#FF9800"
        )
        self.status_label.pack(side="right")

    def _create_input_section(self):
        """입력 섹션 생성"""
        input_frame = ctk.CTkFrame(self.main_scroll)
        input_frame.pack(fill="x", pady=(0, 15))

        # 제목
        ctk.CTkLabel(
            input_frame,
            text="📝 팩 설정",
            font=get_font("large", bold=True)
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # 그리드 설정
        grid_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        grid_frame.pack(fill="x", padx=15, pady=(0, 15))

        # Row 1: 장르 선택
        ctk.CTkLabel(
            grid_frame, text="장르:", font=get_font("medium")
        ).grid(row=0, column=0, sticky="w", pady=5)

        self.genre_var = ctk.StringVar(value="horror")
        genre_options = ["horror", "mystery", "emotional", "documentary", "entertainment", "asmr", "education"]
        self.genre_combo = ctk.CTkComboBox(
            grid_frame,
            values=genre_options,
            variable=self.genre_var,
            width=200,
            font=get_font("medium")
        )
        self.genre_combo.grid(row=0, column=1, sticky="w", padx=10, pady=5)

        # Row 2: 테마 입력
        ctk.CTkLabel(
            grid_frame, text="테마:", font=get_font("medium")
        ).grid(row=1, column=0, sticky="w", pady=5)

        self.theme_entry = ctk.CTkEntry(
            grid_frame,
            width=300,
            placeholder_text="예: 학교 괴담, 미제 사건, 감동 실화...",
            font=get_font("medium")
        )
        self.theme_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        # Row 3: 비주얼 스타일
        ctk.CTkLabel(
            grid_frame, text="비주얼 스타일:", font=get_font("medium")
        ).grid(row=2, column=0, sticky="w", pady=5)

        self.style_var = ctk.StringVar(value="silhouette")
        style_options = ["silhouette", "anime", "realistic", "cartoon", "cinematic", "lofi"]
        self.style_combo = ctk.CTkComboBox(
            grid_frame,
            values=style_options,
            variable=self.style_var,
            width=200,
            font=get_font("medium")
        )
        self.style_combo.grid(row=2, column=1, sticky="w", padx=10, pady=5)

        # Row 4: 채널명 (선택)
        ctk.CTkLabel(
            grid_frame, text="채널명 (선택):", font=get_font("medium")
        ).grid(row=3, column=0, sticky="w", pady=5)

        self.channel_entry = ctk.CTkEntry(
            grid_frame,
            width=300,
            placeholder_text="비워두면 AI가 자동 생성",
            font=get_font("medium")
        )
        self.channel_entry.grid(row=3, column=1, sticky="w", padx=10, pady=5)

        # Insight 연동 버튼
        insight_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        insight_frame.pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkButton(
            insight_frame,
            text="📥 Insight 분석 결과 불러오기",
            width=220,
            height=35,
            font=get_font("medium"),
            fg_color="#9C27B0",
            hover_color="#7B1FA2",
            command=self._load_from_insight
        ).pack(side="left")

        ctk.CTkButton(
            insight_frame,
            text="📦 .revpack에서 불러오기",
            width=200,
            height=35,
            font=get_font("medium"),
            fg_color="#FF9800",
            hover_color="#F57C00",
            command=self._load_from_revpack
        ).pack(side="left", padx=10)

    def _create_action_buttons(self):
        """액션 버튼 생성"""
        btn_frame = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 15))

        # 설계 시작 버튼
        self.design_btn = ctk.CTkButton(
            btn_frame,
            text="🚀 팩 설계 시작",
            width=180,
            height=45,
            font=get_font("large", bold=True),
            fg_color="#4CAF50",
            hover_color="#388E3C",
            command=self._start_design
        )
        self.design_btn.pack(side="left")

        # 프로그레스
        self.progress_label = ctk.CTkLabel(
            btn_frame,
            text="",
            font=get_font("medium"),
            text_color="#888888"
        )
        self.progress_label.pack(side="left", padx=20)

    def _create_result_section(self):
        """결과 섹션 생성"""
        self.result_frame = ctk.CTkFrame(self.main_scroll)
        self.result_frame.pack(fill="both", expand=True)

        # 제목
        header = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(15, 10))

        ctk.CTkLabel(
            header,
            text="📊 설계 결과",
            font=get_font("large", bold=True)
        ).pack(side="left")

        # 내보내기 버튼들
        self.export_btn = ctk.CTkButton(
            header,
            text="📦 .revpack 내보내기",
            width=150,
            height=32,
            font=get_font("medium"),
            fg_color="#2196F3",
            hover_color="#1976D2",
            state="disabled",
            command=self._export_revpack
        )
        self.export_btn.pack(side="right")

        self.json_btn = ctk.CTkButton(
            header,
            text="💾 JSON 저장",
            width=100,
            height=32,
            font=get_font("medium"),
            fg_color="#757575",
            hover_color="#616161",
            state="disabled",
            command=self._save_json
        )
        self.json_btn.pack(side="right", padx=5)

        # 탭뷰
        self.result_tabs = ctk.CTkTabview(self.result_frame, height=400)
        self.result_tabs.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # 탭 생성
        self.tab_summary = self.result_tabs.add("요약")
        self.tab_models = self.result_tabs.add("SD 모델")
        self.tab_voice = self.result_tabs.add("목소리 가이드")
        self.tab_topics = self.result_tabs.add("토픽 제안")

        # 요약 탭
        self.summary_text = ctk.CTkTextbox(
            self.tab_summary,
            font=get_font("medium"),
            wrap="word"
        )
        self.summary_text.pack(fill="both", expand=True)

        # SD 모델 탭
        self.models_scroll = ctk.CTkScrollableFrame(self.tab_models)
        self.models_scroll.pack(fill="both", expand=True)

        # 목소리 가이드 탭
        self.voice_text = ctk.CTkTextbox(
            self.tab_voice,
            font=get_font("medium"),
            wrap="word"
        )
        self.voice_text.pack(fill="both", expand=True)

        # 토픽 탭
        self.topics_text = ctk.CTkTextbox(
            self.tab_topics,
            font=get_font("medium"),
            wrap="word"
        )
        self.topics_text.pack(fill="both", expand=True)

    # ============================================================
    # 기능 구현
    # ============================================================

    def _start_design(self):
        """팩 설계 시작"""
        if self.is_designing:
            return

        # 채널 분석 데이터가 있으면 클론 팩 생성
        if self.channel_analysis_data and self.clone_generator:
            self._start_clone_pack_generation()
            return

        # 기존 수동 설계 로직
        if not self.designer:
            messagebox.showerror("오류", "Designer 모듈을 사용할 수 없습니다.")
            return

        # 입력값 수집
        config = {
            "genre": self.genre_var.get(),
            "theme": self.theme_entry.get().strip(),
            "style_type": self.style_var.get(),
        }

        channel_name = self.channel_entry.get().strip()
        if channel_name:
            config["channel_name"] = channel_name

        self.is_designing = True
        self.design_btn.configure(state="disabled")
        self.progress_label.configure(text="🔄 AI가 팩을 설계하고 있습니다...")

        # 백그라운드 스레드에서 실행
        thread = threading.Thread(
            target=self._design_thread,
            args=(config,),
            daemon=True
        )
        thread.start()

    def _start_clone_pack_generation(self):
        """채널 분석 기반 클론 팩 생성 시작"""
        self.is_designing = True
        self.design_btn.configure(state="disabled")
        self.progress_label.configure(text="🔄 클론 팩을 생성하고 있습니다...")

        thread = threading.Thread(
            target=self._clone_pack_thread,
            daemon=True
        )
        thread.start()

    def _clone_pack_thread(self):
        """클론 팩 생성 스레드"""
        try:
            def progress_callback(current, total, stage):
                self.parent.after(0, lambda: self.progress_label.configure(
                    text=f"🔄 {stage}... ({current}%)"
                ))

            pack = self.clone_generator.generate_clone_pack(
                channel_analysis=self.channel_analysis_data,
                num_topics=30,
                progress_callback=progress_callback
            )
            self.parent.after(0, lambda: self._on_clone_pack_complete(pack))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.parent.after(0, lambda: self._on_clone_pack_error(str(e)))

    def _on_clone_pack_complete(self, pack):
        """클론 팩 생성 완료 콜백"""
        self.is_designing = False
        self.design_btn.configure(state="normal")
        self.progress_label.configure(text="✅ 클론 팩 생성 완료!")

        self.current_clone_pack = pack

        # 버튼 활성화
        self.export_btn.configure(state="normal")
        self.json_btn.configure(state="normal")

        # 결과 표시
        self._display_clone_pack(pack)

    def _on_clone_pack_error(self, error_msg: str):
        """클론 팩 생성 오류 콜백"""
        self.is_designing = False
        self.design_btn.configure(state="normal")
        self.progress_label.configure(text="❌ 생성 실패")

        messagebox.showerror("클론 팩 생성 오류", f"팩 생성 중 오류가 발생했습니다.\n\n{error_msg}")

    def _display_clone_pack(self, pack):
        """클론 팩 결과 표시"""
        # 요약 탭
        self.summary_text.delete("1.0", "end")
        summary = f"""📦 클론 팩 생성 완료

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📺 원본 채널: {pack.source_channel}
🆔 팩 ID: {pack.pack_id}
📅 생성일: {pack.created_at[:10]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 생성된 콘텐츠:
  • 시나리오 프롬프트 (pd_system.txt)
  • 대사 스타일 가이드 (writer_system.txt)
  • 토픽 {len(pack.topics)}개 (줄거리 포함)
  • SD 이미지 프롬프트
  • 스타일 가이드 (색감, 모델)
  • 감정 가이드 + 샘플 대사
  • TTS 학습 가이드

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📂 .revpack 내보내기로 저장하세요!
"""
        self.summary_text.insert("1.0", summary)

        # SD 모델 탭 - 스타일 가이드로 대체
        for widget in self.models_scroll.winfo_children():
            widget.destroy()

        style_frame = ctk.CTkFrame(self.models_scroll)
        style_frame.pack(fill="x", pady=5, padx=5)

        ctk.CTkLabel(
            style_frame,
            text="🎨 비주얼 스타일",
            font=get_font("medium", bold=True)
        ).pack(anchor="w", padx=10, pady=(10, 5))

        style_info = pack.style_guide
        color_text = f"색상: {style_info.get('primary_colors', '')}"
        mood_text = f"분위기: {style_info.get('mood', '')}"
        comp_text = f"구도: {style_info.get('composition', '')}"

        for text in [color_text, mood_text, comp_text]:
            ctk.CTkLabel(
                style_frame,
                text=f"  • {text}",
                font=get_font("small"),
                text_color="#888888"
            ).pack(anchor="w", padx=10)

        # 추천 모델
        if "recommended_models" in style_info:
            ctk.CTkLabel(
                style_frame,
                text="📥 추천 SD 모델",
                font=get_font("medium", bold=True)
            ).pack(anchor="w", padx=10, pady=(15, 5))

            for model in style_info["recommended_models"]:
                model_frame = ctk.CTkFrame(style_frame, fg_color="transparent")
                model_frame.pack(fill="x", padx=10, pady=2)

                ctk.CTkLabel(
                    model_frame,
                    text=f"  • {model.get('name', 'Unknown')}",
                    font=get_font("small")
                ).pack(side="left")

                if model.get("civitai_id"):
                    ctk.CTkButton(
                        model_frame,
                        text="Civitai",
                        width=60,
                        height=24,
                        font=get_font("small"),
                        fg_color="#FF6B6B",
                        hover_color="#EE5A5A",
                        command=lambda mid=model["civitai_id"]: webbrowser.open(f"https://civitai.com/models/{mid}")
                    ).pack(side="right")

        # 목소리 가이드 탭 - TTS 가이드
        self.voice_text.delete("1.0", "end")
        self.voice_text.insert("1.0", pack.tts_guide)

        # 토픽 탭
        self.topics_text.delete("1.0", "end")
        topics_content = f"""💡 생성된 토픽 ({len(pack.topics)}개)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        for i, topic in enumerate(pack.topics[:10], 1):
            topics_content += f"""[{i}] {topic.topic}
    제목: {topic.title_template}
    줄거리: {topic.outline[:100]}...
    분위기: {topic.mood} | {topic.estimated_duration}초
    키워드: {', '.join(topic.keywords)}

"""
        if len(pack.topics) > 10:
            topics_content += f"\n... 외 {len(pack.topics) - 10}개 더 있음 (JSON 저장으로 전체 확인)"

        self.topics_text.insert("1.0", topics_content)

    def _design_thread(self, config: dict):
        """설계 스레드"""
        try:
            design = self.designer.design_channel_pack(manual_config=config)
            self.parent.after(0, lambda: self._on_design_complete(design))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.parent.after(0, lambda: self._on_design_error(str(e)))

    def _on_design_complete(self, design):
        """설계 완료 콜백"""
        self.is_designing = False
        self.design_btn.configure(state="normal")
        self.progress_label.configure(text="✅ 설계 완료!")

        self.current_design = design

        # 버튼 활성화
        self.export_btn.configure(state="normal")
        self.json_btn.configure(state="normal")

        # 결과 표시
        self._display_design(design)

    def _on_design_error(self, error_msg: str):
        """설계 오류 콜백"""
        self.is_designing = False
        self.design_btn.configure(state="normal")
        self.progress_label.configure(text="❌ 설계 실패")

        messagebox.showerror("설계 오류", f"팩 설계 중 오류가 발생했습니다.\n\n{error_msg}")

    def _display_design(self, design):
        """설계 결과 표시"""
        # 요약 탭
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", format_design_summary(design))

        # SD 모델 탭
        for widget in self.models_scroll.winfo_children():
            widget.destroy()

        for i, model in enumerate(design.sd_models):
            model_frame = ctk.CTkFrame(self.models_scroll)
            model_frame.pack(fill="x", pady=5, padx=5)

            # 모델 정보
            info_frame = ctk.CTkFrame(model_frame, fg_color="transparent")
            info_frame.pack(fill="x", padx=10, pady=10)

            ctk.CTkLabel(
                info_frame,
                text=f"{'🎨' if model.model_type == 'checkpoint' else '🔧'} {model.model_name}",
                font=get_font("medium", bold=True)
            ).pack(anchor="w")

            ctk.CTkLabel(
                info_frame,
                text=f"타입: {model.model_type} | {model.match_reason}",
                font=get_font("small"),
                text_color="#888888"
            ).pack(anchor="w")

            if model.style_tags:
                ctk.CTkLabel(
                    info_frame,
                    text=f"스타일: {', '.join(model.style_tags)}",
                    font=get_font("small"),
                    text_color="#666666"
                ).pack(anchor="w")

            # Civitai 링크 버튼
            ctk.CTkButton(
                info_frame,
                text="🔗 Civitai에서 보기",
                width=130,
                height=28,
                font=get_font("small"),
                fg_color="#FF6B6B",
                hover_color="#EE5A5A",
                command=lambda url=model.civitai_url: webbrowser.open(url)
            ).pack(anchor="w", pady=(5, 0))

        # 목소리 가이드 탭
        self.voice_text.delete("1.0", "end")
        if design.voice_guide:
            vg = design.voice_guide
            voice_content = f"""🎙️ 목소리 가이드

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

기본 설정:
  • 성별: {vg.voice_gender}
  • 연령대: {vg.voice_age}
  • 톤: {vg.voice_tone}

참조 스타일:
  {vg.reference_style}

ElevenLabs 힌트:
  {vg.elevenlabs_hints}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

필요 감정: {', '.join(vg.required_emotions)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

감정별 샘플 스크립트:
"""
            for emotion, script in vg.sample_scripts.items():
                voice_content += f"\n  [{emotion}]\n  \"{script}\"\n"

            voice_content += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

녹음 팁:
"""
            for tip in vg.recording_tips:
                voice_content += f"  • {tip}\n"

            self.voice_text.insert("1.0", voice_content)

        # 토픽 탭
        self.topics_text.delete("1.0", "end")
        topics_content = f"""💡 토픽 제안

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

카테고리:
"""
        for cat in design.topic_categories:
            topics_content += f"  • {cat}\n"

        topics_content += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

샘플 토픽:
"""
        for topic in design.sample_topics:
            topics_content += f"  • {topic}\n"

        if design.banned_keywords:
            topics_content += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ 금지 키워드:
"""
            for kw in design.banned_keywords:
                topics_content += f"  • {kw}\n"

        self.topics_text.insert("1.0", topics_content)

    # ============================================================
    # Insight/Revpack 연동
    # ============================================================

    def _load_from_insight(self):
        """Insight 분석 결과에서 불러오기"""
        try:
            from insight.style_analyzer import get_style_analyzer

            # 최근 분석 결과 확인
            analyzer = get_style_analyzer()

            messagebox.showinfo(
                "Insight 연동",
                "Insight 탭에서 분석을 완료한 후\n"
                "결과에서 'Factory로 보내기' 버튼을 사용하세요."
            )

        except ImportError:
            messagebox.showwarning(
                "모듈 없음",
                "Insight 모듈을 사용할 수 없습니다."
            )

    def _load_from_revpack(self):
        """.revpack 파일에서 설정 불러오기"""
        filepath = filedialog.askopenfilename(
            title=".revpack 파일 선택",
            filetypes=[("Revpack Files", "*.revpack"), ("All Files", "*.*")]
        )

        if not filepath:
            return

        try:
            from insight.revpack_generator import get_revpack_generator

            generator = get_revpack_generator()
            success, msg, data = generator.load_revpack(Path(filepath))

            if not success:
                messagebox.showerror("로드 실패", msg)
                return

            # 설정 적용
            pkg_info = data.get("package_info", {})
            style_guide = data.get("style_guide", {})

            if pkg_info.get("channel_type"):
                self.genre_var.set(pkg_info["channel_type"])

            if style_guide.get("style_type"):
                self.style_var.set(style_guide["style_type"])

            if pkg_info.get("channel_display_name"):
                self.channel_entry.delete(0, "end")
                self.channel_entry.insert(0, pkg_info["channel_display_name"])

            messagebox.showinfo("로드 완료", f".revpack에서 설정을 불러왔습니다.\n\n{msg}")

        except ImportError:
            messagebox.showwarning("모듈 없음", "revpack_generator 모듈을 사용할 수 없습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"파일 로드 중 오류: {e}")

    # ============================================================
    # 내보내기
    # ============================================================

    def _check_license_for_export(self) -> tuple:
        """
        라이센스 검증 (내보내기용)

        Returns:
            (can_export, can_encrypt, license_type, message, owned_packs)
        """
        try:
            from utils.firebase_license import HybridLicenseValidator, CloudFunctionsClient

            validator = HybridLicenseValidator()
            is_valid, license_info = validator.validate()

            if not is_valid:
                return (False, False, None, "유효한 라이센스가 없습니다.", [])

            license_type = license_info.get("license_type", "T")
            license_key = license_info.get("license_key", "")

            # 라이센스 타입별 권한
            # A: Admin - 모든 기능
            # H: Heavy - 암호화 가능
            # M: Mid - 기본 내보내기만
            # T: Trial - 기본 내보내기만
            can_encrypt = license_type in ("A", "H")

            # Firebase에서 보유 팩 목록 조회
            owned_packs = []
            try:
                cf_client = CloudFunctionsClient()
                if cf_client.is_available and license_key:
                    success, msg, packs = cf_client.get_owned_packs(license_key)
                    if success:
                        owned_packs = packs
            except Exception:
                pass  # 팩 목록 조회 실패해도 계속 진행

            return (True, can_encrypt, license_type, "라이센스 확인됨", owned_packs)

        except ImportError:
            # 라이센스 모듈 없으면 기본 내보내기만 허용
            return (True, False, "DEMO", "라이센스 모듈 없음 (데모 모드)", [])
        except Exception as e:
            return (False, False, None, f"라이센스 확인 오류: {e}", [])

    def _export_revpack(self):
        """설계 결과를 .revpack으로 내보내기 (라이센스 검증 포함)"""
        # 클론 팩이 있으면 클론 팩 내보내기
        if self.current_clone_pack:
            self._export_clone_pack()
            return

        if not self.current_design:
            return

        # 라이센스 검증 (owned_packs 포함)
        can_export, can_encrypt, license_type, lic_msg, owned_packs = self._check_license_for_export()

        if not can_export:
            messagebox.showerror(
                "라이센스 필요",
                f"팩 내보내기를 위해 유효한 라이센스가 필요합니다.\n\n{lic_msg}"
            )
            return

        try:
            from insight.revpack_generator import get_revpack_generator
            from insight.style_analyzer import CloneRecipe

            # 암호화 여부 확인
            encrypt = False
            if can_encrypt:
                encrypt = messagebox.askyesno(
                    "패키지 암호화",
                    "패키지를 암호화하시겠습니까?\n\n"
                    "암호화하면 Studio에서만 열 수 있습니다.\n"
                    "유료 배포용이면 '예'를 선택하세요."
                )
            else:
                # 암호화 권한 없음 알림
                if license_type not in ("A", "H"):
                    messagebox.showinfo(
                        "암호화 불가",
                        f"현재 라이센스 타입({license_type})으로는 암호화가 불가능합니다.\n\n"
                        "일반(비암호화) 팩으로 내보냅니다."
                    )

            # Design → CloneRecipe 변환
            design = self.current_design

            recipe = CloneRecipe(
                video_id=design.source_insight_id or f"factory_{design.design_id}",
                channel_id="factory",
                title=design.channel_name_kr,
                url="",
                analyzed_at=datetime.now().isoformat(),
                style_type=design.visual_style,
                color_palette={"hex_colors": design.color_palette},
                lighting_style="dramatic" if design.genre == "horror" else "natural",
                composition_type="cinematic",
                sd_models=[
                    {
                        "name": m.model_name,
                        "type": m.model_type,
                        "civitai_url": m.civitai_url,
                    }
                    for m in design.sd_models
                ],
                sd_prompts={
                    "positive": design.prompt_template.positive_base if design.prompt_template else "",
                    "negative": design.prompt_template.negative_base if design.prompt_template else "",
                },
                tts_guide={
                    "gender": design.voice_guide.voice_gender if design.voice_guide else "neutral",
                    "age": design.voice_guide.voice_age if design.voice_guide else "adult",
                    "tone": design.voice_guide.voice_tone if design.voice_guide else "calm",
                    "reference": design.voice_guide.reference_style if design.voice_guide else "",
                    "emotions": design.voice_guide.required_emotions if design.voice_guide else [],
                },
                channel_type=design.genre,
                confidence_score=0.9,
                metadata={
                    "factory_design_id": design.design_id,
                    "channel_name": design.channel_name,
                    "channel_name_kr": design.channel_name_kr,
                    "concept_summary": design.concept_summary,
                    "target_audience": design.target_audience,
                    "usp": design.unique_selling_point,
                    "topics": design.sample_topics,
                    "license_type": license_type,  # 생성 시 라이센스 기록
                    "owned_packs": owned_packs,  # Firebase 보유 팩 목록
                    "created_by": "Factory",
                }
            )

            # .revpack 생성
            generator = get_revpack_generator()

            # 출력 디렉토리 선택
            output_dir = filedialog.askdirectory(title=".revpack 저장 위치 선택")
            if not output_dir:
                return

            success, msg, pack_path = generator.generate_single(
                recipe=recipe,
                output_dir=Path(output_dir),
                author="Reverie Factory",
                encrypt=encrypt,
                require_license=encrypt,  # 암호화 시 라이센스 필요
            )

            if success:
                enc_status = "🔒 암호화됨" if encrypt else "🔓 일반"
                response = messagebox.askyesno(
                    "내보내기 완료",
                    f".revpack 파일이 생성되었습니다.\n\n"
                    f"상태: {enc_status}\n"
                    f"위치: {pack_path}\n\n"
                    f"폴더를 여시겠습니까?"
                )
                if response:
                    import subprocess
                    subprocess.Popen(['explorer', output_dir])
            else:
                messagebox.showerror("내보내기 실패", msg)

        except ImportError as e:
            messagebox.showwarning("모듈 없음", f"필요한 모듈을 불러올 수 없습니다.\n\n{e}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("오류", f".revpack 내보내기 중 오류: {e}")

    def _export_clone_pack(self):
        """클론 팩을 폴더 구조로 내보내기"""
        if not self.current_clone_pack:
            return

        try:
            # 출력 디렉토리 선택
            output_dir = filedialog.askdirectory(title="클론 팩 저장 위치 선택")
            if not output_dir:
                return

            pack = self.current_clone_pack

            # 팩 이름으로 하위 폴더 생성
            pack_folder = os.path.join(output_dir, pack.pack_id)

            # 내보내기 실행
            files_created = self.clone_generator.export_to_revpack_structure(
                pack=pack,
                output_dir=pack_folder
            )

            # 결과 표시
            files_list = "\n".join([f"  • {k}: {os.path.basename(v)}" for k, v in files_created.items()])
            response = messagebox.askyesno(
                "클론 팩 내보내기 완료",
                f"클론 팩이 생성되었습니다!\n\n"
                f"📂 위치: {pack_folder}\n\n"
                f"생성된 파일:\n{files_list}\n\n"
                f"폴더를 여시겠습니까?"
            )
            if response:
                import subprocess
                subprocess.Popen(['explorer', pack_folder])

        except Exception as e:
            import traceback
            traceback.print_exc()
            messagebox.showerror("오류", f"클론 팩 내보내기 중 오류: {e}")

    def _save_json(self):
        """설계 결과 JSON 저장"""
        # 클론 팩이 있으면 클론 팩 저장
        if self.current_clone_pack:
            self._save_clone_pack_json()
            return

        if not self.current_design:
            return

        filepath = filedialog.asksaveasfilename(
            title="설계 결과 저장",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            initialfile=f"{self.current_design.design_id}.json"
        )

        if not filepath:
            return

        try:
            from dataclasses import asdict

            design = self.current_design
            data = {
                "design_id": design.design_id,
                "channel_name": design.channel_name,
                "channel_name_kr": design.channel_name_kr,
                "genre": design.genre,
                "theme": design.theme,
                "theme_kr": design.theme_kr,
                "concept_summary": design.concept_summary,
                "target_audience": design.target_audience,
                "unique_selling_point": design.unique_selling_point,
                "visual_style": design.visual_style,
                "color_palette": design.color_palette,
                "sd_models": [asdict(m) for m in design.sd_models],
                "prompt_template": asdict(design.prompt_template) if design.prompt_template else None,
                "voice_guide": asdict(design.voice_guide) if design.voice_guide else None,
                "topic_categories": design.topic_categories,
                "sample_topics": design.sample_topics,
                "banned_keywords": design.banned_keywords,
                "created_at": design.created_at,
                "source_insight_id": design.source_insight_id,
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("저장 완료", f"설계 결과가 저장되었습니다.\n\n{filepath}")

        except Exception as e:
            messagebox.showerror("저장 오류", f"저장 중 오류: {e}")

    def _save_clone_pack_json(self):
        """클론 팩 JSON 저장"""
        if not self.current_clone_pack:
            return

        pack = self.current_clone_pack
        filepath = filedialog.asksaveasfilename(
            title="클론 팩 JSON 저장",
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            initialfile=f"{pack.pack_id}.json"
        )

        if not filepath:
            return

        try:
            from dataclasses import asdict

            data = {
                "pack_id": pack.pack_id,
                "source_channel": pack.source_channel,
                "source_channel_id": pack.source_channel_id,
                "created_at": pack.created_at,
                "pd_system_prompt": pack.pd_system_prompt,
                "writer_system_prompt": pack.writer_system_prompt,
                "topics": [asdict(t) for t in pack.topics],
                "sd_prompts": pack.sd_prompts,
                "style_guide": pack.style_guide,
                "emotions": pack.emotions,
                "tts_guide": pack.tts_guide,
                "channel_config": pack.channel_config,
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            messagebox.showinfo("저장 완료", f"클론 팩이 저장되었습니다.\n\n{filepath}")

        except Exception as e:
            messagebox.showerror("저장 오류", f"저장 중 오류: {e}")

    # ============================================================
    # 외부 연동
    # ============================================================

    def load_from_clone_recipe(self, recipe_data: dict):
        """CloneRecipe 데이터로 설정 불러오기 (Insight에서 호출)"""
        try:
            # 장르 설정
            if recipe_data.get("channel_type"):
                self.genre_var.set(recipe_data["channel_type"])

            # 스타일 설정
            if recipe_data.get("style_type"):
                self.style_var.set(recipe_data["style_type"])

            # 테마 설정 (메타데이터에서)
            if recipe_data.get("metadata", {}).get("theme"):
                self.theme_entry.delete(0, "end")
                self.theme_entry.insert(0, recipe_data["metadata"]["theme"])

            messagebox.showinfo(
                "불러오기 완료",
                "Insight 분석 결과를 불러왔습니다.\n\n"
                "'팩 설계 시작' 버튼을 눌러 설계를 진행하세요."
            )

        except Exception as e:
            messagebox.showerror("오류", f"데이터 로드 중 오류: {e}")

    def load_from_channel_analysis(self, analysis_data: dict):
        """채널 분석 데이터로 설정 불러오기 (Insight 채널 분석기에서 호출)"""
        try:
            # 장르 설정
            if analysis_data.get("channel_type"):
                self.genre_var.set(analysis_data["channel_type"])

            # 스타일 설정
            if analysis_data.get("style_type"):
                self.style_var.set(analysis_data["style_type"])

            # 테마 설정 (채널 이름)
            if analysis_data.get("channel_title"):
                self.theme_entry.delete(0, "end")
                theme = f"{analysis_data['channel_title']} 스타일"
                self.theme_entry.insert(0, theme[:50])

            # 채널 분석 데이터 저장 (설계 시 활용)
            self.channel_analysis_data = analysis_data

            # 정보 표시
            metadata = analysis_data.get("metadata", {})
            formula = analysis_data.get("content_formula", {})

            info_text = f"""채널 분석 데이터를 불러왔습니다.

📺 채널: {analysis_data.get('channel_title', '알 수 없음')}
👥 구독자: {metadata.get('subscriber_count', 0):,}명
👀 평균 조회수: {metadata.get('avg_views', 0):,.0f}
📅 업로드 빈도: 주 {metadata.get('upload_frequency', 0):.1f}회

🎯 제목 키워드: {', '.join(formula.get('title_keywords', [])[:5])}
⏰ 최적 업로드: {formula.get('best_upload_day', '')}요일 {formula.get('best_upload_hour', 12)}시

'팩 설계 시작'을 눌러 이 채널 스타일의 팩을 생성하세요."""

            messagebox.showinfo("채널 분석 불러오기", info_text)

        except Exception as e:
            messagebox.showerror("오류", f"채널 분석 데이터 로드 중 오류: {e}")


# ============================================================
# 테스트
# ============================================================

def main():
    """독립 실행 테스트"""
    root = ctk.CTk()
    root.title("Factory Tab Test")
    root.geometry("900x700")

    tab = FactoryTab(root)
    tab.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
