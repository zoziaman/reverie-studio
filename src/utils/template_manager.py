# src/utils/template_manager.py
"""
템플릿 관리자
- 자주 쓰는 설정 조합 저장/불러오기
- 프리셋 관리

v57.6.8: Thread Safety 추가 (_lock)
"""
import os
import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class TemplateManager:
    """제작 템플릿 관리 (Thread Safe)"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.templates_path = os.path.join(data_dir, "templates.json")
        self._lock = threading.Lock()  # v57.6.8: Thread Safety
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[str, Any]:
        """템플릿 로드"""
        if os.path.exists(self.templates_path):
            try:
                with open(self.templates_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError, OSError) as e:
                logger.warning(f"템플릿 JSON 로드 실패: {e}")
        return {"templates": [], "default_template": None}

    def _save_templates(self):
        """템플릿 저장"""
        os.makedirs(os.path.dirname(self.templates_path), exist_ok=True)
        with open(self.templates_path, "w", encoding="utf-8") as f:
            json.dump(self.templates, f, ensure_ascii=False, indent=2)

    def save_template(self,
                      name: str,
                      channel: str,
                      mode: str,
                      quantity: int = 1,
                      topic_mode: str = "auto",
                      manual_topic: str = "",
                      auto_upload: bool = False,
                      voice_emotions: Dict[str, str] = None,
                      description: str = "") -> bool:
        """
        템플릿 저장

        Args:
            name: 템플릿 이름
            channel: 채널
            mode: 모드
            quantity: 기본 수량
            topic_mode: 주제 모드
            manual_topic: 수동 주제
            auto_upload: 자동 업로드 여부
            voice_emotions: 역할별 감정 설정
            description: 설명

        Returns:
            bool: 성공 여부
        """
        # v57.6.8: Thread Safety
        with self._lock:
            # 중복 이름 확인
            for i, t in enumerate(self.templates["templates"]):
                if t["name"] == name:
                    # 덮어쓰기
                    self.templates["templates"][i] = {
                        "name": name,
                        "channel": channel,
                        "mode": mode,
                        "quantity": quantity,
                        "topic_mode": topic_mode,
                        "manual_topic": manual_topic,
                        "auto_upload": auto_upload,
                        "voice_emotions": voice_emotions or {},
                        "description": description,
                        "created_at": t.get("created_at", datetime.now().isoformat()),
                        "updated_at": datetime.now().isoformat()
                    }
                    self._save_templates()
                    return True

            # 새로 추가
            template = {
                "name": name,
                "channel": channel,
                "mode": mode,
                "quantity": quantity,
                "topic_mode": topic_mode,
                "manual_topic": manual_topic,
                "auto_upload": auto_upload,
                "voice_emotions": voice_emotions or {},
                "description": description,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

            self.templates["templates"].append(template)
            self._save_templates()
            return True

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        """템플릿 조회"""
        for t in self.templates["templates"]:
            if t["name"] == name:
                return t
        return None

    def get_all_templates(self) -> List[Dict[str, Any]]:
        """모든 템플릿 목록"""
        return self.templates["templates"]

    def get_template_names(self) -> List[str]:
        """템플릿 이름 목록"""
        return [t["name"] for t in self.templates["templates"]]

    def delete_template(self, name: str) -> bool:
        """템플릿 삭제"""
        with self._lock:  # v57.6.8: Thread Safety
            for i, t in enumerate(self.templates["templates"]):
                if t["name"] == name:
                    self.templates["templates"].pop(i)

                    # 기본 템플릿이었다면 해제
                    if self.templates["default_template"] == name:
                        self.templates["default_template"] = None

                    self._save_templates()
                    return True
        return False

    def set_default_template(self, name: str) -> bool:
        """기본 템플릿 설정"""
        with self._lock:  # v57.6.8: Thread Safety
            if self.get_template(name):
                self.templates["default_template"] = name
                self._save_templates()
                return True
        return False

    def get_default_template(self) -> Optional[Dict[str, Any]]:
        """기본 템플릿 조회"""
        if self.templates["default_template"]:
            return self.get_template(self.templates["default_template"])
        return None

    def rename_template(self, old_name: str, new_name: str) -> bool:
        """템플릿 이름 변경"""
        # 새 이름 중복 확인
        if self.get_template(new_name):
            return False

        for t in self.templates["templates"]:
            if t["name"] == old_name:
                t["name"] = new_name
                t["updated_at"] = datetime.now().isoformat()

                # 기본 템플릿 업데이트
                if self.templates["default_template"] == old_name:
                    self.templates["default_template"] = new_name

                self._save_templates()
                return True
        return False

    def duplicate_template(self, name: str, new_name: str = None) -> Optional[str]:
        """템플릿 복제"""
        template = self.get_template(name)
        if not template:
            return None

        # 새 이름 생성
        if not new_name:
            new_name = f"{name} (복사본)"
            i = 2
            while self.get_template(new_name):
                new_name = f"{name} (복사본 {i})"
                i += 1

        # 복제
        self.save_template(
            name=new_name,
            channel=template["channel"],
            mode=template["mode"],
            quantity=template.get("quantity", 1),
            topic_mode=template.get("topic_mode", "auto"),
            manual_topic=template.get("manual_topic", ""),
            auto_upload=template.get("auto_upload", False),
            voice_emotions=template.get("voice_emotions", {}),
            description=template.get("description", "")
        )

        return new_name
