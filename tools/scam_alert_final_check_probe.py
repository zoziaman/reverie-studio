from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import ACTIVE_PACK, load_pack_by_id, resolve_motiontoon_runtime_config
from modules_pro.remotion_assembler import RemotionAssembler
from modules_pro.scene_analyzer import CharacterState, SceneAnalysisResult
from pipeline.image_pipeline import ImagePipeline
from utils.runtime_utils import (
    ensure_channel_temp_project_dir,
    ensure_probe_output_dir,
    relocate_generated_image_dir,
)


PROJECT_NAME = "Senior_scam_alert_final_check_v1"
OUTPUT_STEM = "scam_alert_final_check_v1"


def _scene(
    index: int,
    *,
    location: str,
    location_detail: str,
    time_of_day: str,
    atmosphere: str,
    char_id: str,
    emotion: str,
    action: str,
    sd_prompt: str,
) -> SceneAnalysisResult:
    result = SceneAnalysisResult(
        scene_id=f"scene_{index:04d}",
        dialogue_index=index,
        speaker=char_id,
        location=location,
        location_detail=location_detail,
        time_of_day=time_of_day,
        atmosphere=atmosphere,
        sd_prompt=sd_prompt,
        image_action="new",
    )
    result.characters.append(
        CharacterState(
            id=char_id,
            name=char_id,
            emotion=emotion,
            action=action,
        )
    )
    return result


def build_script_list() -> list[dict]:
    return [
        {
            "role": "직원",
            "character": "young_woman",
            "voice_type": "young_woman",
            "text": "점장님 이름으로 온 문자에는 약국 금고 비밀번호를 바로 바꾸라는 지시가 적혀 있었다.",
            "emotion": "worried",
        },
        {
            "role": "기사",
            "character": "young_man",
            "voice_type": "young_man",
            "text": "서류 봉투를 건네받은 남자는 송금 확인증이 진짜인지 한 번만 더 보자고 했다.",
            "emotion": "calm",
        },
        {
            "role": "어머니",
            "character": "grandma",
            "voice_type": "grandma",
            "text": "엄마는 모르는 번호로 걸려 온 전화를 받고도 아들 부탁인 줄 알고 끝까지 끊지 못했다.",
            "emotion": "sad",
        },
        {
            "role": "직원",
            "character": "young_woman",
            "voice_type": "young_woman",
            "text": "은행 창구 앞에서야 위임장 뒷장에 붙은 이름이 점장님 필체가 아니라는 걸 알았다.",
            "emotion": "fear",
        },
        {
            "role": "기사",
            "character": "young_man",
            "voice_type": "young_man",
            "text": "골목 CCTV 시간을 맞춰 보니 문자 받은 시각과 카드 결제 시각이 정확히 겹쳤다.",
            "emotion": "desperate",
        },
        {
            "role": "직원",
            "character": "young_woman",
            "voice_type": "young_woman",
            "text": "지하철 안에서 다시 열어 본 메신저 대화에는 계좌번호만 남고 점장님 말투는 없었다.",
            "emotion": "worried",
        },
        {
            "role": "어머니",
            "character": "grandma",
            "voice_type": "grandma",
            "text": "식탁 위 송금 영수증을 내려다보던 엄마는 그 종이가 가족을 믿은 대가였다고 중얼거렸다.",
            "emotion": "sad",
        },
        {
            "role": "기사",
            "character": "young_man",
            "voice_type": "young_man",
            "text": "작은 가게 카운터 밑에서 찾은 계약서는 이 모든 연락이 사기단의 역할극이었다는 증거가 됐다.",
            "emotion": "anger",
        },
    ]


def build_scene_cache() -> dict[int, SceneAnalysisResult]:
    return {
        0: _scene(
            0,
            location="약국",
            location_detail="카운터 앞",
            time_of_day="낮",
            atmosphere="tense",
            char_id="young_woman",
            emotion="worried",
            action="standing",
            sd_prompt="realistic small korean pharmacy interior, medicine shelves, clean counter, empty background plate, no people, no mascot, no robot, no appliance face, no toy, no chibi",
        ),
        1: _scene(
            1,
            location="사무실",
            location_detail="책상 앞",
            time_of_day="낮",
            atmosphere="tense",
            char_id="young_man",
            emotion="calm",
            action="standing",
            sd_prompt="realistic small office desk area, paperwork and computer monitor, empty background plate, no people, no mascot, no robot, no toy",
        ),
        2: _scene(
            2,
            location="집",
            location_detail="거실 식탁",
            time_of_day="밤",
            atmosphere="sad",
            char_id="grandma",
            emotion="sad",
            action="sitting",
            sd_prompt="realistic modest korean apartment living room, sofa and table, empty background plate, no people, no mascot, no robot, no doll",
        ),
        3: _scene(
            3,
            location="은행",
            location_detail="상담 창구",
            time_of_day="낮",
            atmosphere="fear",
            char_id="young_woman",
            emotion="fear",
            action="standing",
            sd_prompt="realistic korean bank consultation desk and waiting chairs, empty background plate, no people, no mascot, no robot, no cartoon object",
        ),
        4: _scene(
            4,
            location="골목",
            location_detail="주택가 골목",
            time_of_day="밤",
            atmosphere="tense",
            char_id="young_man",
            emotion="desperate",
            action="walking",
            sd_prompt="quiet korean residential alley at night, empty background plate, no people, no mascot, no robot, no toy",
        ),
        5: _scene(
            5,
            location="지하철",
            location_detail="전동차 안",
            time_of_day="밤",
            atmosphere="tense",
            char_id="young_woman",
            emotion="worried",
            action="standing",
            sd_prompt="realistic korean subway interior, empty background plate, no people, no mascot, no robot, no cartoon object",
        ),
        6: _scene(
            6,
            location="집",
            location_detail="식탁 앞",
            time_of_day="밤",
            atmosphere="sad",
            char_id="grandma",
            emotion="sad",
            action="sitting",
            sd_prompt="realistic modest korean apartment dining area, empty background plate, no people, no mascot, no robot, no doll",
        ),
        7: _scene(
            7,
            location="가게",
            location_detail="카운터 안쪽",
            time_of_day="밤",
            atmosphere="tense",
            char_id="young_man",
            emotion="anger",
            action="standing",
            sd_prompt="realistic small korean shop counter interior, shelves and register, empty background plate, no people, no mascot, no robot, no toy",
        ),
    }


def generate_images() -> tuple[Path, Path]:
    load_pack_by_id("senior_scam_alert")
    channel_name = getattr(ACTIVE_PACK, "pack_name", "사기 경보 드라마 채널")

    image_dir = ensure_channel_temp_project_dir(channel_name, PROJECT_NAME)
    if image_dir.exists():
        shutil.rmtree(image_dir)

    pipeline = ImagePipeline(
        channel=channel_name,
        mode="scam_alert",
        sd_url="http://127.0.0.1:7860",
        sd_webui_root=r"C:\AI\webui",
        data_dir=str(ROOT / "data"),
        assets_dir=str(ROOT / "assets"),
        video_width=1920,
        video_height=1080,
    )
    script_list = build_script_list()
    scene_cache = build_scene_cache()
    image_paths = pipeline.generate_images_v59(
        script_list=script_list,
        project_name=PROJECT_NAME,
        mode="scam_alert",
        scene_analysis_cache=scene_cache,
    )
    image_dir = relocate_generated_image_dir(image_paths, image_dir)
    image_paths = [str(image_dir / Path(path).name) for path in image_paths]

    json_path = ROOT / "data" / "scripts" / f"{PROJECT_NAME}.json"
    payload = {
        "project_name": PROJECT_NAME,
        "category": "senior",
        "mode": "scam_alert",
        "script_list": script_list,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    output_dir = ensure_probe_output_dir(PROJECT_NAME)
    summary_path = output_dir / f"{OUTPUT_STEM}_images_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "project_name": PROJECT_NAME,
                "images": image_paths,
                "json_path": str(json_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return json_path, image_dir


def render_probe(json_path: Path, image_dir: Path) -> Path:
    load_pack_by_id("senior_scam_alert")

    assembler = RemotionAssembler(channel="senior")
    motiontoon_config, _ = resolve_motiontoon_runtime_config(
        render_mode_override="gishini_motiontoon",
        motiontoon=getattr(ACTIVE_PACK, "motiontoon", None),
    )
    assembler.set_motiontoon_config(motiontoon_config)
    assembler.set_visual_effects(getattr(ACTIVE_PACK, "visual_effects", None))
    assembler.set_subtitle_style(getattr(ACTIVE_PACK, "subtitle_style", None))

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    script_list = payload["script_list"]
    for idx, item in enumerate(script_list):
        scene_name = f"scene_{idx:04d}.png"
        candidates = [
            image_dir / scene_name,
            image_dir / "_motiontoon" / scene_name,
            image_dir / "_motiontoon" / "_motiontoon" / scene_name,
        ]
        image_path = next((path for path in candidates if path.exists()), None)
        if image_path is None:
            raise FileNotFoundError(f"Missing scene image for render probe: {scene_name}")
        assembler.add_scene(
            image_path=str(image_path),
            audio_path="",
            text=str(item["text"]),
            speaker=str(item["role"]),
            duration_ms=1500,
            voice_type=str(item.get("voice_type") or ""),
        )

    output_dir = ensure_probe_output_dir(PROJECT_NAME)
    output_path = output_dir / f"{OUTPUT_STEM}_motiontoon.mp4"
    assembler.render(str(output_path))
    return output_path


def main() -> None:
    json_path, image_dir = generate_images()
    video_path = render_probe(json_path, image_dir)
    print(
        json.dumps(
            {
                "json_path": str(json_path),
                "image_dir": str(image_dir),
                "video_path": str(video_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
