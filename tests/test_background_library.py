from modules_pro.background_library import BackgroundLibrary, build_background_library_config


def test_match_location_supports_life_saguk_aliases():
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path="assets/backgrounds/test_pack")

    assert bg._match_location("한옥 마당") == "집"
    assert bg._match_location("사랑방") == "집"
    assert bg._match_location("대문 앞") == "집"
    assert bg._match_location("시장 골목") == "시장"
    assert bg._match_location("장터 입구") == "시장"
    assert bg._match_location("hanok courtyard") == "집"
    assert bg._match_location("market alley") == "시장"


def test_generate_background_library_normalizes_requested_locations(tmp_path):
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path=str(tmp_path))

    captured = []

    def fake_generate_single_background(sd_api, prompt, negative_prompt, seed, location, time, index):
        captured.append((location, time, index))
        return str(tmp_path / f"{location}_{time}_{index:02d}.png")

    bg._generate_single_background = fake_generate_single_background

    result = bg.generate_background_library(
        sd_api=object(),
        locations=["한옥 마당", "시장 골목"],
        images_per_location=2,
        time_variants=False,
    )

    assert "집" in result
    assert "시장" in result
    assert all(location in {"집", "시장"} for location, _time, _index in captured)


def test_generate_single_background_saves_base64_result(tmp_path):
    bg = BackgroundLibrary(pack_id="test_pack", genre="senior", base_path=str(tmp_path))

    class FakeApi:
        def txt2img(self, **_kwargs):
            return {
                "images": [
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
                ]
            }

    path = bg._generate_single_background(
        sd_api=FakeApi(),
        prompt="test",
        negative_prompt="test",
        seed=1,
        location="집",
        time="any",
        index=0,
    )

    assert path is not None
    assert tmp_path.joinpath("집_any_00.png").exists()


def test_build_background_library_config_uses_custom_templates():
    config = build_background_library_config(
        genre="senior",
        config_data={
            "profile": "yadam",
            "style_prompt": "custom joseon style",
            "location_templates": {
                "집": {
                    "id": "hanok_home",
                    "name_ko": "집",
                    "name_en": "hanok home",
                    "base_prompt": "joseon hanok interior, no people",
                    "keywords": ["한옥", "사랑방"],
                }
            },
        },
        library_path="assets/backgrounds/test_pack",
    )

    assert config.style_prompt == "custom joseon style"
    assert "집" in config.location_templates
    assert config.location_templates["집"].id == "hanok_home"
    assert "한옥" in config.location_templates["집"].keywords
