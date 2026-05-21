import json
from pathlib import Path

from PIL import Image

from config.pack_config import _load_motiontoon_config, resolve_motiontoon_runtime_config
from config.pack_models import MotiontoonConfig
from config.settings_v2 import ReverieSettings
from modules_pro.scene_analyzer import CharacterState, SceneAnalysisResult
from modules_pro.videotoon_local import (
    VideoToonCharacterCue,
    VideoToonLocalWorkspace,
    VideoToonSceneSpec,
    VideoToonStackConfig,
    build_scene_specs_from_production,
)


def test_settings_exposes_videotoon_config(tmp_path):
    settings = ReverieSettings(
        BASE_DIR=str(tmp_path),
        VIDEOTOON_LOCAL_MODE_OVERRIDE=True,
        VIDEOTOON_WORKSPACE_ROOT=str(tmp_path / "vt"),
        VIDEOTOON_IMAGE_BACKEND="comfyui",
        VIDEOTOON_GENERATION_WIDTH=1024,
        VIDEOTOON_GENERATION_HEIGHT=576,
        VIDEOTOON_MAX_PARALLEL_IMAGE_JOBS=0,
        VIDEOTOON_LAYER_TOOL_PYTHON=str(tmp_path / ".venv" / "Scripts" / "python.exe"),
        COMFYUI_URL="http://127.0.0.1:8188",
        COMFYUI_ROOT=str(tmp_path / "ComfyUI"),
    )

    config = settings.get_videotoon_config()

    assert config["workspace_root"] == str(tmp_path / "vt")
    assert config["local_mode_enabled"] is True
    assert config["image_backend"] == "comfyui"
    assert config["generation_width"] == 1024
    assert config["generation_height"] == 576
    assert config["max_parallel_image_jobs"] == 1
    assert config["layer_tool_python"].endswith("python.exe")
    assert config["comfyui_url"] == "http://127.0.0.1:8188"


def test_scene_spec_from_scene_result_preserves_storyboard_fields():
    scene = SceneAnalysisResult(
        scene_id="scene_0012",
        dialogue_index=12,
        location="police station",
        location_detail="investigation desk",
        time_of_day="night",
        weather="rainy",
        atmosphere="tense",
        story_beat="climax",
        camera_shot="medium close-up",
        key_props=["phone", "bank slip"],
        outfit_hint="same cardigan",
        sd_prompt="elderly korean woman crying at investigation desk",
        continuity_hint="same woman from previous scene",
        original_dialogue="What happened to my account?",
        speaker="Sunja",
        characters=[
            CharacterState(
                id="grandma_sunja",
                name="Sunja",
                emotion="panic",
                action="crying",
                is_speaker=True,
            )
        ],
    )

    spec = VideoToonSceneSpec.from_scene_result(scene)

    assert spec.scene_id == "scene_0012"
    assert spec.dialogue_index == 12
    assert spec.location_detail == "investigation desk"
    assert spec.key_props == ["phone", "bank slip"]
    assert spec.characters[0].id == "grandma_sunja"
    assert spec.characters[0].emotion == "panic"
    assert spec.required_outputs == [
        "background_plate",
        "character_foreground_alpha",
        "mouth_closed",
        "mouth_open",
        "composite_preview",
    ]


def test_workspace_writes_storyboard_and_generation_request(tmp_path):
    config = VideoToonStackConfig(
        workspace_root=str(tmp_path / "VideoToon"),
        image_backend="comfyui",
        generation_width=1024,
        generation_height=576,
        max_parallel_image_jobs=1,
        layer_tool_python=str(tmp_path / "python.exe"),
        comfyui_url="http://127.0.0.1:8188",
        comfyui_root=str(tmp_path / "ComfyUI"),
    )
    workspace = VideoToonLocalWorkspace(config)
    scene = VideoToonSceneSpec(
        scene_id="scene_0001",
        text="The phone rings again.",
        speaker="Sunja",
        location="living room",
        sd_prompt="elderly korean woman holding smartphone in living room",
    )

    storyboard_path = workspace.write_storyboard("run:01", [scene])
    artifacts = workspace.write_generation_request("run:01", scene)

    storyboard = json.loads(Path(storyboard_path).read_text(encoding="utf-8"))
    request = json.loads(Path(artifacts.generation_request_path).read_text(encoding="utf-8"))

    assert storyboard["schema"] == "reverie.videotoon.storyboard.v1"
    assert storyboard["production_id"] == "run:01"
    assert storyboard["scenes"][0]["scene_id"] == "scene_0001"
    assert request["backend"] == "comfyui"
    assert request["size"] == {"width": 1024, "height": 576}
    assert request["character_reference_mode"] == "ip_adapter_plus_face_sd15"
    assert request["pose_control_mode"] == "controlnet_openpose_sd15"
    assert Path(artifacts.scene_dir).name == "scene_0001"
    assert "run_01" in artifacts.scene_dir


def test_workspace_writes_background_plate_request_without_character_focus(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scene = VideoToonSceneSpec(
        scene_id="scene_0011",
        speaker="Sunja",
        text="The phone buzzes on the table.",
        location="old apartment living room",
        location_detail="blue sofa and low wooden table",
        time_of_day="early morning",
        atmosphere="uneasy but ordinary",
        sd_prompt="elderly korean woman holding a phone in an old apartment living room",
    )

    artifacts = workspace.write_background_plate_request("run-bg", scene)
    request = json.loads(Path(artifacts.background_generation_request_path).read_text(encoding="utf-8"))

    assert request["layer_role"] == "background_plate"
    assert request["target_artifact"] == "background_path"
    assert request["target_artifact_path"] == artifacts.background_path
    assert "empty background plate" in request["prompt"]
    assert "old apartment living room" in request["prompt"]
    assert "blue sofa and low wooden table" in request["prompt"]
    assert "no people" in request["negative_prompt"]


def test_artifact_paths_map_to_remotion_layer_fields(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path)))

    artifacts = workspace.scene_artifacts("prod", "scene:bad/name")
    fields = artifacts.to_remotion_layer_fields()

    assert Path(artifacts.scene_dir).name == "scene_bad_name"
    assert fields == {
        "background_path": artifacts.background_path,
        "foreground_path": artifacts.foreground_path,
        "eyes_open_path": artifacts.eyes_open_path,
        "eyes_closed_path": artifacts.eyes_closed_path,
        "mouth_closed_path": artifacts.mouth_closed_path,
        "mouth_open_path": artifacts.mouth_open_path,
    }


def test_motiontoon_config_preserves_videotoon_pack_options():
    config = _load_motiontoon_config(
        {
            "motiontoon": {
                "enabled": True,
                "profile": "gishini",
                "video_toon_local_enabled": True,
                "video_toon_generation_backend": "comfyui",
                "video_toon_layered_assets_required": True,
                "video_toon_workflow_template": "sd15_ipadapter_openpose_v1",
            }
        }
    )
    resolved, _support = resolve_motiontoon_runtime_config(motiontoon=config)

    assert config.video_toon_local_enabled is True
    assert config.video_toon_generation_backend == "comfyui"
    assert config.video_toon_layered_assets_required is True
    assert config.video_toon_workflow_template == "sd15_ipadapter_openpose_v1"
    assert resolved.video_toon_local_enabled is True
    assert resolved.video_toon_generation_backend == "comfyui"


def test_workspace_status_requires_pack_opt_in_even_when_stack_assets_exist(tmp_path):
    layer_python = tmp_path / "python.exe"
    layer_python.write_text("", encoding="utf-8")
    workspace_root = tmp_path / "VideoToon"
    workspace = VideoToonLocalWorkspace(
        VideoToonStackConfig(
            workspace_root=str(workspace_root),
            layer_tool_python=str(layer_python),
        )
    )
    workspace.ensure_layout()
    for relative_path in (
        "models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "models/ipadapter/ip-adapter-plus_sd15.safetensors",
        "models/ipadapter/ip-adapter-plus-face_sd15.safetensors",
        "models/controlnet/control_v11p_sd15_openpose.pth",
        "models/controlnet/control_v11f1p_sd15_depth.pth",
        "tools/remove_background.py",
        "tools/audio_rms_mouth_cues.py",
    ):
        path = workspace_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    disabled = workspace.build_status(
        MotiontoonConfig(
            enabled=True,
            video_toon_local_enabled=False,
            video_toon_generation_backend="comfyui",
            video_toon_layered_assets_required=True,
        )
    )
    enabled = workspace.build_status(
        MotiontoonConfig(
            enabled=True,
            video_toon_local_enabled=True,
            video_toon_generation_backend="comfyui",
            video_toon_layered_assets_required=True,
        )
    )

    assert disabled["ready"] is False
    assert disabled["stack_ready"] is True
    assert disabled["pack_enabled"] is False
    assert disabled["reason"] == "pack_disabled"
    assert enabled["ready"] is True
    assert enabled["backend"] == "comfyui"


def test_workspace_compiles_core_comfyui_prompt_from_generation_request(tmp_path):
    workspace = VideoToonLocalWorkspace(
        VideoToonStackConfig(
            workspace_root=str(tmp_path / "VideoToon"),
            generation_width=1024,
            generation_height=576,
        )
    )
    scene = VideoToonSceneSpec(
        scene_id="scene_0003",
        text="The transfer alert arrives.",
        speaker="Sunja",
        sd_prompt="elderly korean woman holding a phone, tense apartment room",
    )
    artifacts = workspace.write_generation_request("run-01", scene)
    request = json.loads(Path(artifacts.generation_request_path).read_text(encoding="utf-8"))

    prompt = workspace.compile_comfyui_prompt(
        request,
        checkpoint="counterfeitV30_v30.safetensors",
        seed=123,
    )

    assert prompt["1"]["class_type"] == "CheckpointLoaderSimple"
    assert prompt["4"]["class_type"] == "EmptyLatentImage"
    assert prompt["4"]["inputs"]["width"] == 1024
    assert prompt["4"]["inputs"]["height"] == 576
    assert prompt["5"]["inputs"]["text"] == scene.sd_prompt
    assert "worst quality" in prompt["6"]["inputs"]["text"]
    assert prompt["7"]["inputs"]["seed"] == 123
    assert prompt["9"]["class_type"] == "SaveImage"
    assert "reverie_videotoon/run-01/scene_0003" in prompt["9"]["inputs"]["filename_prefix"]


def test_workspace_submits_generation_request_with_fake_client(tmp_path):
    class FakeComfyClient:
        def __init__(self):
            self.prompt = None

        def queue_prompt(self, prompt):
            self.prompt = prompt
            return "prompt-123"

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scene = VideoToonSceneSpec(scene_id="scene_0004", sd_prompt="phone on a bank desk")
    artifacts = workspace.write_generation_request("run-01", scene)
    fake_client = FakeComfyClient()

    result = workspace.submit_generation_request(
        artifacts.generation_request_path,
        client=fake_client,
        checkpoint="counterfeitV30_v30.safetensors",
        seed=321,
    )

    submission = json.loads(Path(artifacts.comfyui_submission_path).read_text(encoding="utf-8"))
    assert result["prompt_id"] == "prompt-123"
    assert result["submission_path"] == artifacts.comfyui_submission_path
    assert fake_client.prompt["7"]["inputs"]["seed"] == 321
    assert submission["prompt_id"] == "prompt-123"
    assert submission["prompt"]["9"]["class_type"] == "SaveImage"


def test_workspace_ingests_comfyui_history_output_into_scene_composite(tmp_path):
    class FakeComfyClient:
        def __init__(self):
            self.saved = []

        def save_output(self, filename, save_path, subfolder="", output_type="output"):
            Image.new("RGB", (32, 18), (10, 20, 30)).save(save_path)
            self.saved.append(
                {
                    "filename": filename,
                    "save_path": save_path,
                    "subfolder": subfolder,
                    "output_type": output_type,
                }
            )
            return save_path

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scenes = [VideoToonSceneSpec(scene_id="scene_0005", sd_prompt="phone alert")]
    workspace.write_production_bundle("run-result", scenes)
    artifacts = workspace.scene_artifacts("run-result", "scene_0005")
    history = {
        "outputs": {
            "9": {
                "images": [
                    {
                        "filename": "scene_0005_00001_.png",
                        "subfolder": "reverie_videotoon/run-result/scene_0005",
                        "type": "output",
                    }
                ]
            }
        }
    }

    result = workspace.ingest_comfyui_result("run-result", artifacts, history, client=FakeComfyClient())

    status = json.loads(Path(artifacts.status_path).read_text(encoding="utf-8"))
    progress = json.loads(Path(workspace.bundle_progress_path("run-result")).read_text(encoding="utf-8"))
    report = json.loads(Path(artifacts.comfyui_result_path).read_text(encoding="utf-8"))

    assert Path(artifacts.composite_path).is_file()
    assert result["composite_path"] == artifacts.composite_path
    assert status["status"] == "generated"
    assert progress["status_counts"] == {"generated": 1}
    assert report["selected_image"]["filename"] == "scene_0005_00001_.png"


def test_workspace_executes_generation_request_with_fake_comfyui_client(tmp_path):
    class FakeComfyClient:
        def __init__(self):
            self.queued_prompt = None

        def queue_prompt(self, prompt):
            self.queued_prompt = prompt
            return "prompt-runner-1"

        def wait_for_completion(self, prompt_id, progress_callback=None, timeout=None):
            assert prompt_id == "prompt-runner-1"
            return {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "scene_0006_00001_.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }

        def save_output(self, filename, save_path, subfolder="", output_type="output"):
            Image.new("RGB", (32, 18), (40, 50, 60)).save(save_path)
            return save_path

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scene = VideoToonSceneSpec(scene_id="scene_0006", sd_prompt="elderly woman holding phone")
    workspace.write_production_bundle("run-execute", [scene])
    artifacts = workspace.scene_artifacts("run-execute", "scene_0006")
    fake_client = FakeComfyClient()

    result = workspace.execute_generation_request(
        artifacts.generation_request_path,
        client=fake_client,
        checkpoint="counterfeitV30_v30.safetensors",
        seed=123,
    )

    assert result["prompt_id"] == "prompt-runner-1"
    assert result["status"] == "generated"
    assert Path(artifacts.composite_path).is_file()
    assert fake_client.queued_prompt["7"]["inputs"]["seed"] == 123


def test_workspace_execute_generation_request_can_finalize_generated_layers(tmp_path):
    class FakeComfyClient:
        def queue_prompt(self, prompt):
            return "prompt-finalize-1"

        def wait_for_completion(self, prompt_id, progress_callback=None, timeout=None):
            return {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "scene_0007_00001_.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }

        def save_output(self, filename, save_path, subfolder="", output_type="output"):
            Image.new("RGB", (64, 36), (90, 110, 130)).save(save_path)
            return save_path

    def fake_background_removal(input_path: str, output_path: str):
        Image.new("RGBA", (64, 36), (255, 0, 0, 128)).save(output_path)

    def fake_mouth_cues(wav_path: str, output_path: str, fps: int):
        Path(output_path).write_text(
            json.dumps({"source": wav_path, "fps": fps, "cues": [{"frame": 0, "mouth": 1}]}),
            encoding="utf-8",
        )

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake wav")
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scene = VideoToonSceneSpec(scene_id="scene_0007", sd_prompt="woman speaking in apartment")
    workspace.write_production_bundle("run-finalize", [scene])
    artifacts = workspace.scene_artifacts("run-finalize", "scene_0007")

    result = workspace.execute_generation_request(
        artifacts.generation_request_path,
        client=FakeComfyClient(),
        finalize_layers=True,
        use_composite_as_background=True,
        audio_path=str(audio),
        background_removal_runner=fake_background_removal,
        mouth_cue_runner=fake_mouth_cues,
    )
    status = json.loads(Path(artifacts.status_path).read_text(encoding="utf-8"))

    assert result["status"] == "finalized"
    assert result["layer_qc"]["ready_for_remotion"] is True
    assert status["status"] == "finalized"
    assert Path(artifacts.background_path).is_file()
    assert Path(artifacts.foreground_path).is_file()
    assert Path(artifacts.mouth_cues_path).is_file()
    assert Path(artifacts.mouth_open_path).is_file()


def test_workspace_executes_background_plate_request_into_background_artifact(tmp_path):
    class FakeComfyClient:
        def queue_prompt(self, prompt):
            return "prompt-bg-1"

        def wait_for_completion(self, prompt_id, progress_callback=None, timeout=None):
            return {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": "background_00001_.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }

        def save_output(self, filename, save_path, subfolder="", output_type="output"):
            Image.new("RGB", (64, 36), (10, 120, 180)).save(save_path)
            return save_path

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scene = VideoToonSceneSpec(scene_id="scene_0012", location="police station", sd_prompt="woman at police station")
    artifacts = workspace.write_background_plate_request("run-bg-exec", scene)

    result = workspace.execute_generation_request(
        artifacts.background_generation_request_path,
        client=FakeComfyClient(),
        seed=33,
    )
    status = json.loads(Path(artifacts.status_path).read_text(encoding="utf-8"))

    assert result["status"] == "background_generated"
    assert result["target_artifact"] == "background_path"
    assert Path(artifacts.background_path).is_file()
    assert not Path(artifacts.composite_path).exists()
    assert status["status"] == "background_generated"


def test_workspace_applies_character_reference_from_manifest(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    refs_dir = Path(workspace.root) / "characters" / "refs" / "cheap_cast_v2"
    refs_dir.mkdir(parents=True, exist_ok=True)
    ref_path = refs_dir / "sunja_grandma_ref.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(ref_path)
    manifest_path = refs_dir / "cheap_cast_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": "reverie.videotoon.cheap_cast.v2",
                "characters": [
                    {
                        "character_id": "sunja_grandma",
                        "korean_name": "순자",
                        "role": "피해자 할머니",
                        "reference_image": str(ref_path),
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    scene = VideoToonSceneSpec(
        scene_id="scene_ref",
        speaker="순자",
        characters=[VideoToonCharacterCue(id="sunja_grandma", name="순자", is_speaker=True)],
    )

    manifest = workspace.load_character_reference_manifest()
    resolved = workspace.apply_character_reference(scene, manifest)

    assert resolved.character_reference_path == str(ref_path)
    assert "sunja_grandma" in resolved.continuity_hint


def test_workspace_prefers_golden_manifest_only_when_reference_images_exist(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    refs_root = Path(workspace.root) / "characters" / "refs"
    golden_dir = refs_root / "golden_cast_v1"
    cheap_dir = refs_root / "cheap_cast_v2"
    golden_dir.mkdir(parents=True, exist_ok=True)
    cheap_dir.mkdir(parents=True, exist_ok=True)

    golden_ref = golden_dir / "sunja_grandma_golden_ref.png"
    cheap_ref = cheap_dir / "sunja_grandma_ref.png"
    Image.new("RGBA", (32, 32), (255, 0, 0, 255)).save(cheap_ref)
    (golden_dir / "golden_cast_manifest.json").write_text(
        json.dumps(
            {
                "schema": "reverie.videotoon.golden_cast.v1",
                "characters": [{"character_id": "sunja_grandma", "reference_image": str(golden_ref)}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cheap_dir / "cheap_cast_manifest.json").write_text(
        json.dumps(
            {
                "schema": "reverie.videotoon.cheap_cast.v2",
                "characters": [{"character_id": "sunja_grandma", "reference_image": str(cheap_ref)}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert workspace.default_character_manifest_path() == cheap_dir / "cheap_cast_manifest.json"

    Image.new("RGBA", (32, 32), (0, 255, 0, 255)).save(golden_ref)

    assert workspace.default_character_manifest_path() == golden_dir / "golden_cast_manifest.json"


def test_workspace_executes_production_bundle_and_continues_after_scene_failure(tmp_path):
    class FakeComfyClient:
        def __init__(self):
            self.count = 0

        def queue_prompt(self, prompt):
            self.count += 1
            return f"prompt-{self.count}"

        def wait_for_completion(self, prompt_id, progress_callback=None, timeout=None):
            if prompt_id == "prompt-2":
                raise RuntimeError("simulated ComfyUI failure")
            return {
                "outputs": {
                    "9": {
                        "images": [
                            {
                                "filename": f"{prompt_id}.png",
                                "subfolder": "",
                                "type": "output",
                            }
                        ]
                    }
                }
            }

        def save_output(self, filename, save_path, subfolder="", output_type="output"):
            Image.new("RGB", (32, 18), (70, 80, 90)).save(save_path)
            return save_path

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    manifest = workspace.write_production_bundle(
        "run-bundle-exec",
        [
            VideoToonSceneSpec(scene_id="scene_0001", sd_prompt="first scene"),
            VideoToonSceneSpec(scene_id="scene_0002", sd_prompt="second scene"),
            VideoToonSceneSpec(scene_id="scene_0003", sd_prompt="third scene"),
        ],
    )

    summary = workspace.execute_production_bundle(
        manifest["manifest_path"],
        client=FakeComfyClient(),
        seed=100,
    )
    progress = json.loads(Path(workspace.bundle_progress_path("run-bundle-exec")).read_text(encoding="utf-8"))

    assert summary["generated_count"] == 2
    assert summary["failed_count"] == 1
    assert Path(summary["summary_path"]).is_file()
    assert progress["status_counts"] == {"generated": 2, "failed": 1}
    assert progress["failed_scenes"][0]["scene_id"] == "scene_0002"
    assert "simulated ComfyUI failure" in progress["failed_scenes"][0]["reason"]


def test_scene_generation_request_includes_reference_control_assets():
    scene = VideoToonSceneSpec(
        scene_id="scene_0005",
        sd_prompt="same woman in a police station",
        character_reference_path=r"D:\refs\sunja_face.png",
        pose_reference_path=r"D:\poses\standing_phone.png",
        depth_reference_path=r"D:\poses\standing_phone.png",
    )

    request = scene.to_generation_request(VideoToonStackConfig(workspace_root=r"X:\ReverieVideoToon"))

    assert request["reference_assets"] == {
        "character_reference_path": r"D:\refs\sunja_face.png",
        "pose_reference_path": r"D:\poses\standing_phone.png",
        "depth_reference_path": r"D:\poses\standing_phone.png",
    }


def test_workspace_compiles_reference_pose_depth_comfyui_prompt(tmp_path):
    workspace = VideoToonLocalWorkspace(
        VideoToonStackConfig(
            workspace_root=str(tmp_path / "VideoToon"),
            generation_width=1024,
            generation_height=576,
        )
    )
    request = {
        "production_id": "run-adv",
        "scene_id": "scene_0006",
        "prompt": "consistent adult woman holding phone in apartment",
        "size": {"width": 1024, "height": 576},
        "reference_assets": {
            "character_reference_path": r"D:\refs\sunja_face.png",
            "pose_reference_path": r"D:\poses\standing_phone.png",
            "depth_reference_path": r"D:\poses\standing_phone.png",
        },
    }

    prompt = workspace.compile_comfyui_prompt(
        request,
        checkpoint="counterfeitV30_v30.safetensors",
        template="sd15_ipadapter_openpose_depth_v1",
        seed=777,
    )

    assert prompt["10"]["class_type"] == "VHS_LoadImagePath"
    assert prompt["10"]["inputs"]["image"] == r"D:\refs\sunja_face.png"
    assert prompt["11"]["class_type"] == "CLIPVisionLoader"
    assert prompt["12"]["class_type"] == "IPAdapterUnifiedLoader"
    assert prompt["13"]["class_type"] == "IPAdapterAdvanced"
    assert prompt["13"]["inputs"]["model"] == ["12", 0]
    assert prompt["20"]["class_type"] == "VHS_LoadImagePath"
    assert prompt["21"]["class_type"] == "OpenposePreprocessor"
    assert prompt["22"]["inputs"]["control_net_name"] == "control_v11p_sd15_openpose.pth"
    assert prompt["23"]["class_type"] == "ControlNetApplyAdvanced"
    assert prompt["31"]["class_type"] == "DepthAnythingV2Preprocessor"
    assert prompt["32"]["inputs"]["control_net_name"] == "control_v11f1p_sd15_depth.pth"
    assert prompt["33"]["class_type"] == "ControlNetApplyAdvanced"
    assert prompt["7"]["inputs"]["model"] == ["13", 0]
    assert prompt["7"]["inputs"]["positive"] == ["33", 0]
    assert prompt["7"]["inputs"]["negative"] == ["33", 1]


def test_workspace_validates_advanced_comfyui_template_contract():
    object_info = {
        "CheckpointLoaderSimple": {},
        "CLIPTextEncode": {},
        "EmptyLatentImage": {},
        "KSampler": {},
        "VAEDecode": {},
        "SaveImage": {},
        "VHS_LoadImagePath": {},
        "CLIPVisionLoader": {},
        "IPAdapterUnifiedLoader": {},
        "IPAdapterAdvanced": {},
        "OpenposePreprocessor": {},
        "ControlNetLoader": {},
        "ControlNetApplyAdvanced": {},
        "DepthAnythingV2Preprocessor": {},
    }

    status = VideoToonLocalWorkspace.validate_comfyui_template_contract(
        object_info,
        template="sd15_ipadapter_openpose_depth_v1",
    )
    missing_status = VideoToonLocalWorkspace.validate_comfyui_template_contract(
        {"CheckpointLoaderSimple": {}},
        template="sd15_ipadapter_openpose_depth_v1",
    )

    assert status["ready"] is True
    assert status["missing_nodes"] == []
    assert missing_status["ready"] is False
    assert "IPAdapterAdvanced" in missing_status["missing_nodes"]


def test_workspace_finalizes_scene_layers_with_qc_report(tmp_path):
    composite = tmp_path / "composite_source.png"
    background = tmp_path / "background_source.png"
    audio = tmp_path / "voice.wav"
    Image.new("RGB", (64, 36), (120, 80, 60)).save(composite)
    Image.new("RGB", (64, 36), (20, 30, 40)).save(background)
    audio.write_bytes(b"fake wav")

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-final", "scene_0007")

    def fake_background_removal(input_path: str, output_path: str):
        Image.new("RGBA", (64, 36), (255, 0, 0, 128)).save(output_path)

    def fake_mouth_cues(wav_path: str, output_path: str, fps: int):
        Path(output_path).write_text(
            json.dumps({"source": wav_path, "fps": fps, "cues": [{"frame": 0, "mouth": 1}]}),
            encoding="utf-8",
        )

    report = workspace.finalize_scene_layers(
        artifacts,
        composite_source_path=str(composite),
        background_source_path=str(background),
        audio_path=str(audio),
        background_removal_runner=fake_background_removal,
        mouth_cue_runner=fake_mouth_cues,
    )

    qc = json.loads(Path(artifacts.qc_report_path).read_text(encoding="utf-8"))
    assert Path(artifacts.composite_path).is_file()
    assert Path(artifacts.background_path).is_file()
    assert Path(artifacts.foreground_path).is_file()
    assert Path(artifacts.mouth_cues_path).is_file()
    assert report["ready_for_remotion"] is True
    assert qc["ready_for_remotion"] is True
    assert qc["remotion_layer_fields"] == artifacts.to_remotion_layer_fields()


def test_workspace_layer_qc_blocks_missing_foreground(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-final", "scene_0008")
    Path(artifacts.scene_dir).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (20, 30, 40)).save(artifacts.background_path)

    report = workspace.write_layer_qc_report(artifacts)

    assert report["ready_for_remotion"] is False
    assert "foreground_path" in report["missing_required"]


def test_workspace_attaches_reusable_face_sprite_parts(tmp_path):
    source_dir = tmp_path / "face_parts"
    source_dir.mkdir()
    source_parts = {}
    for filename, color in (
        ("eyes_open.png", (255, 255, 255, 255)),
        ("eyes_closed.png", (20, 20, 20, 255)),
        ("mouth_closed.png", (90, 20, 20, 255)),
        ("mouth_open.png", (200, 40, 40, 255)),
    ):
        path = source_dir / filename
        Image.new("RGBA", (16, 8), color).save(path)
        source_parts[filename.removesuffix(".png") + "_path"] = str(path)

    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-face", "scene_0009")
    Path(artifacts.scene_dir).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (20, 30, 40)).save(artifacts.background_path)
    Image.new("RGBA", (64, 36), (255, 0, 0, 128)).save(artifacts.foreground_path)

    report = workspace.attach_face_sprite_assets(artifacts, source_parts)

    assert Path(artifacts.eyes_open_path).is_file()
    assert Path(artifacts.eyes_closed_path).is_file()
    assert Path(artifacts.mouth_closed_path).is_file()
    assert Path(artifacts.mouth_open_path).is_file()
    assert report["face_sprites_ready"] is True
    assert report["ready_for_remotion"] is True


def test_workspace_synthesizes_face_sprite_fallback_when_parts_are_missing(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-face", "scene_0010")
    Path(artifacts.scene_dir).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 72), (20, 30, 40)).save(artifacts.background_path)
    Image.new("RGBA", (128, 72), (255, 200, 180, 160)).save(artifacts.foreground_path)

    report = workspace.synthesize_face_sprite_fallback(artifacts, source_path=artifacts.foreground_path)

    for path in (
        artifacts.eyes_open_path,
        artifacts.eyes_closed_path,
        artifacts.mouth_closed_path,
        artifacts.mouth_open_path,
    ):
        image = Image.open(path)
        assert image.mode == "RGBA"
        assert image.size == (128, 72)

    assert report["face_sprites_ready"] is True
    assert report["ready_for_remotion"] is True
    assert "synthetic_face_sprite_fallback" in report["warnings"]


def test_workspace_synthesizes_face_sprite_fallback_from_foreground_alpha_bbox(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-face", "scene_0011")
    Path(artifacts.scene_dir).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (128, 72), (20, 30, 40)).save(artifacts.background_path)
    foreground = Image.new("RGBA", (128, 72), (0, 0, 0, 0))
    for x in range(18, 52):
        for y in range(8, 68):
            foreground.putpixel((x, y), (255, 200, 180, 200))
    foreground.save(artifacts.foreground_path)

    workspace.synthesize_face_sprite_fallback(artifacts, source_path=artifacts.foreground_path)

    mouth_open = Image.open(artifacts.mouth_open_path).convert("RGBA")
    bbox = mouth_open.getchannel("A").getbbox()
    assert bbox is not None
    center_x = (bbox[0] + bbox[2]) // 2
    assert 18 <= center_x <= 52


def test_workspace_writes_production_videotoon_bundle(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    script_list = [{"role": "순자", "text": "문자를 확인했다."}]
    image_prompts = [{"prompt": "phone screen in a kitchen", "location": "kitchen"}]

    scenes = build_scene_specs_from_production(script_list, image_prompts)
    manifest = workspace.write_production_bundle("run-bundle", scenes)

    assert manifest["schema"] == "reverie.videotoon.production_bundle.v1"
    assert manifest["scene_count"] == 1
    assert Path(manifest["storyboard_path"]).is_file()
    request_path = Path(manifest["scenes"][0]["generation_request_path"])
    assert request_path.is_file()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["prompt"] == "phone screen in a kitchen"
    assert request["storyboard"]["text"] == "문자를 확인했다."


def test_build_scene_specs_applies_episode_role_casting_to_actor_id():
    scenes = build_scene_specs_from_production(
        script_list=[
            {"role": "victim", "emotion": "fear", "text": "I should not have opened that message."},
            {"role": "scammer", "emotion": "smirk", "text": "Send it before midnight."},
        ],
        image_prompts=[
            {"prompt": "woman looking at phone", "shot_type": "medium_close", "motion_preset": "slow_push"},
            {"prompt": "man smiling in office", "shot_type": "prop_reveal", "motion_preset": "snap_zoom"},
        ],
        role_casting={
            "victim": "actor_woman_01",
            "scammer": "actor_man_01",
        },
    )

    assert scenes[0].role_id == "victim"
    assert scenes[0].actor_id == "actor_woman_01"
    assert scenes[0].emotion == "fear"
    assert scenes[0].shot_type == "medium_close"
    assert scenes[0].motion_preset == "slow_push"
    assert scenes[1].role_id == "scammer"
    assert scenes[1].actor_id == "actor_man_01"


def test_generation_request_includes_actor_contract_fields():
    scene = VideoToonSceneSpec(
        scene_id="scene_actor",
        role_id="victim",
        actor_id="actor_woman_01",
        emotion="fear",
        shot_type="medium_close",
        motion_preset="slow_push",
        sd_prompt="woman looking at phone",
    )
    request = scene.to_generation_request(VideoToonStackConfig(workspace_root="unused"))

    assert request["role_id"] == "victim"
    assert request["actor_id"] == "actor_woman_01"
    assert request["emotion"] == "fear"
    assert request["shot_type"] == "medium_close"
    assert request["motion_preset"] == "slow_push"
    assert request["storyboard"]["actor_id"] == "actor_woman_01"


def test_workspace_tracks_scene_status_and_bundle_progress(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    scenes = [
        VideoToonSceneSpec(scene_id="scene_0001", sd_prompt="phone alert in apartment"),
        VideoToonSceneSpec(scene_id="scene_0002", sd_prompt="bank receipt closeup"),
    ]

    manifest = workspace.write_production_bundle("run-progress", scenes)
    progress_path = Path(manifest["progress_path"])
    initial_progress = json.loads(progress_path.read_text(encoding="utf-8"))

    assert initial_progress["schema"] == "reverie.videotoon.bundle_progress.v1"
    assert initial_progress["total_scenes"] == 2
    assert initial_progress["status_counts"] == {"pending": 2}
    assert initial_progress["failed_scenes"] == []

    first = workspace.scene_artifacts("run-progress", "scene_0001")
    second = workspace.scene_artifacts("run-progress", "scene_0002")
    workspace.write_scene_status(
        "run-progress",
        first,
        status="submitted",
        stage="comfyui",
        reason="queued",
        retry_count=1,
        details={"prompt_id": "abc"},
    )
    workspace.write_scene_status(
        "run-progress",
        second,
        status="failed",
        stage="finalize",
        reason="background_removal_failed",
        details={"exception": "tool timeout"},
    )

    first_status = json.loads(Path(first.status_path).read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))

    assert first_status["status"] == "submitted"
    assert first_status["retry_count"] == 1
    assert progress["status_counts"] == {"submitted": 1, "failed": 1}
    assert progress["completed_scenes"] == 1
    assert progress["failed_scenes"] == [
        {
            "scene_id": "scene_0002",
            "stage": "finalize",
            "reason": "background_removal_failed",
        }
    ]


def test_workspace_rejects_unknown_scene_status(tmp_path):
    workspace = VideoToonLocalWorkspace(VideoToonStackConfig(workspace_root=str(tmp_path / "VideoToon")))
    artifacts = workspace.scene_artifacts("run-progress", "scene_0001")

    try:
        workspace.write_scene_status("run-progress", artifacts, status="mystery")
    except ValueError as exc:
        assert "Unsupported VideoToon scene status" in str(exc)
    else:
        raise AssertionError("write_scene_status accepted an unknown status")


def test_media_factory_can_write_videotoon_bundle_without_running_generation(tmp_path, monkeypatch):
    from config.settings import config
    from pipeline.orchestrator import MediaFactory

    monkeypatch.setattr(config, "VIDEOTOON_WORKSPACE_ROOT", str(tmp_path / "VideoToon"))
    monkeypatch.setattr(config, "VIDEOTOON_IMAGE_BACKEND", "comfyui")
    monkeypatch.setattr(config, "VIDEOTOON_LOCAL_MODE_OVERRIDE", True)

    factory = MediaFactory.__new__(MediaFactory)
    logs = []
    manifest = factory._write_videotoon_production_bundle(
        project_name="run-factory",
        script_list=[{"role": "순자", "text": "문자를 확인했다."}],
        image_prompts=["phone screen in a kitchen"],
        scene_analysis_cache=None,
        log_callback=logs.append,
    )

    assert manifest is not None
    assert manifest["scene_count"] == 1
    assert Path(manifest["manifest_path"]).is_file()
    assert Path(manifest["progress_path"]).is_file()
    assert any("VideoToon" in message for message in logs)
    assert any("progress" in message for message in logs)
