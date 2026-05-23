import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTOR_DIR = ROOT / "assets" / "actor_models" / "actor_adult_woman_01"
SCHEMA_PATH = ROOT / "schemas" / "video_toon_actor_model.schema.json"
DOC_PATH = ROOT / "docs" / "ACTOR_MODEL_TEMPLATE.md"


def test_actor_model_template_public_safe_package_exists():
    actor_path = ACTOR_DIR / "actor.json"
    assert actor_path.exists()

    actor = json.loads(actor_path.read_text(encoding="utf-8"))
    assert actor["actor_id"] == "actor_adult_woman_01"
    assert actor["readiness_state"] == "template"
    assert actor["template_version"] == "actor_model_template_v1"
    assert actor["identity_lock"]["must_not_change"]
    assert actor["required_variants"]
    assert actor["mouth_shapes"]
    assert actor["eye_shapes"]

    public_boundary = actor["public_release_boundary"]
    assert public_boundary["contains_real_actor_media"] is False
    assert public_boundary["contains_voice_samples"] is False
    assert public_boundary["contains_model_weights"] is False
    assert public_boundary["contains_private_paths"] is False

    for relative_path in (
        "prompts/identity_prompt.txt",
        "prompts/variant_prompt.txt",
        "prompts/mouth_prompt.txt",
        "prompts/negative_prompt.txt",
        "references/README.md",
        "references/.gitkeep",
        "variants/.gitkeep",
        "face_parts/.gitkeep",
        "qa/actor_model_checklist.md",
    ):
        assert (ACTOR_DIR / relative_path).exists()

    forbidden_suffixes = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".wav",
        ".mp3",
        ".flac",
        ".mp4",
        ".mov",
        ".safetensors",
        ".ckpt",
        ".pt",
        ".pth",
        ".onnx",
        ".pickle",
        ".pkl",
    }
    forbidden_files = [
        path.relative_to(ROOT)
        for path in ACTOR_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]
    assert forbidden_files == []


def test_actor_model_schema_documents_required_fields():
    assert SCHEMA_PATH.exists()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    required = set(schema["required"])
    assert {
        "actor_id",
        "template_version",
        "readiness_state",
        "identity_lock",
        "required_variants",
        "mouth_shapes",
        "eye_shapes",
        "public_release_boundary",
    }.issubset(required)

    readiness_enum = schema["properties"]["readiness_state"]["enum"]
    assert readiness_enum == ["template", "draft", "ready_for_test", "approved", "retired"]


def test_actor_model_template_doc_matches_actor_pool_direction():
    assert DOC_PATH.exists()
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "actor_adult_woman_01" in text
    assert "actor_model_path" in text
    assert "docs/VIDEO_TOON_ACTOR_POOL_CONTRACT.md" in text
    assert "public-safe" in text
