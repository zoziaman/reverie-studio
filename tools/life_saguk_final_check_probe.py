from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.pack_config import load_pack_by_id
from modules_pro.scene_analyzer import CharacterState, SceneAnalysisResult
from pipeline.image_pipeline import ImagePipeline
from modules_pro.remotion_assembler import RemotionAssembler
from utils.runtime_utils import (
    ensure_channel_temp_project_dir,
    ensure_probe_output_dir,
    relocate_generated_image_dir,
)


PROJECT_NAME = "Senior_life_saguk_final_check_v2"
OUTPUT_STEM = "life_saguk_final_check_v2"
CHANNEL_NAME = "생활 사극 채널"


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
            "role": "낭자",
            "character": "young_woman",
            "voice_type": "young_woman",
            "text": "문간에 놓인 봉투가 또 젖어 있었다. 누가 다리 아래에서 올려보낸 것이었다.",
            "emotion": "worried",
        },
        {
            "role": "사내",
            "character": "young_man",
            "voice_type": "young_man",
            "text": "다리 쪽으로는 가지 마시오. 물안개가 짙으면 발밑도 속인다.",
            "emotion": "calm",
        },
        {
            "role": "훈장",
            "character": "grandpa",
            "voice_type": "grandpa",
            "text": "장터에 소문이 돌기 전에 장부부터 숨겨라. 오늘은 길목이 수상하다.",
            "emotion": "worried",
        },
        {
            "role": "할머니",
            "character": "grandma",
            "voice_type": "grandma",
            "text": "이 서찰은 서재 불빛 아래서만 읽어라. 남들 앞에서는 펼치지 마라.",
            "emotion": "sad",
        },
        {
            "role": "낭자",
            "character": "young_woman",
            "voice_type": "young_woman",
            "text": "강가까지 발자국이 이어졌어요. 그런데 돌아온 자국은 하나도 없었어요.",
            "emotion": "fear",
        },
        {
            "role": "사내",
            "character": "young_man",
            "voice_type": "young_man",
            "text": "길은 비었는데 다리 위 판자만 젖어 있었소. 누군가 방금 건넌 흔적이오.",
            "emotion": "desperate",
        },
        {
            "role": "훈장",
            "character": "grandpa",
            "voice_type": "grandpa",
            "text": "논밭 끝에서 기다리면 날이 밝기 전에 반드시 사람이 온다.",
            "emotion": "calm",
        },
        {
            "role": "할머니",
            "character": "grandma",
            "voice_type": "grandma",
            "text": "오늘 밤은 집 마당에서 문을 닫지 말거라. 돌아오는 길을 막으면 안 된다.",
            "emotion": "sad",
        },
    ]


def build_scene_cache() -> dict[int, SceneAnalysisResult]:
    return {
        0: _scene(
            0,
            location="집",
            location_detail="한옥 안채 마당",
            time_of_day="밤",
            atmosphere="tense",
            char_id="young_woman",
            emotion="worried",
            action="standing",
            sd_prompt="joseon hanok courtyard at night, empty background plate, no people",
        ),
        1: _scene(
            1,
            location="다리",
            location_detail="개울 위 나무다리",
            time_of_day="밤",
            atmosphere="tense",
            char_id="young_man",
            emotion="calm",
            action="standing",
            sd_prompt="simple wooden footbridge over stream in joseon countryside, empty background plate, no people",
        ),
        2: _scene(
            2,
            location="시장",
            location_detail="장터 골목",
            time_of_day="낮",
            atmosphere="tense",
            char_id="grandpa",
            emotion="worried",
            action="standing",
            sd_prompt="joseon market lane with empty merchant stalls, empty background plate, no people",
        ),
        3: _scene(
            3,
            location="서재",
            location_detail="글방",
            time_of_day="밤",
            atmosphere="sad",
            char_id="grandma",
            emotion="sad",
            action="sitting",
            sd_prompt="joseon study room with calligraphy desk, empty background plate, no people",
        ),
        4: _scene(
            4,
            location="강",
            location_detail="강가",
            time_of_day="밤",
            atmosphere="fear",
            char_id="young_woman",
            emotion="fear",
            action="standing",
            sd_prompt="joseon riverside with mist over water, empty background plate, no people",
        ),
        5: _scene(
            5,
            location="길",
            location_detail="마을길",
            time_of_day="밤",
            atmosphere="desperate",
            char_id="young_man",
            emotion="desperate",
            action="walking",
            sd_prompt="joseon dirt lane between stone walls, empty background plate, no people",
        ),
        6: _scene(
            6,
            location="논밭",
            location_detail="논두렁",
            time_of_day="새벽",
            atmosphere="calm",
            char_id="grandpa",
            emotion="calm",
            action="standing",
            sd_prompt="joseon rice field and farm path, empty background plate, no people",
        ),
        7: _scene(
            7,
            location="집",
            location_detail="한옥 마당",
            time_of_day="밤",
            atmosphere="sad",
            char_id="grandma",
            emotion="sad",
            action="standing",
            sd_prompt="joseon hanok courtyard at night, empty background plate, no people",
        ),
    }


def copy_probe_backgrounds() -> None:
    src_dir = ROOT / "assets" / "backgrounds" / "life_saguk_probe_v2"
    dst_dir = ROOT / "assets" / "backgrounds" / CHANNEL_NAME
    dst_dir.mkdir(parents=True, exist_ok=True)
    for path in src_dir.glob("*_any_00.png"):
        shutil.copy2(path, dst_dir / path.name)
    index_path = src_dir / "background_index.json"
    if index_path.exists():
        shutil.copy2(index_path, dst_dir / index_path.name)


def generate_images() -> tuple[Path, Path]:
    load_pack_by_id("senior_life_saguk")
    copy_probe_backgrounds()

    image_dir = ensure_channel_temp_project_dir(CHANNEL_NAME, PROJECT_NAME)
    if image_dir.exists():
        shutil.rmtree(image_dir)

    pipeline = ImagePipeline(
        channel=CHANNEL_NAME,
        mode="life_saguk",
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
        mode="life_saguk",
        scene_analysis_cache=scene_cache,
    )
    image_dir = relocate_generated_image_dir(image_paths, image_dir)
    image_paths = [str(image_dir / Path(path).name) for path in image_paths]

    json_path = ROOT / "data" / "scripts" / f"{PROJECT_NAME}.json"
    payload = {
        "project_name": PROJECT_NAME,
        "category": "senior",
        "mode": "life_saguk",
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
    load_pack_by_id("senior_life_saguk")

    assembler = RemotionAssembler(channel="senior")
    from config.pack_config import ACTIVE_PACK, resolve_motiontoon_runtime_config

    motiontoon_config, _ = resolve_motiontoon_runtime_config(
        render_mode_override="gishini_motiontoon",
        motiontoon=getattr(ACTIVE_PACK, "motiontoon", None),
    )
    assembler.set_motiontoon_config(motiontoon_config)
    assembler.set_visual_effects(getattr(ACTIVE_PACK, "visual_effects", None))
    assembler.set_subtitle_style(getattr(ACTIVE_PACK, "subtitle_style", None))

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    script_list = payload["script_list"]
    for idx, image_path in enumerate(sorted(image_dir.glob("scene_*.png"))[:8]):
        item = script_list[idx]
        assembler.add_scene(
            image_path=str(image_path),
            audio_path="",
            text=item["text"],
            speaker=item["role"],
            duration_ms=1500,
            voice_type=item.get("voice_type", ""),
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
