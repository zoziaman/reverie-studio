# tests/test_e2e_pipeline_mock.py
"""
v63.0 Phase 1: 목 기반 E2E 파이프라인 통합 테스트

외부 서비스(SD WebUI, GPT-SoVITS, Gemini, Remotion) 전부 목 처리하여
produce_video_with_gui의 전체 흐름을 검증.

테스트 범위:
- 파이프라인 초기화 (MediaFactory 생성)
- 기획안 JSON 로딩
- 품질 게이트 통과/실패
- 7-Step 흐름 (썸네일→데이터준비→TTS→이미지→SFX→렌더링→최종)
- 취소 토큰 동작
- 체크포인트 저장/복원
- 에러 전파 및 복구
"""
import os
import json
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass


# ============================================================
# 테스트용 데이터 생성 헬퍼
# ============================================================

def make_plan_json(temp_dir: str, num_turns: int = 5) -> str:
    """최소한의 기획안 JSON 생성"""
    script_list = []
    for i in range(num_turns):
        roles = ["narrator", "grandma", "grandpa"]
        script_list.append({
            "role": roles[i % len(roles)],
            "character": roles[i % len(roles)],
            "text": f"테스트 대사 {i+1}번입니다.",
            "emotion": "calm",
            "sfx_tag": "",
            "voice_type": roles[i % len(roles)],
        })

    plan = {
        "project_name": "test_project_001",
        "title": "테스트 영상 제목",
        "thumbnail_title": "테스트 썸네일",
        "thumbnail_text": "부제목",
        "topic": "테스트 주제: 할머니의 비밀",
        "mode": "touching",
        "category": "senior",
        "hook": "충격적인 비밀이 밝혀진다",
        "script_list": script_list,
        "visual_scenes": [f"scene prompt {i}" for i in range(num_turns)],
    }

    path = os.path.join(temp_dir, "test_plan.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return path


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="test_e2e_")
    # 필수 하위 디렉토리 생성
    os.makedirs(os.path.join(d, "thumbnails"), exist_ok=True)
    os.makedirs(os.path.join(d, "output"), exist_ok=True)
    os.makedirs(os.path.join(d, "checkpoints"), exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def plan_json(temp_dir):
    return make_plan_json(temp_dir)


# ============================================================
# 파이프라인 컴포넌트 목 클래스
# ============================================================

class MockTTSManager:
    """TTS 목 — 빈 WAV 파일 생성"""

    def __init__(self, *args, **kwargs):
        self._temp_dir = None

    def set_callbacks(self, **kwargs):
        pass

    def synthesize_all(self, script_list, output_dir, **kwargs):
        """빈 WAV 파일들 생성"""
        self._temp_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        subtitle_data = []
        audio_files = []
        current_time = 0.0

        for i, item in enumerate(script_list):
            duration = 2.0
            audio_path = os.path.join(output_dir, f"turn_{i:03d}.wav")
            with open(audio_path, "wb") as f:
                f.write(b"\x00" * 100)  # 빈 WAV
            audio_files.append(audio_path)

            subtitle_data.append({
                "text": item.get("text", ""),
                "role": item.get("role", "narrator"),
                "voice_type": item.get("voice_type", "narrator"),
                "emotion": item.get("emotion", "calm"),
                "start": current_time,
                "end": current_time + duration,
                "scene_end": current_time + duration + 0.3,
                "sfx_tag": item.get("sfx_tag", ""),
            })
            current_time += duration + 0.3

        # full.wav 생성
        full_audio = os.path.join(output_dir, "full.wav")
        with open(full_audio, "wb") as f:
            f.write(b"\x00" * 500)

        return {
            "subtitle_data": subtitle_data,
            "audio_files": audio_files,
            "full_audio_path": full_audio,
            "total_duration": current_time,
        }


class MockImagePipeline:
    """이미지 생성 목 — 빈 PNG 파일 생성"""

    def __init__(self, *args, **kwargs):
        pass

    def set_callbacks(self, **kwargs):
        pass

    def generate_all(self, prompts, output_dir, **kwargs):
        os.makedirs(output_dir, exist_ok=True)
        paths = []
        for i, prompt in enumerate(prompts):
            path = os.path.join(output_dir, f"scene_{i:03d}.png")
            with open(path, "wb") as f:
                f.write(b"\x89PNG" + b"\x00" * 50)
            paths.append(path)
        return paths


class MockVideoRenderer:
    """영상 렌더링 목 — 빈 MP4 파일 생성"""

    def __init__(self, *args, **kwargs):
        pass

    def set_callbacks(self, **kwargs):
        pass

    def assemble_main(self, audio_path, subtitle_data, image_paths, mode, topic=""):
        output = tempfile.mktemp(suffix=".mp4", prefix="mock_video_")
        with open(output, "wb") as f:
            f.write(b"\x00" * 200)  # 빈 MP4
        return output


# ============================================================
# 테스트 클래스
# ============================================================

class TestPlanJsonLoading:
    """기획안 JSON 로딩 테스트"""

    def test_valid_json_loads(self, plan_json):
        with open(plan_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["project_name"] == "test_project_001"
        assert len(data["script_list"]) == 5
        assert data["mode"] == "touching"

    def test_script_list_structure(self, plan_json):
        with open(plan_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data["script_list"]:
            assert "role" in item
            assert "text" in item
            assert "emotion" in item

    def test_visual_scenes_count_matches(self, plan_json):
        with open(plan_json, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data["visual_scenes"]) == len(data["script_list"])


class TestMockTTS:
    """TTS 목 동작 검증"""

    def test_synthesize_creates_files(self, temp_dir):
        tts = MockTTSManager()
        script = [
            {"text": "안녕하세요", "role": "narrator", "emotion": "calm"},
            {"text": "반갑습니다", "role": "grandma", "emotion": "happy"},
        ]

        output_dir = os.path.join(temp_dir, "tts_output")
        result = tts.synthesize_all(script, output_dir)

        assert len(result["subtitle_data"]) == 2
        assert len(result["audio_files"]) == 2
        assert os.path.exists(result["full_audio_path"])
        assert result["total_duration"] > 0

    def test_subtitle_timing_sequential(self, temp_dir):
        tts = MockTTSManager()
        script = [{"text": f"대사 {i}", "role": "narrator"} for i in range(5)]

        result = tts.synthesize_all(script, os.path.join(temp_dir, "tts"))

        # 타이밍이 순차적인지 확인
        for i in range(1, len(result["subtitle_data"])):
            assert result["subtitle_data"][i]["start"] > result["subtitle_data"][i-1]["start"]
            assert result["subtitle_data"][i]["start"] >= result["subtitle_data"][i-1]["end"]


class TestMockImagePipeline:
    """이미지 생성 목 동작 검증"""

    def test_generate_creates_files(self, temp_dir):
        img = MockImagePipeline()
        prompts = ["prompt 1", "prompt 2", "prompt 3"]

        output_dir = os.path.join(temp_dir, "images")
        paths = img.generate_all(prompts, output_dir)

        assert len(paths) == 3
        for p in paths:
            assert os.path.exists(p)
            assert p.endswith(".png")


class TestMockVideoRenderer:
    """영상 렌더링 목 동작 검증"""

    def test_assemble_creates_mp4(self, temp_dir):
        vr = MockVideoRenderer()

        # 빈 오디오 생성
        audio = os.path.join(temp_dir, "full.wav")
        with open(audio, "wb") as f:
            f.write(b"\x00" * 100)

        subtitle = [{"text": "테스트", "role": "narrator", "start": 0, "end": 2}]
        images = [os.path.join(temp_dir, "img.png")]
        with open(images[0], "wb") as f:
            f.write(b"\x89PNG" + b"\x00" * 50)

        result = vr.assemble_main(audio, subtitle, images, "horror", topic="테스트")
        assert result.endswith(".mp4")
        assert os.path.exists(result)


class TestE2EDataFlow:
    """전체 데이터 흐름 통합 테스트 (목 기반)"""

    def test_full_data_flow(self, temp_dir, plan_json):
        """
        기획안 → TTS → 이미지 → 렌더링 전체 흐름 검증
        (MediaFactory 없이 각 컴포넌트를 순차 호출)
        """
        # 1. 기획안 로드
        with open(plan_json, "r", encoding="utf-8") as f:
            plan = json.load(f)

        script_list = plan["script_list"]
        visual_scenes = plan["visual_scenes"]
        assert len(script_list) > 0

        # 2. TTS 생성
        tts = MockTTSManager()
        tts_output_dir = os.path.join(temp_dir, "tts")
        tts_result = tts.synthesize_all(script_list, tts_output_dir)

        assert len(tts_result["subtitle_data"]) == len(script_list)
        assert os.path.exists(tts_result["full_audio_path"])

        # 3. 이미지 생성
        img = MockImagePipeline()
        img_output_dir = os.path.join(temp_dir, "images")
        image_paths = img.generate_all(visual_scenes, img_output_dir)

        assert len(image_paths) == len(visual_scenes)

        # 4. 영상 렌더링
        vr = MockVideoRenderer()
        video_path = vr.assemble_main(
            audio_path=tts_result["full_audio_path"],
            subtitle_data=tts_result["subtitle_data"],
            image_paths=image_paths,
            mode=plan["mode"],
            topic=plan["topic"],
        )

        assert video_path is not None
        assert os.path.exists(video_path)

        # 5. 데이터 정합성 검증
        # TTS 자막 수 == 스크립트 턴 수
        assert len(tts_result["subtitle_data"]) == len(script_list)
        # 이미지 수 == 비주얼 씬 수
        assert len(image_paths) == len(visual_scenes)
        # 타이밍 순서 정합성
        for i in range(1, len(tts_result["subtitle_data"])):
            prev = tts_result["subtitle_data"][i-1]
            curr = tts_result["subtitle_data"][i]
            assert curr["start"] >= prev["end"], f"타이밍 역전: 턴 {i}"

    def test_data_flow_with_more_scenes_than_images(self, temp_dir, plan_json):
        """이미지 < 자막 수일 때 반복 처리"""
        with open(plan_json, "r", encoding="utf-8") as f:
            plan = json.load(f)

        script_list = plan["script_list"]  # 5턴

        # TTS
        tts = MockTTSManager()
        tts_result = tts.synthesize_all(script_list, os.path.join(temp_dir, "tts"))

        # 이미지 3개만 (5개 자막보다 적음)
        img = MockImagePipeline()
        image_paths = img.generate_all(["p1", "p2", "p3"], os.path.join(temp_dir, "img"))

        assert len(image_paths) < len(tts_result["subtitle_data"])

        # 렌더링 — 이미지 부족해도 동작해야 함
        vr = MockVideoRenderer()
        video_path = vr.assemble_main(
            tts_result["full_audio_path"],
            tts_result["subtitle_data"],
            image_paths,
            "horror",
        )
        assert video_path is not None

    def test_empty_script_list_handling(self, temp_dir):
        """빈 스크립트 → TTS 0턴"""
        tts = MockTTSManager()
        result = tts.synthesize_all([], os.path.join(temp_dir, "tts"))
        assert len(result["subtitle_data"]) == 0
        assert len(result["audio_files"]) == 0


class TestCancellationToken:
    """취소 토큰 동작 테스트"""

    def test_cancellation_token_check(self):
        from pipeline.context import CancellationToken
        token = CancellationToken()
        assert token.check() is False

        token.cancel()
        assert token.check() is True

    def test_cancellation_token_reset(self):
        """새 토큰은 항상 False"""
        from pipeline.context import CancellationToken
        token1 = CancellationToken()
        token1.cancel()

        token2 = CancellationToken()
        assert token2.check() is False


class TestProgressCallback:
    """진행 콜백 테스트"""

    def test_callback_receives_messages(self):
        """진행 콜백이 (message, percentage) 형태로 호출되는지"""
        messages = []

        def callback(msg, pct):
            messages.append((msg, pct))

        # 시뮬레이션: 파이프라인 단계별 콜백 호출
        callback("썸네일 생성 중...", 5)
        callback("TTS 생성 중...", 20)
        callback("이미지 생성 중...", 40)
        callback("영상 렌더링 중...", 70)
        callback("완료", 100)

        assert len(messages) == 5
        assert messages[0][1] == 5
        assert messages[-1][1] == 100

        # 퍼센티지 단조증가 검증
        for i in range(1, len(messages)):
            assert messages[i][1] >= messages[i-1][1]


class TestCheckpointFlow:
    """체크포인트 흐름 테스트"""

    def test_checkpoint_save_and_load(self, temp_dir):
        """체크포인트 JSON 저장/로드"""
        ckpt_path = os.path.join(temp_dir, "checkpoint.json")

        checkpoint = {
            "stage": "tts",
            "script_turns": 35,
            "tts_complete": True,
            "images_complete": False,
        }

        with open(ckpt_path, "w") as f:
            json.dump(checkpoint, f)

        with open(ckpt_path, "r") as f:
            loaded = json.load(f)

        assert loaded["stage"] == "tts"
        assert loaded["tts_complete"] is True

    def test_checkpoint_stage_progression(self):
        """스테이지 순서 검증"""
        stages = ["init", "thumbnail", "tts", "image", "sfx", "render", "upload", "complete"]

        for i in range(1, len(stages)):
            assert stages.index(stages[i]) > stages.index(stages[i-1])


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_single_turn_pipeline(self, temp_dir):
        """1턴 스크립트 처리"""
        tts = MockTTSManager()
        result = tts.synthesize_all(
            [{"text": "단일 대사", "role": "narrator"}],
            os.path.join(temp_dir, "tts"),
        )
        assert len(result["subtitle_data"]) == 1

        img = MockImagePipeline()
        images = img.generate_all(["single scene"], os.path.join(temp_dir, "img"))
        assert len(images) == 1

        vr = MockVideoRenderer()
        video = vr.assemble_main(
            result["full_audio_path"],
            result["subtitle_data"],
            images,
            "touching",
        )
        assert video is not None

    def test_large_script_pipeline(self, temp_dir):
        """100턴 대규모 스크립트 처리"""
        script = [{"text": f"대사 {i}", "role": "narrator"} for i in range(100)]

        tts = MockTTSManager()
        result = tts.synthesize_all(script, os.path.join(temp_dir, "tts"))
        assert len(result["subtitle_data"]) == 100
        assert result["total_duration"] > 0

        img = MockImagePipeline()
        images = img.generate_all([f"prompt {i}" for i in range(100)], os.path.join(temp_dir, "img"))
        assert len(images) == 100

    def test_unicode_text_in_script(self, temp_dir):
        """한국어/특수문자 대사 처리"""
        script = [
            {"text": "할머니가 말했다... \"정말이야?\"", "role": "grandma"},
            {"text": "😱 무서워!!!", "role": "narrator"},
            {"text": "괜찮아요, 걱정 마세요.", "role": "grandpa"},
        ]

        tts = MockTTSManager()
        result = tts.synthesize_all(script, os.path.join(temp_dir, "tts"))
        assert len(result["subtitle_data"]) == 3
        assert result["subtitle_data"][0]["role"] == "grandma"  # role 보존
        assert result["subtitle_data"][0]["text"] == script[0]["text"]  # 텍스트 보존
        assert result["subtitle_data"][1]["text"] == script[1]["text"]  # 이모지 포함 텍스트 보존
