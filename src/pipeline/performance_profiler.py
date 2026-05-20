import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_value(item) for item in value]
    return str(value)


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[<>:\"/\\\\|?*]+", "_", name or "")
    cleaned = cleaned.strip().rstrip(".")
    return cleaned or "unknown_project"


def _iso_timestamp(epoch_sec: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch_sec))


@dataclass
class StageProfile:
    key: str
    label: str
    status: str = "pending"
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    elapsed_sec: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def merge_metadata(self, metadata: Optional[Dict[str, Any]]) -> None:
        if metadata:
            self.metadata.update(_sanitize_value(metadata))

    def mark_started(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.status = "in_progress"
        self.started_at = time.time()
        self.ended_at = None
        self.elapsed_sec = None
        self.merge_metadata(metadata)

    def mark_completed(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        if self.started_at is None:
            self.started_at = time.time()
        self.ended_at = time.time()
        self.elapsed_sec = round(self.ended_at - self.started_at, 2)
        self.status = "completed"
        self.merge_metadata(metadata)

    def mark_skipped(self, reason: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        self.started_at = self.started_at or now
        self.ended_at = now
        self.elapsed_sec = round(max(0.0, self.ended_at - self.started_at), 2)
        self.status = "skipped"
        merged = {"reason": reason}
        if metadata:
            merged.update(metadata)
        self.merge_metadata(merged)

    def mark_failed(self, error: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        if self.started_at is None:
            self.started_at = time.time()
        self.ended_at = time.time()
        self.elapsed_sec = round(self.ended_at - self.started_at, 2)
        self.status = "failed"
        merged = {"error": error}
        if metadata:
            merged.update(metadata)
        self.merge_metadata(merged)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "started_at": _iso_timestamp(self.started_at) if self.started_at else None,
            "ended_at": _iso_timestamp(self.ended_at) if self.ended_at else None,
            "elapsed_sec": self.elapsed_sec,
            "metadata": _sanitize_value(self.metadata),
        }


class ProductionPerformanceProfiler:
    def __init__(
        self,
        project_name: str,
        data_dir: str,
        logger: Any = None,
    ) -> None:
        self.project_name = project_name
        self._logger = logger
        self._started_at = time.time()
        self._stages: Dict[str, StageProfile] = {}
        self._overview: Dict[str, Any] = {}
        self._status = "in_progress"
        self._current_stage: Optional[str] = None
        report_dir = os.path.join(data_dir, "outputs", "reports", "performance")
        os.makedirs(report_dir, exist_ok=True)
        safe_name = _sanitize_name(project_name)
        self.json_path = os.path.join(report_dir, f"{safe_name}.json")
        self.md_path = os.path.join(report_dir, f"{safe_name}.md")

    @property
    def current_stage(self) -> Optional[str]:
        return self._current_stage

    def update_overview(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if value is not None:
                self._overview[key] = _sanitize_value(value)
        self.write()

    def start_stage(self, key: str, label: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        stage = self._stages.get(key)
        if stage is None:
            stage = StageProfile(key=key, label=label)
            self._stages[key] = stage
        stage.label = label
        stage.mark_started(metadata)
        self._current_stage = key
        self._status = "in_progress"
        self.write()

    def complete_stage(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        stage = self._require_stage(key)
        stage.mark_completed(metadata)
        if self._current_stage == key:
            self._current_stage = None
        self.write()

    def skip_stage(
        self,
        key: str,
        label: str,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        stage = self._stages.get(key)
        if stage is None:
            stage = StageProfile(key=key, label=label)
            self._stages[key] = stage
        stage.label = label
        stage.mark_skipped(reason, metadata)
        self.write()

    def fail_stage(self, key: str, error: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        stage = self._require_stage(key)
        stage.mark_failed(error, metadata)
        self._status = "failed"
        if self._current_stage == key:
            self._current_stage = None
        self.write()

    def finalize(self, status: str = "completed", metadata: Optional[Dict[str, Any]] = None) -> None:
        self._status = status
        self._current_stage = None
        if metadata:
            self.update_overview(**metadata)
        self.write()

    def stage_elapsed(self, key: str) -> Optional[float]:
        stage = self._stages.get(key)
        return stage.elapsed_sec if stage else None

    def write(self) -> None:
        payload = self._build_payload()
        with open(self.json_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        with open(self.md_path, "w", encoding="utf-8") as handle:
            handle.write(self._build_markdown(payload))

    def _require_stage(self, key: str) -> StageProfile:
        stage = self._stages.get(key)
        if stage is None:
            raise KeyError(f"unknown stage: {key}")
        return stage

    def _build_payload(self) -> Dict[str, Any]:
        now = time.time()
        total_elapsed = round(now - self._started_at, 2)
        derived = self._build_derived_metrics()
        return {
            "project_name": self.project_name,
            "status": self._status,
            "current_stage": self._current_stage,
            "started_at": _iso_timestamp(self._started_at),
            "updated_at": _iso_timestamp(now),
            "total_elapsed_sec": total_elapsed,
            "overview": _sanitize_value(self._overview),
            "derived_metrics": derived,
            "stages": [stage.to_dict() for stage in self._stages.values()],
        }

    def _build_derived_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        subtitle_count = self._overview.get("subtitle_count")
        image_count = self._overview.get("image_count")
        script_turns = self._overview.get("script_turns")
        tts_elapsed = self.stage_elapsed("tts")
        image_elapsed = self.stage_elapsed("images")
        if subtitle_count and tts_elapsed and tts_elapsed > 0:
            metrics["tts_turns_per_min"] = round((float(subtitle_count) / tts_elapsed) * 60.0, 2)
        if image_count and image_elapsed and image_elapsed > 0:
            metrics["images_per_min"] = round((float(image_count) / image_elapsed) * 60.0, 2)
        if script_turns and image_count:
            metrics["image_to_script_ratio"] = round(float(image_count) / float(script_turns), 3)
        return metrics

    def _build_markdown(self, payload: Dict[str, Any]) -> str:
        lines = [
            f"# Production Performance Report: {payload['project_name']}",
            "",
            f"- status: {payload['status']}",
            f"- current_stage: {payload['current_stage'] or '-'}",
            f"- started_at: {payload['started_at']}",
            f"- updated_at: {payload['updated_at']}",
            f"- total_elapsed_sec: {payload['total_elapsed_sec']}",
            "",
            "## Overview",
        ]
        overview = payload.get("overview", {})
        if overview:
            for key, value in overview.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- no overview data")
        metrics = payload.get("derived_metrics", {})
        lines.extend(["", "## Derived Metrics"])
        if metrics:
            for key, value in metrics.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- no derived metrics")
        lines.extend(["", "## Stages"])
        for stage in payload.get("stages", []):
            lines.append(
                f"- {stage['label']} ({stage['key']}): {stage['status']}, elapsed={stage['elapsed_sec']}"
            )
            if stage["metadata"]:
                for key, value in stage["metadata"].items():
                    lines.append(f"  - {key}: {value}")
        lines.append("")
        return "\n".join(lines)
