"""Caption style preset helpers (shared by the API and the renderer)."""

from models.enums import CaptionStylePreset
from services.caption_styles import (
    apply_style_overrides,
    caption_style_to_dict,
    framing_to_dict,
    get_default_caption_style,
    get_default_framing,
    list_presets,
    resolve_preset,
)


def test_default_caption_style_is_a_copy():
    first = get_default_caption_style()
    second = get_default_caption_style()
    first.font_size = 999
    assert second.font_size != 999  # deep copies, no shared mutable state


def test_resolve_preset_by_name():
    style = resolve_preset("neon")
    assert style.preset == CaptionStylePreset.NEON


def test_resolve_preset_falls_back_to_default():
    assert resolve_preset("does-not-exist").preset == CaptionStylePreset.TIKTOK
    assert resolve_preset(None).preset == CaptionStylePreset.TIKTOK


def test_caption_style_to_dict_from_none_returns_defaults():
    payload = caption_style_to_dict(None)
    assert payload["preset"] == "tiktok"
    assert payload["words_per_line"] == 3


def test_caption_style_to_dict_merges_partial_dict():
    payload = caption_style_to_dict({"font_size": 100, "uppercase": False})
    assert payload["font_size"] == 100
    assert payload["uppercase"] is False
    assert payload["preset"] == "tiktok"  # untouched defaults survive


def test_apply_style_overrides_merges():
    merged = apply_style_overrides(None, {"text_color": "#123456"})
    assert merged["text_color"] == "#123456"


def test_framing_to_dict_from_none():
    payload = framing_to_dict(None)
    assert payload["output_width"] == 1080
    assert payload["output_height"] == 1920
    assert payload["fps"] == 30


def test_get_default_framing_honours_args():
    framing = get_default_framing(width=720, height=1280, fps=24)
    assert (framing.output_width, framing.output_height, framing.fps) == (720, 1280, 24)


def test_list_presets_exposes_labels_and_styles():
    presets = list_presets()
    names = {preset["name"] for preset in presets}
    assert names == {
        CaptionStylePreset.TIKTOK,
        CaptionStylePreset.KARAOKE,
        CaptionStylePreset.MINIMAL,
        CaptionStylePreset.NEON,
        CaptionStylePreset.BOLD_YELLOW,
    }
    for preset in presets:
        assert preset["label"]
        assert "font_size" in preset["style"]
