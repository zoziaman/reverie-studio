# src/gui/training_wizard.py
"""
v35 - SoVITS 학습 마법사 GUI

학습 과정을 단계별로 안내하는 마법사 형식 UI
- Step 1: 기본 정보 입력
- Step 2: 음성 파일 선택 및 검증
- Step 3: 학습 설정 (프리셋 / 고급)
- Step 4: 학습 진행 및 모니터링
"""

import os
import sys
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

# 백엔드
try:
    from utils.sovits_trainer import (
        SoVITSTrainer, TrainingConfig, TrainingProgress, TrainingStage, get_trainer
    )
except ImportError:
    SoVITSTrainer = None

try:
    from utils.model_manager import get_model_manager
except Exception:
    get_model_manager = None


class TrainingWizard(ctk.CTkToplevel):
    """SoVITS 학습 마법사 다이얼로그"""

    WINDOW_WIDTH = 700
    WINDOW_HEIGHT = 600

    def __init__(self, parent, on_complete: Optional[Callable] = None):
        super().__init__(parent)

        self.title("음성 모델 학습 마법사")
        self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")
        self.resizable(False, False)

        # 콜백
        self.on_complete = on_complete

        # 상태
        self.current_step = 1
        self.total_steps = 4
        self.config = TrainingConfig()
        self.trainer: Optional[SoVITSTrainer] = None
        self.audio_info: Optional[dict] = None

        # UI 구성
        self._create_widgets()
        self._show_step(1)

        # 모달
        self.transient(parent)
        self.grab_set()

        # 중앙 정렬
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self.WINDOW_WIDTH) // 2
        y = (self.winfo_screenheight() - self.WINDOW_HEIGHT) // 2
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        """위젯 생성"""
        # 헤더
        self.header_frame = ctk.CTkFrame(self, height=80)
        self.header_frame.pack(fill="x", padx=20, pady=(20, 10))
        self.header_frame.pack_propagate(False)

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="음성 모델 학습 마법사",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.title_label.pack(pady=(15, 5))

        self.step_label = ctk.CTkLabel(
            self.header_frame,
            text="Step 1/4: 기본 정보",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        self.step_label.pack()

        # 진행 바
        self.progress_bar = ctk.CTkProgressBar(self, width=660, height=8)
        self.progress_bar.pack(padx=20, pady=(0, 10))
        self.progress_bar.set(0.25)

        # 콘텐츠 영역
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # 버튼 영역
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent", height=60)
        self.button_frame.pack(fill="x", padx=20, pady=(10, 20))
        self.button_frame.pack_propagate(False)

        self.back_btn = ctk.CTkButton(
            self.button_frame, text="이전", width=100,
            command=self._on_back
        )
        self.back_btn.pack(side="left")

        self.next_btn = ctk.CTkButton(
            self.button_frame, text="다음", width=100,
            command=self._on_next
        )
        self.next_btn.pack(side="right")

        self.cancel_btn = ctk.CTkButton(
            self.button_frame, text="취소", width=100,
            fg_color="gray", hover_color="darkgray",
            command=self._on_cancel
        )
        self.cancel_btn.pack(side="right", padx=(0, 10))

    def _clear_content(self):
        """콘텐츠 영역 초기화"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _show_step(self, step: int):
        """단계별 화면 표시"""
        self.current_step = step
        self._clear_content()

        # 진행 바 업데이트
        self.progress_bar.set(step / self.total_steps)

        # 버튼 상태
        self.back_btn.configure(state="normal" if step > 1 else "disabled")

        if step == 1:
            self.step_label.configure(text="Step 1/4: 기본 정보")
            self.next_btn.configure(text="다음", state="normal")
            self._create_step1()
        elif step == 2:
            self.step_label.configure(text="Step 2/4: 음성 파일")
            self.next_btn.configure(text="다음", state="normal")
            self._create_step2()
        elif step == 3:
            self.step_label.configure(text="Step 3/4: 학습 설정")
            self.next_btn.configure(text="학습 시작", state="normal")
            self._create_step3()
        elif step == 4:
            self.step_label.configure(text="Step 4/4: 학습 진행")
            self.next_btn.configure(text="완료", state="disabled")
            self.back_btn.configure(state="disabled")
            self.cancel_btn.configure(text="중단")
            self._create_step4()

    # ========== Step 1: 기본 정보 ==========
    def _create_step1(self):
        """Step 1: 기본 정보 입력"""
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True, pady=20)

        # 설명
        desc = ctk.CTkLabel(
            frame,
            text="새로운 음성 모델의 기본 정보를 입력하세요.",
            font=ctk.CTkFont(size=14)
        )
        desc.pack(pady=(0, 20))

        # 모델 이름
        name_frame = ctk.CTkFrame(frame, fg_color="transparent")
        name_frame.pack(fill="x", pady=10)

        name_label = ctk.CTkLabel(name_frame, text="모델 이름 *", width=100, anchor="w")
        name_label.pack(side="left")

        self.name_entry = ctk.CTkEntry(name_frame, width=400, placeholder_text="예: 할머니_v2")
        self.name_entry.pack(side="left", padx=(10, 0))
        if self.config.model_name:
            self.name_entry.insert(0, self.config.model_name)

        # 설명
        desc_frame = ctk.CTkFrame(frame, fg_color="transparent")
        desc_frame.pack(fill="x", pady=10)

        desc_label = ctk.CTkLabel(desc_frame, text="설명", width=100, anchor="w")
        desc_label.pack(side="left")

        self.desc_entry = ctk.CTkEntry(desc_frame, width=400, placeholder_text="모델에 대한 간단한 설명")
        self.desc_entry.pack(side="left", padx=(10, 0))
        if self.config.model_description:
            self.desc_entry.insert(0, self.config.model_description)

        # 안내
        info_frame = ctk.CTkFrame(frame, fg_color="#2b2b2b", corner_radius=10)
        info_frame.pack(fill="x", pady=30, padx=20)

        info_text = """
학습 전 준비사항:

  1. 깨끗한 음성 파일 준비 (10~30분 분량 권장)
  2. 배경 음악이나 노이즈가 없는 파일
  3. 한 명의 화자만 포함된 음성
  4. WAV 또는 MP3 형식 권장
        """
        info_label = ctk.CTkLabel(
            info_frame, text=info_text.strip(),
            font=ctk.CTkFont(size=12),
            justify="left", anchor="w"
        )
        info_label.pack(padx=20, pady=15)

    # ========== Step 2: 음성 파일 ==========
    def _create_step2(self):
        """Step 2: 음성 파일 선택"""
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True, pady=20)

        # 설명
        desc = ctk.CTkLabel(
            frame,
            text="학습에 사용할 음성 파일이 있는 폴더를 선택하세요.",
            font=ctk.CTkFont(size=14)
        )
        desc.pack(pady=(0, 20))

        # 폴더 선택
        folder_frame = ctk.CTkFrame(frame, fg_color="transparent")
        folder_frame.pack(fill="x", pady=10)

        folder_label = ctk.CTkLabel(folder_frame, text="음성 폴더", width=80, anchor="w")
        folder_label.pack(side="left")

        self.folder_entry = ctk.CTkEntry(folder_frame, width=400, placeholder_text="폴더 경로를 선택하세요")
        self.folder_entry.pack(side="left", padx=(10, 10))
        if self.config.audio_folder:
            self.folder_entry.insert(0, self.config.audio_folder)

        browse_btn = ctk.CTkButton(
            folder_frame, text="찾아보기", width=80,
            command=self._browse_folder
        )
        browse_btn.pack(side="left")

        # 검증 결과 영역
        self.validation_frame = ctk.CTkFrame(frame, fg_color="#2b2b2b", corner_radius=10)
        self.validation_frame.pack(fill="both", expand=True, pady=20, padx=20)

        self.validation_label = ctk.CTkLabel(
            self.validation_frame,
            text="폴더를 선택하면 음성 파일을 자동으로 검증합니다.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.validation_label.pack(pady=50)

        # 자동 검증
        if self.config.audio_folder:
            self._validate_folder()

    def _browse_folder(self):
        """폴더 선택 다이얼로그"""
        folder = filedialog.askdirectory(title="음성 파일 폴더 선택")
        if folder:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, folder)
            self.config.audio_folder = folder
            self._validate_folder()

    def _validate_folder(self):
        """폴더 검증"""
        folder = self.folder_entry.get().strip()
        if not folder:
            return

        # 검증 중 표시
        self.validation_label.configure(text="검증 중...", text_color="white")
        self.update()

        try:
            # Trainer 인스턴스 생성
            if self.trainer is None:
                self.trainer = get_trainer()

            valid, info = self.trainer.validate_audio_folder(folder)

            # 결과 표시
            for widget in self.validation_frame.winfo_children():
                widget.destroy()

            if valid:
                self.audio_info = info

                # 성공 헤더
                header = ctk.CTkLabel(
                    self.validation_frame,
                    text=f"검증 완료: {info['file_count']}개 파일 ({info['total_duration_str']})",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color="#4CAF50"
                )
                header.pack(pady=(15, 10))

                # 파일 목록 (최대 10개만 표시, 스크롤 제거)
                files_to_show = info['files'][:10]
                file_list_text = "\n".join([f"  - {f['name']} ({f['size_mb']:.1f}MB)" for f in files_to_show])
                if len(info['files']) > 10:
                    file_list_text += f"\n  ... 외 {len(info['files'])-10}개 파일"

                file_label = ctk.CTkLabel(
                    self.validation_frame,
                    text=file_list_text,
                    font=ctk.CTkFont(size=11),
                    justify="left",
                    anchor="w"
                )
                file_label.pack(fill="x", padx=20, pady=5)

                # 경고
                if info.get('warnings'):
                    for warn in info['warnings']:
                        warn_label = ctk.CTkLabel(
                            self.validation_frame,
                            text=f"  {warn}",
                            font=ctk.CTkFont(size=11),
                            text_color="#FFA500"
                        )
                        warn_label.pack(pady=2)

            else:
                # 실패
                error_label = ctk.CTkLabel(
                    self.validation_frame,
                    text=f"검증 실패: {info.get('error', '알 수 없는 오류')}",
                    font=ctk.CTkFont(size=14),
                    text_color="#F44336"
                )
                error_label.pack(pady=50)

        except Exception as e:
            import traceback
            traceback.print_exc()  # 콘솔에 상세 에러 출력

            # 에러 메시지 표시
            for widget in self.validation_frame.winfo_children():
                widget.destroy()

            error_label = ctk.CTkLabel(
                self.validation_frame,
                text=f"오류: {str(e)}",
                font=ctk.CTkFont(size=14),
                text_color="#F44336"
            )
            error_label.pack(pady=50)

    # ========== Step 3: 학습 설정 ==========
    def _create_step3(self):
        """Step 3: 학습 설정"""
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True, pady=20)

        # 설명
        desc = ctk.CTkLabel(
            frame,
            text="학습 품질과 세부 설정을 선택하세요.",
            font=ctk.CTkFont(size=14)
        )
        desc.pack(pady=(0, 20))

        # 프리셋 선택
        preset_frame = ctk.CTkFrame(frame, fg_color="transparent")
        preset_frame.pack(fill="x", pady=10)

        preset_label = ctk.CTkLabel(preset_frame, text="학습 품질", font=ctk.CTkFont(size=13, weight="bold"))
        preset_label.pack(anchor="w")

        self.preset_var = ctk.StringVar(value="normal")

        # 8GB VRAM 최적화 프리셋
        presets = [
            ("quick", "빠른 학습", "약 40분, 보통 품질"),
            ("normal", "일반 학습 (권장)", "약 1.5시간, 좋은 품질"),
            ("high", "고품질 학습", "약 3시간, 최상 품질"),
        ]

        for value, title, desc_text in presets:
            radio_frame = ctk.CTkFrame(preset_frame, fg_color="transparent")
            radio_frame.pack(fill="x", pady=5, padx=20)

            radio = ctk.CTkRadioButton(
                radio_frame, text=title, variable=self.preset_var, value=value,
                command=self._on_preset_change
            )
            radio.pack(side="left")

            desc_lbl = ctk.CTkLabel(radio_frame, text=f"  ({desc_text})", text_color="gray")
            desc_lbl.pack(side="left")

        # 고급 설정 토글
        self.advanced_var = ctk.BooleanVar(value=False)
        advanced_check = ctk.CTkCheckBox(
            frame, text="고급 설정 표시",
            variable=self.advanced_var,
            command=self._toggle_advanced
        )
        advanced_check.pack(anchor="w", pady=(20, 10))

        # 고급 설정 프레임 (초기에는 숨김)
        self.advanced_frame = ctk.CTkFrame(frame, fg_color="#2b2b2b", corner_radius=10)

        # 고급 설정 내용
        self._create_advanced_settings()

    def _create_advanced_settings(self):
        """고급 설정 위젯 생성"""
        # GPT Epochs
        row1 = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(row1, text="GPT Epochs:", width=120, anchor="w").pack(side="left")
        self.gpt_epochs_entry = ctk.CTkEntry(row1, width=80)
        self.gpt_epochs_entry.pack(side="left")
        self.gpt_epochs_entry.insert(0, str(self.config.gpt_epochs))

        ctk.CTkLabel(row1, text="SoVITS Epochs:", width=120, anchor="w").pack(side="left", padx=(30, 0))
        self.sovits_epochs_entry = ctk.CTkEntry(row1, width=80)
        self.sovits_epochs_entry.pack(side="left")
        self.sovits_epochs_entry.insert(0, str(self.config.sovits_epochs))

        # Batch Size, Learning Rate
        row2 = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(row2, text="Batch Size:", width=120, anchor="w").pack(side="left")
        self.batch_size_entry = ctk.CTkEntry(row2, width=80)
        self.batch_size_entry.pack(side="left")
        self.batch_size_entry.insert(0, str(self.config.batch_size))

        ctk.CTkLabel(row2, text="Learning Rate:", width=120, anchor="w").pack(side="left", padx=(30, 0))
        self.lr_entry = ctk.CTkEntry(row2, width=80)
        self.lr_entry.pack(side="left")
        self.lr_entry.insert(0, str(self.config.learning_rate))

        # ASR 설정
        row3 = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(row3, text="ASR 언어:", width=120, anchor="w").pack(side="left")
        self.asr_lang_combo = ctk.CTkComboBox(row3, values=["ko", "en", "ja", "zh", "auto"], width=80)
        self.asr_lang_combo.pack(side="left")
        self.asr_lang_combo.set(self.config.asr_language)

        ctk.CTkLabel(row3, text="ASR 모델:", width=120, anchor="w").pack(side="left", padx=(30, 0))
        self.asr_size_combo = ctk.CTkComboBox(row3, values=["large-v3", "medium", "small", "base"], width=100)
        self.asr_size_combo.pack(side="left")
        self.asr_size_combo.set(self.config.asr_model_size)

    def _on_preset_change(self):
        """프리셋 변경 시 (8GB VRAM 최적화)"""
        preset = self.preset_var.get()
        # (gpt_epochs, sovits_epochs, batch_size, learning_rate)
        presets = {
            "quick": (10, 6, 2, 0.0003),
            "normal": (20, 12, 2, 0.0002),
            "high": (40, 24, 1, 0.0001),
        }
        gpt, sovits, batch, lr = presets.get(preset, (20, 12, 2, 0.0002))

        if hasattr(self, 'gpt_epochs_entry'):
            self.gpt_epochs_entry.delete(0, "end")
            self.gpt_epochs_entry.insert(0, str(gpt))
            self.sovits_epochs_entry.delete(0, "end")
            self.sovits_epochs_entry.insert(0, str(sovits))
            self.batch_size_entry.delete(0, "end")
            self.batch_size_entry.insert(0, str(batch))
            self.lr_entry.delete(0, "end")
            self.lr_entry.insert(0, str(lr))

    def _toggle_advanced(self):
        """고급 설정 토글"""
        if self.advanced_var.get():
            self.advanced_frame.pack(fill="x", pady=10, padx=20)
        else:
            self.advanced_frame.pack_forget()

    # ========== Step 4: 학습 진행 ==========
    def _create_step4(self):
        """Step 4: 학습 진행"""
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(fill="both", expand=True, pady=20)

        # 현재 단계
        self.stage_label = ctk.CTkLabel(
            frame,
            text="학습 준비 중...",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.stage_label.pack(pady=(0, 10))

        # 전체 진행률
        overall_frame = ctk.CTkFrame(frame, fg_color="transparent")
        overall_frame.pack(fill="x", pady=10, padx=20)

        ctk.CTkLabel(overall_frame, text="전체 진행률:").pack(anchor="w")
        self.overall_progress = ctk.CTkProgressBar(overall_frame, width=600, height=20)
        self.overall_progress.pack(fill="x", pady=5)
        self.overall_progress.set(0)

        self.overall_percent_label = ctk.CTkLabel(overall_frame, text="0%")
        self.overall_percent_label.pack(anchor="e")

        # 현재 단계 진행률
        stage_frame = ctk.CTkFrame(frame, fg_color="transparent")
        stage_frame.pack(fill="x", pady=10, padx=20)

        ctk.CTkLabel(stage_frame, text="현재 단계:").pack(anchor="w")
        self.stage_progress = ctk.CTkProgressBar(stage_frame, width=600, height=15)
        self.stage_progress.pack(fill="x", pady=5)
        self.stage_progress.set(0)

        # 상세 정보
        info_frame = ctk.CTkFrame(frame, fg_color="#2b2b2b", corner_radius=10)
        info_frame.pack(fill="x", pady=20, padx=20)

        self.epoch_label = ctk.CTkLabel(info_frame, text="Epoch: -")
        self.epoch_label.pack(anchor="w", padx=20, pady=5)

        self.time_label = ctk.CTkLabel(info_frame, text="경과 시간: 00:00:00 | 예상 남은 시간: --:--:--")
        self.time_label.pack(anchor="w", padx=20, pady=5)

        self.message_label = ctk.CTkLabel(info_frame, text="", text_color="gray")
        self.message_label.pack(anchor="w", padx=20, pady=5)

        # 로그 영역
        log_label = ctk.CTkLabel(frame, text="학습 로그", anchor="w")
        log_label.pack(fill="x", padx=20)

        self.log_text = ctk.CTkTextbox(frame, height=120, state="disabled")
        self.log_text.pack(fill="x", padx=20, pady=5)

        # 학습 시작
        self._start_training()

    def _start_training(self):
        """학습 시작"""
        # Config 수집
        self.config.model_name = self.name_entry.get().strip() if hasattr(self, 'name_entry') else self.config.model_name
        self.config.model_description = self.desc_entry.get().strip() if hasattr(self, 'desc_entry') else ""
        self.config.audio_folder = self.folder_entry.get().strip() if hasattr(self, 'folder_entry') else self.config.audio_folder
        self.config.quality_preset = self.preset_var.get() if hasattr(self, 'preset_var') else "normal"

        if hasattr(self, 'gpt_epochs_entry'):
            try:
                self.config.gpt_epochs = int(self.gpt_epochs_entry.get())
                self.config.sovits_epochs = int(self.sovits_epochs_entry.get())
                self.config.batch_size = int(self.batch_size_entry.get())
                self.config.learning_rate = float(self.lr_entry.get())
                self.config.asr_language = self.asr_lang_combo.get()
                self.config.asr_model_size = self.asr_size_combo.get()
            except (ValueError, KeyError) as e:
                logger.debug(f"트레이닝 설정 파싱 실패: {e}")

        # Trainer 설정
        if self.trainer is None:
            self.trainer = get_trainer()

        self.trainer.set_progress_callback(self._on_progress_update)
        self.trainer.set_log_callback(self._on_log_update)

        # 학습 시작
        success = self.trainer.start_training(self.config)
        if not success:
            messagebox.showerror("오류", "학습을 시작할 수 없습니다.")

    def _on_progress_update(self, progress: TrainingProgress):
        """진행률 업데이트 (콜백, 다른 스레드에서 호출됨)"""
        # GUI 업데이트는 메인 스레드에서
        self.after(0, lambda: self._update_progress_ui(progress))

    def _update_progress_ui(self, progress: TrainingProgress):
        """진행률 UI 업데이트"""
        # 단계 이름 매핑
        stage_names = {
            TrainingStage.IDLE: "대기 중",
            TrainingStage.VALIDATING: "음성 파일 검증",
            TrainingStage.SLICING: "음성 슬라이싱",
            TrainingStage.ASR: "음성→텍스트 변환",
            TrainingStage.TEXT_PROCESS: "텍스트 처리",
            TrainingStage.HUBERT: "오디오 피처 추출",
            TrainingStage.SEMANTIC: "시멘틱 토큰 추출",
            TrainingStage.GPT_TRAIN: "GPT 모델 학습",
            TrainingStage.SOVITS_TRAIN: "SoVITS 모델 학습",
            TrainingStage.EXTRACTING: "모델 추출",
            TrainingStage.COMPLETED: "완료!",
            TrainingStage.FAILED: "실패",
            TrainingStage.CANCELLED: "취소됨",
        }

        stage_name = stage_names.get(progress.stage, str(progress.stage.name))
        self.stage_label.configure(text=stage_name)

        # 진행률
        self.overall_progress.set(progress.overall_progress / 100)
        self.overall_percent_label.configure(text=f"{progress.overall_progress:.1f}%")
        self.stage_progress.set(progress.stage_progress / 100)

        # Epoch
        if progress.total_epochs > 0:
            self.epoch_label.configure(text=f"Epoch: {progress.current_epoch}/{progress.total_epochs}")

        # 시간
        elapsed = self._format_time(progress.elapsed_seconds)
        eta = self._format_time(progress.eta_seconds) if progress.eta_seconds > 0 else "--:--:--"
        self.time_label.configure(text=f"경과 시간: {elapsed} | 예상 남은 시간: {eta}")

        # 메시지
        self.message_label.configure(text=progress.message)

        # 완료/실패 처리
        if progress.stage == TrainingStage.COMPLETED:
            self.next_btn.configure(state="normal", text="완료")
            self.cancel_btn.configure(state="disabled")
            messagebox.showinfo("완료", "음성 모델 학습이 완료되었습니다!")

        elif progress.stage == TrainingStage.FAILED:
            self.next_btn.configure(state="normal", text="닫기")
            self.cancel_btn.configure(state="disabled")
            messagebox.showerror("실패", f"학습 실패: {progress.error}")

        elif progress.stage == TrainingStage.CANCELLED:
            self.next_btn.configure(state="normal", text="닫기")
            self.cancel_btn.configure(state="disabled")

    def _on_log_update(self, message: str):
        """로그 업데이트 (콜백)"""
        self.after(0, lambda: self._append_log(message))

    def _append_log(self, message: str):
        """로그 추가"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _format_time(self, seconds: int) -> str:
        """초 → HH:MM:SS 변환"""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    # ========== 네비게이션 ==========
    def _on_back(self):
        """이전 버튼"""
        if self.current_step > 1:
            self._show_step(self.current_step - 1)

    def _on_next(self):
        """다음 버튼"""
        if self.current_step == 1:
            # 검증
            name = self.name_entry.get().strip()
            if not name:
                messagebox.showwarning("입력 필요", "모델 이름을 입력해주세요.")
                return
            self.config.model_name = name
            self.config.model_description = self.desc_entry.get().strip()
            self._show_step(2)

        elif self.current_step == 2:
            folder = self.folder_entry.get().strip()
            if not folder or not self.audio_info:
                messagebox.showwarning("입력 필요", "음성 폴더를 선택하고 검증을 완료해주세요.")
                return
            self.config.audio_folder = folder
            self._show_step(3)

        elif self.current_step == 3:
            self._show_step(4)

        elif self.current_step == 4:
            # 완료
            self._on_complete()

    def _on_cancel(self):
        """취소/중단 버튼"""
        if self.current_step == 4 and self.trainer and self.trainer.is_running:
            if messagebox.askyesno("학습 중단", "학습을 중단하시겠습니까?"):
                self.trainer.stop_training()
        else:
            self.destroy()

    def _on_complete(self):
        """완료 처리"""
        if self.on_complete:
            self.on_complete(self.config)
        self.destroy()


# 테스트용
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.withdraw()

    def on_done(cfg):
        print(f"완료: {cfg.model_name}")

    wizard = TrainingWizard(root, on_complete=on_done)
    wizard.mainloop()
