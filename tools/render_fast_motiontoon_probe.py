import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from modules_pro.remotion_assembler import RemotionAssembler
from config.pack_config import ACTIVE_PACK, load_pack_by_id, resolve_motiontoon_runtime_config
from modules_pro.visual_director import VisualDirector
from utils.layered_cutout import load_layered_cutout_metadata
from utils.motiontoon import build_scene_motion_directive


def _safe_pack_id(category: str, mode: str) -> str:
    if category == "senior" and mode in {"touching", "makjang", "life_saguk", "scam_alert"}:
        return f"senior_{mode}"
    if category == "horror":
        return "horror_v59"
    return f"{category}_{mode}"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _build_probe(
    json_path: Path,
    image_dir: Path,
    output_path: Path,
    scenes: int,
    scene_duration_ms: int,
    start_index: int = 0,
    render_mode: str | None = None,
) -> dict:
    payload = _load_json(json_path)
    category = str(payload.get("category") or "senior")
    mode = str(payload.get("mode") or "touching")
    script_list = payload.get("script_list") or []

    pack_id = _safe_pack_id(category, mode)
    load_pack_by_id(pack_id)

    assembler = RemotionAssembler(channel=category)
    storytelling_director = None
    if getattr(ACTIVE_PACK, "is_loaded", False):
        motiontoon_config, support = resolve_motiontoon_runtime_config(
            render_mode_override=render_mode,
            motiontoon=getattr(ACTIVE_PACK, "motiontoon", None),
        )
        assembler.set_motiontoon_config(motiontoon_config)
        assembler.set_visual_effects(getattr(ACTIVE_PACK, "visual_effects", None))
        assembler.set_subtitle_style(getattr(ACTIVE_PACK, "subtitle_style", None))
        if support.get("effective_mode") == "gishini_motiontoon":
            visual_director = VisualDirector()
            components = visual_director.init_v59_pipeline(
                pack_id=pack_id,
                genre=str(getattr(ACTIVE_PACK, "genre", category) or category),
                sd_api=None,
                gemini_client=None,
            )
            storytelling_director = components.get("storytelling_director")
            if storytelling_director and getattr(storytelling_director, "scene_analyzer", None):
                storytelling_director._build_dynamic_character_mapping(script_list)
    else:
        support = {"effective_mode": render_mode or "classic_dynamic", "requested_mode": render_mode or "classic_dynamic"}

    images = sorted(image_dir.glob("scene_*.png"))
    selected = images[start_index:start_index + scenes]
    if not selected:
        raise FileNotFoundError(f"No scene images found in {image_dir}")

    for img in selected:
        try:
            idx = int(img.stem.split("_")[-1])
        except ValueError:
            idx = 0
        item = script_list[idx] if idx < len(script_list) else {}
        text = str(item.get("text") or "")
        speaker = str(item.get("role") or item.get("character") or "narrator")
        voice_type = str(item.get("voice_type") or "")
        emotion = str(item.get("emotion") or "neutral")
        pose = str(item.get("action") or item.get("pose") or "standing")
        motion_assets = {}
        motion_data = None

        if support.get("effective_mode") == "gishini_motiontoon" and storytelling_director:
            char_id = ""
            scene_analyzer = getattr(storytelling_director, "scene_analyzer", None)
            if scene_analyzer:
                try:
                    candidate_id = str(scene_analyzer._get_character_id(speaker) or "")
                    alias_values = {str(v).lower() for v in getattr(scene_analyzer, "alias_to_id", {}).values()}
                    if candidate_id and (candidate_id in alias_values or candidate_id in {"narrator", "young_woman", "young_man", "grandma", "grandpa", "child", "man", "woman"}):
                        char_id = candidate_id
                except Exception:
                    char_id = ""

            if not char_id:
                char_id = str(item.get("character_id") or "")

            library_image = ""
            if char_id:
                try:
                    library_image = str(storytelling_director._get_from_library(char_id, emotion, pose) or "")
                except Exception:
                    library_image = ""
                if not library_image:
                    try:
                        library_image = str(storytelling_director._ensure_simple_sprite_library_image(char_id, emotion, pose) or "")
                    except Exception:
                        library_image = ""

            if library_image and Path(library_image).exists():
                try:
                    motion_assets = storytelling_director._compose_scene_motiontoon_assets(
                        str(img),
                        background_source_path=str(img),
                        sprite_source_path=library_image,
                        char_id=char_id,
                        emotion=emotion,
                        pose=pose,
                    ) or {}
                except Exception:
                    motion_assets = {}
            else:
                try:
                    motion_assets = storytelling_director._build_simple_sprite_background_only_parts(
                        str(img),
                        char_id=char_id,
                        emotion=emotion,
                        pose=pose,
                    ) or {}
                except Exception:
                    motion_assets = {}

            duration_frames = assembler._ms_to_frames(scene_duration_ms)
            motion_data = build_scene_motion_directive(
                text=text,
                speaker=speaker,
                duration_frames=duration_frames,
                config=motiontoon_config,
            )
            motion_meta = load_layered_cutout_metadata(str(img)) if motion_assets else {}
            rig = dict(motion_meta.get("rig", {}) or {}) if isinstance(motion_meta, dict) else {}
            if rig:
                motion_data.update({k: v for k, v in rig.items() if v is not None})
                motion_data["use_layered_cutout"] = True
                if motion_assets.get("foreground_path"):
                    motion_data["character_layer_mode"] = str(rig.get("character_layer_mode", "simple_sprite") or "simple_sprite")

        assembler.add_scene(
            image_path=str(img),
            audio_path="",
            text=text,
            speaker=speaker,
            duration_ms=scene_duration_ms,
            voice_type=voice_type,
            background_path=str(motion_assets.get("background_path", "") or ""),
            foreground_path=str(motion_assets.get("foreground_path", "") or ""),
            head_path=str(motion_assets.get("head_path", "") or ""),
            body_path=str(motion_assets.get("body_path", "") or ""),
            left_arm_path=str(motion_assets.get("left_arm_path", "") or ""),
            right_arm_path=str(motion_assets.get("right_arm_path", "") or ""),
            eyes_open_path=str(motion_assets.get("eyes_open_path", "") or ""),
            eyes_closed_path=str(motion_assets.get("eyes_closed_path", "") or ""),
            mouth_closed_path=str(motion_assets.get("mouth_closed_path", "") or ""),
            mouth_open_path=str(motion_assets.get("mouth_open_path", "") or ""),
            motion_data=motion_data,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    result = assembler.render(str(output_path))
    result["wall_clock_seconds"] = time.time() - started
    result["input_json"] = str(json_path)
    result["image_dir"] = str(image_dir)
    result["pack_id"] = pack_id
    result["render_mode"] = support.get("effective_mode")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a fast motiontoon probe from existing scene images.")
    parser.add_argument("--json", required=True, help="Path to existing script json")
    parser.add_argument("--images", required=True, help="Path to existing scene image directory")
    parser.add_argument("--output", required=True, help="Output mp4 path")
    parser.add_argument("--scenes", type=int, default=8, help="Number of scenes to render")
    parser.add_argument("--duration-ms", type=int, default=1500, help="Duration per scene in ms")
    parser.add_argument("--start-index", type=int, default=0, help="Start scene index")
    parser.add_argument("--render-mode", choices=["classic_dynamic", "gishini_motiontoon"], default=None)
    args = parser.parse_args()

    result = _build_probe(
        json_path=Path(args.json),
        image_dir=Path(args.images),
        output_path=Path(args.output),
        scenes=args.scenes,
        scene_duration_ms=args.duration_ms,
        start_index=args.start_index,
        render_mode=args.render_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
