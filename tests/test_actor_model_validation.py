import importlib
import json
import shutil
import tomllib
from pathlib import Path

import pytest

from config.pack_validator import PackValidator


ROOT = Path(__file__).resolve().parents[1]
ACTOR_MODEL_PATH = ROOT / "assets" / "actor_models" / "actor_adult_woman_01" / "actor.json"
ACTOR_PRESET_CATALOG_PATH = ROOT / "assets" / "actor_model_presets" / "catalog.json"
ACTOR_POOL_SCHEMA_PATH = ROOT / "schemas" / "video_toon_actor_pool.schema.json"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def _actor_model_module():
    try:
        return importlib.import_module("utils.actor_model")
    except ModuleNotFoundError as exc:
        pytest.fail(f"utils.actor_model module is required for actor model package validation: {exc}")


def _base_settings(actor_pool):
    return {
        "visual_storytelling": {"enabled": False},
        "tts": {"character_mapping": {"narrator": "narrator_female"}},
        "sd": {"positive": "test"},
        "visual": {"safe_fallbacks": ["fallback"]},
        "motiontoon": {
            "enabled": True,
            "video_toon_local_enabled": True,
            "video_toon_generation_backend": "comfyui",
            "video_toon_workflow_template": "layered_actor_pool_v1",
            "actor_pool": actor_pool,
            "cast_slots": {
                "lead": {"actor_id": next(iter(actor_pool.keys()))},
            },
        },
    }


def test_validate_actor_model_package_accepts_public_safe_template():
    actor_model = _actor_model_module()

    result = actor_model.validate_actor_model_package(ACTOR_MODEL_PATH, repo_root=ROOT)

    assert result.is_valid is True
    assert result.errors == []
    assert result.actor_id == "actor_adult_woman_01"
    assert "neutral_standing" in result.required_variants


def test_pack_validator_accepts_actor_model_path_when_contract_matches():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_adult_woman_01": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "adult Korean woman reusable video-toon actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing", "talking_standing"],
                }
            }
        )
    )

    assert result.is_valid is True
    assert result.errors == []


def test_pack_validator_rejects_actor_model_path_actor_id_mismatch():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_other_99": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "mismatched reusable actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert any("actor_id" in error and "actor_other_99" in error for error in result.errors)


def test_pack_validator_default_repo_root_validates_actor_model_path():
    validator = PackValidator()

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_other_99": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "mismatched reusable actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert not any("repo_root is unavailable" in warning for warning in result.warnings)
    assert any("actor_id" in error and "actor_other_99" in error for error in result.errors)


def test_pack_validator_rejects_required_variant_missing_from_actor_model():
    validator = PackValidator(repo_root=ROOT)

    result = validator.validate_settings(
        _base_settings(
            {
                "actor_adult_woman_01": {
                    "actor_model_path": "assets/actor_models/actor_adult_woman_01/actor.json",
                    "visual_identity": "adult Korean woman reusable video-toon actor",
                    "voice_profile": "female_01",
                    "required_variants": ["neutral_standing", "impossible_pose"],
                }
            }
        )
    )

    assert result.is_valid is False
    assert any("impossible_pose" in error and "actor_model" in error for error in result.errors)


def test_actor_pool_schema_documents_actor_model_path():
    schema = json.loads(ACTOR_POOL_SCHEMA_PATH.read_text(encoding="utf-8"))

    actor_properties = schema["additionalProperties"]["properties"]

    assert actor_properties["actor_model_path"]["type"] == "string"
    assert actor_properties["actor_model_path"]["minLength"] == 1


def test_build_actor_asset_request_manifest_expands_variants_and_face_parts():
    actor_model = _actor_model_module()
    actor = json.loads(ACTOR_MODEL_PATH.read_text(encoding="utf-8"))

    manifest = actor_model.build_actor_asset_request_manifest(ACTOR_MODEL_PATH, repo_root=ROOT)
    requests = manifest["requests"]
    variants = [request for request in requests if request["request_type"] == "variant"]
    mouths = [request for request in requests if request["request_type"] == "mouth_shape"]
    eyes = [request for request in requests if request["request_type"] == "eye_shape"]

    assert manifest["schema"] == "reverie.actor_model.asset_requests.v1"
    assert manifest["actor_id"] == "actor_adult_woman_01"
    assert manifest["source_actor_model_path"] == "assets/actor_models/actor_adult_woman_01/actor.json"
    assert len(variants) == len(actor["required_variants"])
    assert len(mouths) == len(actor["mouth_shapes"])
    assert len(eyes) == len(actor["eye_shapes"])
    assert variants[0]["request_id"] == "actor_adult_woman_01__variant__neutral_standing"
    assert variants[0]["target_relative_path"] == "variants/neutral_standing.png"
    assert "actor_adult_woman_01" in variants[0]["prompt"]
    assert "neutral_standing" in variants[0]["prompt"]
    assert "identity drift" in variants[0]["negative_prompt"]
    assert mouths[0]["target_relative_path"].startswith("face_parts/")
    assert eyes[0]["target_relative_path"].startswith("face_parts/")
    assert all(request["public_safe"] is True for request in requests)


def test_write_actor_asset_request_manifest_creates_json(tmp_path):
    actor_model = _actor_model_module()
    output_path = tmp_path / "actor_adult_woman_01.asset_requests.json"

    written_path = actor_model.write_actor_asset_request_manifest(
        ACTOR_MODEL_PATH,
        output_path,
        repo_root=ROOT,
    )
    manifest = json.loads(output_path.read_text(encoding="utf-8"))

    assert written_path == output_path
    assert manifest["actor_id"] == "actor_adult_woman_01"
    assert manifest["requests"]
    private_path_prefix = "C:" + "/Users/"
    assert not any(private_path_prefix in json.dumps(request) for request in manifest["requests"])


def test_actor_asset_request_manifest_without_repo_root_avoids_private_paths():
    actor_model = _actor_model_module()

    manifest = actor_model.build_actor_asset_request_manifest(ACTOR_MODEL_PATH)
    serialized = json.dumps(manifest)
    private_path_prefixes = ("C:" + "/Users/", "C:" + "\\Users\\")

    assert all(prefix not in serialized for prefix in private_path_prefixes)


def test_actor_model_cli_writes_asset_request_manifest(tmp_path, capsys):
    actor_model = _actor_model_module()
    output_path = tmp_path / "requests.json"

    exit_code = actor_model.main(
        [
            "asset-requests",
            str(ACTOR_MODEL_PATH),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert output_path.exists()
    assert "actor_adult_woman_01" in captured.out


def test_pyproject_exposes_actor_model_request_cli():
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    scripts = pyproject["project"]["scripts"]

    assert scripts["reverie-actor-model-requests"] == "utils.actor_model:main"


def test_actor_asset_coverage_report_flags_missing_public_template_assets():
    actor_model = _actor_model_module()

    report = actor_model.build_actor_asset_coverage_report(ACTOR_MODEL_PATH, repo_root=ROOT)

    assert report["schema"] == "reverie.actor_model.asset_coverage.v1"
    assert report["actor_id"] == "actor_adult_woman_01"
    assert report["expected_count"] == 18
    assert report["existing_count"] == 0
    assert report["missing_count"] == 18
    assert report["ready_for_local_test"] is False
    assert "variants/neutral_standing.png" in report["missing_assets"]


def test_actor_asset_coverage_report_accepts_local_generated_assets(tmp_path):
    actor_model = _actor_model_module()
    actor_dir = tmp_path / "actor_adult_woman_01"
    shutil.copytree(ACTOR_MODEL_PATH.parent, actor_dir)

    request_manifest = actor_model.build_actor_asset_request_manifest(actor_dir / "actor.json")
    for request in request_manifest["requests"]:
        target = actor_dir / request["target_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"local placeholder asset")

    report = actor_model.build_actor_asset_coverage_report(actor_dir / "actor.json")

    assert report["existing_count"] == report["expected_count"]
    assert report["missing_count"] == 0
    assert report["coverage_ratio"] == 1.0
    assert report["ready_for_local_test"] is True


def test_actor_model_cli_writes_coverage_report_and_can_fail_on_missing(tmp_path, capsys):
    actor_model = _actor_model_module()
    output_path = tmp_path / "coverage.json"

    exit_code = actor_model.main(
        [
            "coverage",
            str(ACTOR_MODEL_PATH),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output_path),
        ]
    )
    fail_code = actor_model.main(
        [
            "coverage",
            str(ACTOR_MODEL_PATH),
            "--repo-root",
            str(ROOT),
            "--fail-on-missing",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert fail_code == 1
    assert report["missing_count"] == 18
    assert "missing 18/18" in captured.out


def test_pack_actor_asset_coverage_report_summarizes_actor_model_paths():
    actor_model = _actor_model_module()
    settings_path = ROOT / "assets" / "packs" / "daily_life_toon" / "settings.json"

    report = actor_model.build_pack_actor_asset_coverage_report(settings_path, repo_root=ROOT)

    assert report["schema"] == "reverie.pack.actor_asset_coverage.v1"
    assert report["pack_settings_path"] == "assets/packs/daily_life_toon/settings.json"
    assert report["actor_model_count"] >= 1
    assert report["expected_count"] >= 18
    assert report["missing_count"] >= 18
    assert report["ready_for_local_test"] is False
    assert report["actors"]["actor_adult_woman_01"]["missing_count"] == 18


def test_pack_actor_asset_coverage_report_rejects_unknown_actor_model_path(tmp_path):
    actor_model = _actor_model_module()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "motiontoon": {
                    "actor_pool": {
                        "actor_missing_01": {
                            "visual_identity": "missing actor",
                            "actor_model_path": "assets/actor_models/actor_missing_01/actor.json",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = actor_model.build_pack_actor_asset_coverage_report(settings_path, repo_root=ROOT)

    assert report["ready_for_local_test"] is False
    assert report["actors"]["actor_missing_01"]["is_valid"] is False
    assert "does not exist" in report["actors"]["actor_missing_01"]["errors"][0]


def test_actor_model_cli_writes_pack_coverage_report(tmp_path, capsys):
    actor_model = _actor_model_module()
    settings_path = ROOT / "assets" / "packs" / "daily_life_toon" / "settings.json"
    output_path = tmp_path / "daily_life_toon.actor_coverage.json"

    exit_code = actor_model.main(
        [
            "pack-coverage",
            str(settings_path),
            "--repo-root",
            str(ROOT),
            "--output",
            str(output_path),
        ]
    )
    fail_code = actor_model.main(
        [
            "pack-coverage",
            str(settings_path),
            "--repo-root",
            str(ROOT),
            "--fail-on-missing",
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert fail_code == 1
    assert report["actors"]["actor_adult_woman_01"]["missing_count"] == 18
    assert "daily_life_toon" in captured.out


def test_pack_coverage_fail_on_missing_rejects_pack_without_actor_models(tmp_path):
    actor_model = _actor_model_module()
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"motiontoon": {"actor_pool": {"legacy_actor": {"visual_identity": "legacy only"}}}}),
        encoding="utf-8",
    )

    fail_code = actor_model.main(
        [
            "pack-coverage",
            str(settings_path),
            "--repo-root",
            str(ROOT),
            "--fail-on-missing",
        ]
    )

    assert fail_code == 1


def test_scaffold_actor_model_creates_public_safe_actor_package(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"

    actor_path = actor_model.scaffold_actor_model(
        "actor_middle_man_01",
        actor_root=actor_root,
        display_name="Middle Man Actor 01",
        age_band="middle_aged",
        gender_presentation="man",
        role_range=["lead", "support", "suspect", "witness"],
        visual_identity="middle-aged Korean man with a practical jacket and calm expression",
    )

    actor = json.loads(actor_path.read_text(encoding="utf-8"))
    result = actor_model.validate_actor_model_package(actor_path)
    forbidden_media = [
        path
        for path in actor_path.parent.rglob("*")
        if path.is_file() and path.suffix.lower() in actor_model.FORBIDDEN_PUBLIC_SUFFIXES
    ]

    assert actor_path == actor_root / "actor_middle_man_01" / "actor.json"
    assert actor["actor_id"] == "actor_middle_man_01"
    assert actor["display_name"] == "Middle Man Actor 01"
    assert actor["template_version"] == "actor_model_template_v1"
    assert actor["readiness_state"] == "template"
    assert actor["age_band"] == "middle_aged"
    assert actor["gender_presentation"] == "man"
    assert actor["role_range"] == ["lead", "support", "suspect", "witness"]
    assert actor["identity_lock"]["must_not_change"]
    assert actor["required_variants"]
    assert actor["mouth_shapes"]
    assert actor["eye_shapes"]
    assert actor["public_release_boundary"]["contains_real_actor_media"] is False
    assert actor["public_release_boundary"]["contains_voice_samples"] is False
    assert actor["public_release_boundary"]["contains_model_weights"] is False
    assert actor["public_release_boundary"]["contains_private_paths"] is False
    assert (actor_path.parent / "prompts" / "identity_prompt.txt").exists()
    assert (actor_path.parent / "prompts" / "variant_prompt.txt").exists()
    assert (actor_path.parent / "prompts" / "mouth_prompt.txt").exists()
    assert (actor_path.parent / "prompts" / "negative_prompt.txt").exists()
    assert (actor_path.parent / "references" / "README.md").exists()
    assert (actor_path.parent / "variants" / ".gitkeep").exists()
    assert (actor_path.parent / "face_parts" / ".gitkeep").exists()
    assert (actor_path.parent / "qa" / "actor_model_checklist.md").exists()
    assert result.is_valid is True
    assert result.errors == []
    assert forbidden_media == []


def test_scaffold_actor_model_refuses_existing_package(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"

    actor_model.scaffold_actor_model("actor_middle_man_01", actor_root=actor_root)

    with pytest.raises(FileExistsError):
        actor_model.scaffold_actor_model("actor_middle_man_01", actor_root=actor_root)


def test_actor_model_cli_scaffold_creates_package(tmp_path, capsys):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"

    exit_code = actor_model.main(
        [
            "scaffold",
            "actor_middle_woman_01",
            "--actor-root",
            str(actor_root),
            "--display-name",
            "Middle Woman Actor 01",
            "--age-band",
            "middle_aged",
            "--gender-presentation",
            "woman",
            "--role-range",
            "lead,support,neighbor",
            "--visual-identity",
            "middle-aged Korean woman with short hair and a neat cardigan",
        ]
    )
    captured = capsys.readouterr()
    actor_path = actor_root / "actor_middle_woman_01" / "actor.json"
    actor = json.loads(actor_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert actor_path.exists()
    assert actor["role_range"] == ["lead", "support", "neighbor"]
    assert "actor_middle_woman_01" in captured.out


def test_actor_model_preset_catalog_is_public_safe_and_genre_ready():
    actor_model = _actor_model_module()

    catalog = actor_model.load_actor_model_preset_catalog(ACTOR_PRESET_CATALOG_PATH)
    presets = catalog["presets"]
    serialized = json.dumps(catalog)

    assert catalog["schema"] == "reverie.actor_model.presets.v1"
    assert {"daily_adult_man", "daily_middle_woman", "mystery_senior_man", "saguk_elder_woman"}.issubset(presets)
    assert "C:" + "/Users/" not in serialized
    assert "C:" + "\\Users\\" not in serialized
    for preset_id, preset in presets.items():
        assert preset_id
        assert preset["display_name"]
        assert preset["age_band"]
        assert preset["gender_presentation"]
        assert preset["genre_tags"]
        assert preset["role_range"]
        assert preset["visual_identity"]
        assert preset["voice_profile"]


def test_scaffold_actor_model_from_preset_creates_actor_package(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"

    actor_path = actor_model.scaffold_actor_model_from_preset(
        "daily_adult_man",
        "actor_daily_adult_man_01",
        actor_root=actor_root,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    actor = json.loads(actor_path.read_text(encoding="utf-8"))
    identity_prompt = (actor_path.parent / "prompts" / "identity_prompt.txt").read_text(encoding="utf-8")
    result = actor_model.validate_actor_model_package(actor_path)

    assert actor["actor_id"] == "actor_daily_adult_man_01"
    assert actor["display_name"] == "Daily Adult Man"
    assert actor["age_band"] == "adult"
    assert actor["gender_presentation"] == "man"
    assert "office_worker" in actor["role_range"]
    assert actor["voice_profile"]["recommended_slot"] == "male_01"
    assert "ordinary adult Korean man" in identity_prompt
    assert result.is_valid is True


def test_actor_model_cli_scaffold_preset_creates_package(tmp_path, capsys):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"

    exit_code = actor_model.main(
        [
            "scaffold-preset",
            "mystery_senior_man",
            "actor_mystery_senior_man_01",
            "--actor-root",
            str(actor_root),
            "--catalog",
            str(ACTOR_PRESET_CATALOG_PATH),
        ]
    )
    captured = capsys.readouterr()
    actor_path = actor_root / "actor_mystery_senior_man_01" / "actor.json"
    actor = json.loads(actor_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert actor["age_band"] == "senior"
    assert "suspect" in actor["role_range"]
    assert "mystery_senior_man" in captured.out


def test_build_pack_actor_roster_plan_maps_presets_to_actor_pool_and_casting():
    actor_model = _actor_model_module()

    plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
                "aliases": ["lead", "office_worker"],
            },
            {
                "role_id": "witness",
                "preset_id": "daily_middle_woman",
                "actor_id": "actor_daily_middle_woman_01",
            },
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )
    actor_pool = plan["motiontoon_patch"]["actor_pool"]
    cast_slots = plan["motiontoon_patch"]["cast_slots"]
    role_casting = plan["episode_cast_seed"]["role_casting"]

    assert plan["schema"] == "reverie.pack.actor_roster_plan.v1"
    assert plan["pack_id"] == "daily_life_toon"
    assert plan["role_reuse_policy"]["stable_actor_identity"] is True
    assert plan["role_reuse_policy"]["episode_roles_may_change"] is True
    assert actor_pool["actor_daily_adult_man_01"]["actor_model_path"] == (
        "assets/actor_models/actor_daily_adult_man_01/actor.json"
    )
    assert actor_pool["actor_daily_adult_man_01"]["voice_profile"] == "male_01"
    assert "neutral_standing" in actor_pool["actor_daily_adult_man_01"]["required_variants"]
    assert cast_slots["protagonist"]["actor_id"] == "actor_daily_adult_man_01"
    assert cast_slots["protagonist"]["aliases"] == ["lead", "office_worker"]
    assert role_casting["witness"] == "actor_daily_middle_woman_01"
    assert plan["public_release_boundary"]["contains_generated_media"] is False


def test_build_pack_actor_roster_plan_rejects_unknown_preset():
    actor_model = _actor_model_module()

    with pytest.raises(ValueError, match="unknown actor model preset"):
        actor_model.build_pack_actor_roster_plan(
            "daily_life_toon",
            [{"role_id": "lead", "preset_id": "missing_preset", "actor_id": "actor_missing_01"}],
            catalog_path=ACTOR_PRESET_CATALOG_PATH,
        )


def test_actor_model_cli_writes_pack_actor_roster_plan(tmp_path, capsys):
    actor_model = _actor_model_module()
    output_path = tmp_path / "daily_life_toon.actor_roster_plan.json"

    exit_code = actor_model.main(
        [
            "roster-plan",
            "daily_life_toon",
            "--assignment",
            "protagonist=daily_adult_man:actor_daily_adult_man_01",
            "--assignment",
            "witness=daily_middle_woman:actor_daily_middle_woman_01",
            "--catalog",
            str(ACTOR_PRESET_CATALOG_PATH),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    plan = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["pack_id"] == "daily_life_toon"
    assert plan["motiontoon_patch"]["cast_slots"]["protagonist"]["actor_id"] == "actor_daily_adult_man_01"
    assert "daily_life_toon" in captured.out


def test_apply_pack_actor_roster_plan_merges_motiontoon_patch_and_validates(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "assets" / "actor_models"
    for preset_id, actor_id in (
        ("daily_adult_man", "actor_daily_adult_man_01"),
        ("daily_middle_woman", "actor_daily_middle_woman_01"),
    ):
        actor_model.scaffold_actor_model_from_preset(
            preset_id,
            actor_id,
            actor_root=actor_root,
            catalog_path=ACTOR_PRESET_CATALOG_PATH,
        )
    settings = _base_settings({"actor_seed_01": {"visual_identity": "seed actor"}})
    settings["motiontoon"]["cast_slots"] = {}
    settings["motiontoon"]["actor_pool"] = {}
    settings["motiontoon"]["slow_push_enabled"] = True
    plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            },
            {
                "role_id": "witness",
                "preset_id": "daily_middle_woman",
                "actor_id": "actor_daily_middle_woman_01",
            },
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    applied = actor_model.apply_pack_actor_roster_plan(settings, plan)
    result = PackValidator(repo_root=tmp_path).validate_settings(applied)

    assert applied["motiontoon"]["slow_push_enabled"] is True
    assert applied["motiontoon"]["actor_pool"]["actor_daily_adult_man_01"]["voice_profile"] == "male_01"
    assert applied["motiontoon"]["cast_slots"]["protagonist"]["actor_id"] == "actor_daily_adult_man_01"
    assert applied["motiontoon"]["role_casting_contract"]["strict_actor_refs"] is True
    assert result.is_valid is True
    assert result.errors == []


def test_apply_pack_actor_roster_plan_refuses_conflicting_actor_by_default():
    actor_model = _actor_model_module()
    settings = _base_settings(
        {
            "actor_daily_adult_man_01": {
                "visual_identity": "existing actor",
                "voice_profile": "male_legacy",
            }
        }
    )
    plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            }
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    with pytest.raises(ValueError, match="already exists"):
        actor_model.apply_pack_actor_roster_plan(settings, plan)


def test_actor_model_cli_applies_roster_plan_to_settings_output(tmp_path, capsys):
    actor_model = _actor_model_module()
    settings_path = tmp_path / "settings.json"
    plan_path = tmp_path / "daily_life_toon.actor_roster_plan.json"
    output_path = tmp_path / "settings.with_roster.json"
    settings = _base_settings({"actor_seed_01": {"visual_identity": "seed actor"}})
    settings["motiontoon"]["cast_slots"] = {}
    settings["motiontoon"]["actor_pool"] = {}
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    actor_model.write_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            }
        ],
        plan_path,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    exit_code = actor_model.main(
        [
            "apply-roster-plan",
            str(settings_path),
            str(plan_path),
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()
    applied = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert applied["motiontoon"]["cast_slots"]["protagonist"]["actor_id"] == "actor_daily_adult_man_01"
    assert applied["motiontoon"]["actor_pool"]["actor_daily_adult_man_01"]["preset_id"] == "daily_adult_man"
    assert "settings.with_roster.json" in captured.out


def test_scaffold_actor_models_from_roster_plan_creates_all_actor_packages(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"
    plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            },
            {
                "role_id": "witness",
                "preset_id": "daily_middle_woman",
                "actor_id": "actor_daily_middle_woman_01",
            },
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    report = actor_model.scaffold_actor_models_from_roster_plan(
        plan,
        actor_root=actor_root,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    assert report["schema"] == "reverie.pack.actor_roster_scaffold.v1"
    assert report["pack_id"] == "daily_life_toon"
    assert report["created_count"] == 2
    assert report["existing_count"] == 0
    for actor_id in ("actor_daily_adult_man_01", "actor_daily_middle_woman_01"):
        actor_path = actor_root / actor_id / "actor.json"
        result = actor_model.validate_actor_model_package(actor_path)
        assert actor_path.exists()
        assert report["actors"][actor_id]["created"] is True
        assert result.is_valid is True


def test_scaffold_actor_models_from_roster_plan_refuses_existing_actor_by_default(tmp_path):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"
    plan = actor_model.build_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            }
        ],
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    actor_model.scaffold_actor_models_from_roster_plan(
        plan,
        actor_root=actor_root,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    with pytest.raises(FileExistsError):
        actor_model.scaffold_actor_models_from_roster_plan(
            plan,
            actor_root=actor_root,
            catalog_path=ACTOR_PRESET_CATALOG_PATH,
        )


def test_actor_model_cli_scaffold_roster_creates_actor_packages(tmp_path, capsys):
    actor_model = _actor_model_module()
    actor_root = tmp_path / "actor_models"
    plan_path = tmp_path / "daily_life_toon.actor_roster_plan.json"
    report_path = tmp_path / "daily_life_toon.actor_roster_scaffold.json"
    actor_model.write_pack_actor_roster_plan(
        "daily_life_toon",
        [
            {
                "role_id": "protagonist",
                "preset_id": "daily_adult_man",
                "actor_id": "actor_daily_adult_man_01",
            }
        ],
        plan_path,
        catalog_path=ACTOR_PRESET_CATALOG_PATH,
    )

    exit_code = actor_model.main(
        [
            "scaffold-roster",
            str(plan_path),
            "--actor-root",
            str(actor_root),
            "--catalog",
            str(ACTOR_PRESET_CATALOG_PATH),
            "--output",
            str(report_path),
        ]
    )
    captured = capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert (actor_root / "actor_daily_adult_man_01" / "actor.json").exists()
    assert report["created_count"] == 1
    assert "actor_roster_scaffold" in captured.out
