from unittest.mock import patch
from pathlib import Path
import json

from config.settings import config
from gui.mixins.production_mixin import ProductionMixin
from modules_pro.video_models import ProductionCheckpoint
from pipeline.orchestrator import MediaFactory
from utils.batch_queue import BatchQueue


class DummyVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class DummyEntry:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value


class BrokenGetter:
    def get(self):
        raise RuntimeError("boom")


class DummyButton:
    def __init__(self):
        self.calls = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


class QueueCapture:
    def __init__(self):
        self.kwargs = None

    def add_batch(self, **kwargs):
        self.kwargs = kwargs
        return ["job-1"]

    def get_queue_summary(self):
        return {"pending": 1}


class DummyStats:
    def __init__(self):
        self.calls = []

    def record_production(self, **kwargs):
        self.calls.append(kwargs)


class DummyProductionForQueue(ProductionMixin):
    def __init__(self):
        self.channel_var = DummyVar("senior_touching")
        self.quantity_var = DummyVar(1)
        self.topic_mode_var = DummyVar("manual")
        self.manual_topic_entry = DummyEntry("테스트 주제")
        self.auto_upload_var = DummyVar(False)
        self.prompt_mode_var = DummyVar("enhanced")
        self.skip_thumbnail_popup_var = DummyVar(False)
        self.resume_from_checkpoint_var = DummyVar(True)
        self.upload_privacy_var = DummyVar("private")
        self.batch_queue = QueueCapture()
        self.logs = []

    def _add_log(self, message):
        self.logs.append(message)


class DummyProductionWorker(ProductionMixin):
    def __init__(self, resume=True, skip_thumbnail=False):
        self.resume_from_checkpoint_var = DummyVar(resume)
        self.skip_thumbnail_popup_var = DummyVar(skip_thumbnail)
        self.auto_upload_var = DummyVar(False)
        self.is_producing = True
        self.production_stats = DummyStats()
        self.start_button = DummyButton()
        self.stop_button = DummyButton()
        self.add_queue_button = DummyButton()
        self.logs = []
        self.progress = []
        self.loaded_recent_projects = False

    def _activate_pack_for_job(self, pack_id):
        self.pack_id = pack_id
        return True

    def _add_log(self, message):
        self.logs.append(message)

    def _update_progress(self, *args):
        self.progress.append(args)

    def _thumbnail_callback(self, *args, **kwargs):
        return "approve"

    def _load_recent_projects(self):
        self.loaded_recent_projects = True

    def after(self, _delay, callback):
        callback()


class DummyQueueWorkerWindow(DummyProductionWorker):
    def __init__(self, batch_queue):
        super().__init__(resume=True, skip_thumbnail=False)
        self.batch_queue = batch_queue

    def _clear_log(self):
        self.logs.clear()


def test_add_to_queue_stores_resume_flag():
    window = DummyProductionForQueue()

    with patch("gui.mixins.production_mixin.messagebox.showinfo"), patch(
        "gui.mixins.production_mixin.messagebox.showerror"
    ):
        window._add_to_queue()

    assert window.batch_queue.kwargs is not None
    assert window.batch_queue.kwargs["resume_from_checkpoint"] is True


def test_batch_queue_persists_resume_from_checkpoint(tmp_path):
    queue = BatchQueue(str(tmp_path))

    job_id = queue.add_job(
        channel="senior",
        mode="touching",
        manual_topic="테스트",
        resume_from_checkpoint=True,
    )

    job = queue.get_job(job_id)

    assert job is not None
    assert job["resume_from_checkpoint"] is True


def test_batch_queue_retry_job_preserves_plan_metadata(tmp_path):
    queue = BatchQueue(str(tmp_path))

    job_id = queue.add_job(
        channel="senior",
        mode="touching",
        manual_topic="기존 주제",
        resume_from_checkpoint=False,
    )
    queue.update_job(
        job_id,
        topic="기존 주제",
        json_path="C:/ReverieStudio/data/scripts/retry_plan.json",
        project_name="retry_plan",
    )
    queue.start_job(job_id)
    queue.fail_job(job_id, "boom")

    retry_job_id = queue.retry_job(job_id)

    retry_job = queue.get_job(retry_job_id)
    original_job = queue.get_job(job_id)

    assert retry_job_id is not None
    assert retry_job is not None
    assert retry_job["status"] == "pending"
    assert retry_job["resume_from_checkpoint"] is False
    assert retry_job["json_path"] == "C:/ReverieStudio/data/scripts/retry_plan.json"
    assert retry_job["manual_topic"] == "기존 주제"
    assert retry_job["topic_mode"] == "manual"
    assert retry_job["retry_of"] == job_id
    assert retry_job["retry_count"] == 1
    assert original_job["retry_job_id"] == retry_job_id


def test_media_factory_persists_partial_image_checkpoint_progress(tmp_path):
    checkpoint_path = tmp_path / "image_checkpoint.json"
    factory = MediaFactory.__new__(MediaFactory)
    factory.checkpoint = ProductionCheckpoint(
        project_name="image_progress_test",
        audio_path="C:/ReverieStudio/data/temp_audio/test/full.wav",
    )

    img1 = tmp_path / "scene_0001.png"
    img2 = tmp_path / "scene_0002.png"
    img1.write_bytes(b"img1")
    img2.write_bytes(b"img2")

    partial_paths = []
    subtitle_data = [{"text": "a"}, {"text": "b"}, {"text": "c"}]

    factory._persist_image_checkpoint_progress(
        str(checkpoint_path),
        partial_paths,
        subtitle_data,
        image_path=str(img1),
        total_images=10,
    )
    factory._persist_image_checkpoint_progress(
        str(checkpoint_path),
        partial_paths,
        subtitle_data,
        image_path=str(img2),
        total_images=10,
    )

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["stage"] == "images"
    assert payload["images_completed"] == 2
    assert payload["tts_completed"] == 3
    assert payload["image_paths"] == [str(img1), str(img2)]


def test_production_worker_passes_resume_flag_to_factory(monkeypatch):
    import gui.mixins.production_mixin as production_module

    class DummyScenarioPlanner:
        def __init__(self, prompt_mode="enhanced"):
            self.prompt_mode = prompt_mode

        def create_senior_plan(self, topic, mode="touching"):
            return {
                "project_name": "resume_test_project",
                "title": topic,
            }, "resume_test_project.json"

    class DummyFactory:
        instances = []

        def __init__(self, channel):
            self.channel = channel
            self.calls = []
            DummyFactory.instances.append(self)

        def produce_video_with_gui(self, *args, **kwargs):
            self.calls.append({"args": args, "kwargs": kwargs})
            return "C:/ReverieStudio/data/outputs/resume_test_project.mp4"

    monkeypatch.setattr(production_module, "ScenarioPlanner", DummyScenarioPlanner)
    monkeypatch.setattr(production_module, "MediaFactory", DummyFactory)
    monkeypatch.setattr(DummyProductionWorker, "_run_production_preflight", lambda self: None)

    window = DummyProductionWorker(resume=True, skip_thumbnail=False)
    window._production_worker(
        channel="senior",
        mode="touching",
        quantity=1,
        topic_mode="manual",
        manual_topic="체크포인트 테스트",
        prompt_mode="enhanced",
        pack_id="senior_touching",
    )

    assert DummyFactory.instances
    call = DummyFactory.instances[0].calls[0]["kwargs"]
    assert call["resume_from_checkpoint"] is True
    assert call["thumbnail_callback"] is not None


def test_production_worker_tolerates_broken_auto_upload_var(monkeypatch):
    import gui.mixins.production_mixin as production_module

    class DummyScenarioPlanner:
        def __init__(self, prompt_mode="enhanced"):
            self.prompt_mode = prompt_mode

        def create_senior_plan(self, topic, mode="touching"):
            return {
                "project_name": "auto_upload_safe_project",
                "title": topic,
                "script_list": [{"speaker": "narrator", "text": "line"}] * 10,
            }, "auto_upload_safe_project.json"

    class DummyFactory:
        instances = []

        def __init__(self, channel):
            self.channel = channel
            self.calls = []
            DummyFactory.instances.append(self)

        def produce_video_with_gui(self, *args, **kwargs):
            self.calls.append({"args": args, "kwargs": kwargs})
            return "C:/ReverieStudio/data/outputs/auto_upload_safe_project.mp4"

    monkeypatch.setattr(production_module, "ScenarioPlanner", DummyScenarioPlanner)
    monkeypatch.setattr(production_module, "MediaFactory", DummyFactory)
    monkeypatch.setattr(DummyProductionWorker, "_run_production_preflight", lambda self: None)

    window = DummyProductionWorker(resume=False, skip_thumbnail=False)
    window.auto_upload_var = BrokenGetter()
    window._production_worker(
        channel="senior",
        mode="touching",
        quantity=1,
        topic_mode="manual",
        manual_topic="자동 업로드 안전화 테스트",
        prompt_mode="enhanced",
        pack_id="senior_touching",
    )

    assert DummyFactory.instances
    assert window.production_stats.calls
    assert any("auto_upload_var" in log for log in window.logs)


def test_media_factory_creates_fresh_checkpoint_when_resume_target_missing(tmp_path, monkeypatch):
    factory = MediaFactory.__new__(MediaFactory)
    checkpoint_path = tmp_path / "missing_checkpoint.json"

    monkeypatch.setattr(
        ProductionCheckpoint,
        "load",
        classmethod(lambda cls, path: None),
    )

    checkpoint = factory._load_or_create_checkpoint(
        project_name="resume_test_project",
        checkpoint_path=str(checkpoint_path),
        resume_from_checkpoint=True,
    )

    assert checkpoint.project_name == "resume_test_project"
    assert checkpoint.stage == "init"
    assert checkpoint_path.parent.exists()


def test_media_factory_load_plan_payload_backfills_missing_project_name(tmp_path):
    factory = MediaFactory.__new__(MediaFactory)
    json_path = tmp_path / "fallback_name.json"
    json_path.write_text('{"title": "테스트 제목", "script_list": []}', encoding="utf-8")

    data = factory._load_plan_payload(str(json_path))

    assert data["project_name"] == "fallback_name"
    assert data["title"] == "테스트 제목"


def test_media_factory_sanitizes_checkpoint_when_assets_missing(tmp_path):
    factory = MediaFactory.__new__(MediaFactory)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint = ProductionCheckpoint(
        project_name="broken_resume",
        stage="render",
        audio_path=str(tmp_path / "missing_audio.wav"),
        subtitle_data=[{"text": "x"}],
        image_paths=[str(tmp_path / "missing_image.png")],
    )

    sanitized = factory._sanitize_checkpoint_state(checkpoint, str(checkpoint_path))

    assert sanitized.stage == "thumbnail"
    assert sanitized.audio_path == ""
    assert sanitized.subtitle_data == []
    assert sanitized.image_paths == []
    assert checkpoint_path.exists()


def test_production_checkpoint_load_backfills_missing_project_name(tmp_path):
    checkpoint_path = tmp_path / "fallback_checkpoint.json"
    checkpoint_path.write_text('{"stage":"tts","subtitle_data":"bad","image_paths":"bad"}', encoding="utf-8")

    checkpoint = ProductionCheckpoint.load(str(checkpoint_path))

    assert checkpoint is not None
    assert checkpoint.project_name == "fallback"
    assert checkpoint.subtitle_data == []
    assert checkpoint.image_paths == []


def test_production_worker_ensure_plan_json_writes_fallback_file(tmp_path):
    window = DummyProductionForQueue()
    plan_data = {"project_name": "plan_fallback", "title": "Fallback"}

    original_data_dir = config.DATA_DIR
    config.DATA_DIR = str(tmp_path)
    try:
        _, json_path = window._ensure_plan_json(plan_data, "")
    finally:
        config.DATA_DIR = original_data_dir

    assert json_path.endswith("plan_fallback.json")
    assert (tmp_path / "scripts" / "plan_fallback.json").exists()


def test_safe_get_quantity_falls_back_on_invalid_gui_value():
    window = DummyProductionForQueue()
    window.quantity_var = BrokenGetter()

    assert window._safe_get_quantity(default=2) == 2
    assert any("quantity_var" in log for log in window.logs)


def test_start_production_with_plan_uses_project_name_from_plan(monkeypatch, tmp_path):
    import gui.mixins.production_mixin as production_module

    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    class DummyFactory:
        def __init__(self, channel):
            self.channel = channel

    window = DummyProductionWorker(resume=False, skip_thumbnail=False)
    window.is_producing = False
    window.channel_var = DummyVar("senior_touching")
    window._produce_video_for_gui = lambda *args, **kwargs: str(tmp_path / "preview.mp4")

    monkeypatch.setattr(production_module, "MediaFactory", DummyFactory)
    monkeypatch.setattr(production_module.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(DummyProductionWorker, "_run_production_preflight", lambda self: None)

    plan_data = {"project_name": "approved_project", "title": "승인본"}
    original_data_dir = config.DATA_DIR
    config.DATA_DIR = str(tmp_path)
    try:
        window._start_production_with_plan(plan_data, "senior", "touching")
    finally:
        config.DATA_DIR = original_data_dir

    assert window.production_stats.calls
    assert window.production_stats.calls[0]["project_name"] == "approved_project"


def test_run_production_preflight_starts_missing_required_servers(monkeypatch, tmp_path):
    import gui.mixins.production_mixin as production_module

    class FakeManager:
        def __init__(self):
            self.started = []
            self.running = {"SD WebUI": False, "GPT-SoVITS": False}

        def check_server(self, name):
            return self.running.get(name, False)

        def start_server(self, name):
            self.started.append(name)
            self.running[name] = True
            return True

        def get_status(self, name):
            return {"error": ""}

    manager = FakeManager()
    window = DummyProductionForQueue()
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_text("", encoding="utf-8")
    ffprobe.write_text("", encoding="utf-8")
    fake_mixin_path = tmp_path / "src" / "gui" / "mixins" / "production_mixin.py"
    fake_remotion_root = tmp_path / "remotion-poc"
    fake_mixin_path.parent.mkdir(parents=True, exist_ok=True)
    fake_mixin_path.write_text("", encoding="utf-8")
    fake_remotion_root.mkdir(parents=True, exist_ok=True)
    (fake_remotion_root / "package.json").write_text("{}", encoding="utf-8")
    (fake_remotion_root / "node_modules").mkdir()

    original_provider = getattr(config, "STORY_LLM_PROVIDER", "")
    original_cli_path = getattr(config, "CLAUDE_CLI_PATH", "")
    original_tts_engine = getattr(config, "TTS_ENGINE", "")
    original_hybrid = getattr(config, "TTS_HYBRID_ENABLED", False)
    config.STORY_LLM_PROVIDER = "claude_cli"
    config.CLAUDE_CLI_PATH = "claude"
    config.TTS_ENGINE = "sovits"
    config.TTS_HYBRID_ENABLED = False

    def fake_which(name):
        mapping = {"claude": str(tmp_path / "claude.cmd"), "npx": str(tmp_path / "npx.cmd"), "npx.cmd": str(tmp_path / "npx.cmd")}
        path = mapping.get(name)
        if path:
            Path(path).write_text("", encoding="utf-8")
        return path

    monkeypatch.setattr(production_module, "get_ffmpeg_path", lambda: str(ffmpeg))
    monkeypatch.setattr(production_module, "get_ffprobe_path", lambda: str(ffprobe))
    monkeypatch.setattr(production_module.shutil, "which", fake_which)
    monkeypatch.setattr("utils.server_manager.get_server_manager", lambda: manager)
    monkeypatch.setattr(production_module, "__file__", str(fake_mixin_path))

    try:
        window._run_production_preflight()
    finally:
        config.STORY_LLM_PROVIDER = original_provider
        config.CLAUDE_CLI_PATH = original_cli_path
        config.TTS_ENGINE = original_tts_engine
        config.TTS_HYBRID_ENABLED = original_hybrid

    assert manager.started == ["SD WebUI", "GPT-SoVITS"]


def test_run_production_preflight_fails_fast_when_claude_cli_missing(monkeypatch, tmp_path):
    import gui.mixins.production_mixin as production_module

    window = DummyProductionForQueue()
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_text("", encoding="utf-8")
    ffprobe.write_text("", encoding="utf-8")

    original_provider = getattr(config, "STORY_LLM_PROVIDER", "")
    original_cli_path = getattr(config, "CLAUDE_CLI_PATH", "")
    config.STORY_LLM_PROVIDER = "claude_cli"
    config.CLAUDE_CLI_PATH = "missing-claude"

    monkeypatch.setattr(production_module, "get_ffmpeg_path", lambda: str(ffmpeg))
    monkeypatch.setattr(production_module, "get_ffprobe_path", lambda: str(ffprobe))
    monkeypatch.setattr(production_module.shutil, "which", lambda name: None)

    try:
        try:
            window._run_production_preflight()
            assert False, "expected FileNotFoundError"
        except FileNotFoundError as e:
            assert "Claude CLI" in str(e)
    finally:
        config.STORY_LLM_PROVIDER = original_provider
        config.CLAUDE_CLI_PATH = original_cli_path


def test_queue_worker_reuses_existing_plan_json_on_retry(tmp_path, monkeypatch):
    import gui.mixins.production_mixin as production_module
    import modules_pro.media_factory as media_factory_module

    plan_path = tmp_path / "retry_plan.json"
    plan_path.write_text(
        '{"project_name": "retry_project", "title": "Retry Topic", "script_list": []}',
        encoding="utf-8",
    )

    queue = BatchQueue(str(tmp_path))
    job_id = queue.add_job(
        channel="senior",
        mode="touching",
        manual_topic="Retry Topic",
        resume_from_checkpoint=False,
    )
    queue.update_job(job_id, topic="Retry Topic", json_path=str(plan_path), project_name="retry_project")
    queue.start_job(job_id)
    queue.fail_job(job_id, "boom")
    retry_job_id = queue.retry_job(job_id)

    class DummyScenarioPlanner:
        def __init__(self, prompt_mode="enhanced"):
            self.prompt_mode = prompt_mode

        def get_auto_topic(self, *_args, **_kwargs):
            raise AssertionError("Auto topic generation should not run for a retry job with json_path")

        def create_senior_plan(self, *_args, **_kwargs):
            raise AssertionError("Plan regeneration should not run for a retry job with json_path")

        def create_horror_plan(self, *_args, **_kwargs):
            raise AssertionError("Plan regeneration should not run for a retry job with json_path")

    class DummyFactory:
        instances = []

        def __init__(self, channel):
            self.channel = channel
            self.calls = []
            DummyFactory.instances.append(self)

        def produce_video_with_gui(self, json_path, *args, **kwargs):
            self.calls.append({"json_path": json_path, "kwargs": kwargs})
            return str(tmp_path / "retry_project.mp4")

    monkeypatch.setattr(production_module, "ScenarioPlanner", DummyScenarioPlanner)
    monkeypatch.setattr(media_factory_module, "MediaFactory", DummyFactory)
    monkeypatch.setattr(DummyQueueWorkerWindow, "_run_production_preflight", lambda self: None)

    window = DummyQueueWorkerWindow(queue)
    window._queue_worker()

    retry_job = queue.get_job(retry_job_id)

    assert DummyFactory.instances
    assert DummyFactory.instances[0].calls[0]["json_path"] == str(plan_path)
    assert DummyFactory.instances[0].calls[0]["kwargs"]["resume_from_checkpoint"] is False
    assert retry_job["status"] == "completed"


def test_load_reused_plan_for_job_falls_back_on_invalid_json(tmp_path):
    window = DummyProductionForQueue()
    broken_path = tmp_path / "broken.json"
    broken_path.write_text("{", encoding="utf-8")

    plan_data, json_path = window._load_reused_plan_for_job({"json_path": str(broken_path)})

    assert plan_data is None
    assert json_path == ""
    assert any("새로 생성합니다" in log for log in window.logs)


def test_produce_video_for_gui_skips_thumbnail_when_requested():
    class DummyFactory:
        def __init__(self):
            self.kwargs = None

        def produce_video_with_gui(self, *args, **kwargs):
            self.kwargs = kwargs
            return "ok"

    window = DummyProductionWorker(resume=False, skip_thumbnail=True)
    factory = DummyFactory()

    result = window._produce_video_for_gui(
        factory,
        "resume_test_project.json",
        skip_thumbnail=True,
        resume_from_checkpoint=False,
    )

    assert result == "ok"
    assert factory.kwargs["resume_from_checkpoint"] is False
    assert factory.kwargs["thumbnail_callback"] is None


def test_find_manual_resume_candidate_uses_checkpoint_plan_json(tmp_path):
    window = DummyProductionWorker(resume=True, skip_thumbnail=False)

    original_data_dir = config.DATA_DIR
    config.DATA_DIR = str(tmp_path)
    try:
        plan_path = tmp_path / "scripts" / "resume_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "project_name": "resume_project",
                    "title": "Resume Topic",
                    "category": "senior",
                    "mode": "life_saguk",
                    "script_list": [{"role": "narrator", "text": "line"}] * 12,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        checkpoint_path = tmp_path / "checkpoints" / "resume_project_checkpoint.json"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(
                {
                    "project_name": "resume_project",
                    "stage": "thumbnail",
                    "plan_json_path": str(plan_path),
                    "script_turns": 12,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        candidate = window._find_manual_resume_candidate("senior", "life_saguk")
    finally:
        config.DATA_DIR = original_data_dir

    assert candidate is not None
    assert candidate["json_path"] == str(plan_path)
    assert candidate["checkpoint_stage"] == "thumbnail"
    assert candidate["script_turns"] == 12


def test_prompt_manual_resume_choice_records_user_acceptance(tmp_path, monkeypatch):
    window = DummyProductionWorker(resume=True, skip_thumbnail=False)

    original_data_dir = config.DATA_DIR
    config.DATA_DIR = str(tmp_path)
    try:
        plan_path = tmp_path / "scripts" / "resume_plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "project_name": "resume_project",
                    "title": "Resume Topic",
                    "category": "senior",
                    "mode": "life_saguk",
                    "script_list": [{"role": "narrator", "text": "line"}] * 8,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        checkpoint_path = tmp_path / "checkpoints" / "resume_project_checkpoint.json"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(
                {
                    "project_name": "resume_project",
                    "stage": "thumbnail",
                    "plan_json_path": str(plan_path),
                    "script_turns": 8,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        prompts = []

        def fake_askyesno(title, message):
            prompts.append((title, message))
            return True

        monkeypatch.setattr("gui.mixins.production_mixin.messagebox.askyesno", fake_askyesno)
        window._prompt_manual_resume_choice("senior", "life_saguk")
    finally:
        config.DATA_DIR = original_data_dir

    assert prompts
    assert prompts[0][0] in ("Resume checkpoint", "체크포인트 재개")
    assert "resume_project" in prompts[0][1]
    assert window._manual_resume_plan_choice["accepted"] is True
    assert window._manual_resume_plan_choice["json_path"] == str(plan_path)
