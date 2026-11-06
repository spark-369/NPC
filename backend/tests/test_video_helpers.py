"""Unit tests for the pure-Python video/caption helpers."""

import numpy as np
import pytest

from services.video import captions as cap
from services.video import framing
from services.subtitles import build_subtitle_entries, render_subtitles, to_srt, to_vtt


# --- hex_to_bgr -------------------------------------------------------------
def test_hex_to_bgr_parses_rgb():
    assert cap.hex_to_bgr("#FF0000") == (0, 0, 255)  # BGR order
    assert cap.hex_to_bgr("#0000FF") == (255, 0, 0)


def test_hex_to_bgr_supports_shorthand_and_alpha():
    assert cap.hex_to_bgr("#F00") == (0, 0, 255)
    assert cap.hex_to_bgr("#80FF0000") == (0, 0, 255)  # AARRGGBB -> drop alpha


def test_hex_to_bgr_falls_back_on_garbage():
    assert cap.hex_to_bgr("not-a-colour") == (255, 255, 255)
    assert cap.hex_to_bgr("") == (255, 255, 255)


# --- words_from_payload -----------------------------------------------------
def test_words_from_payload_rebases_onto_clip_start():
    words = [
        {"word": "hello", "start": 10.0, "end": 10.4},
        {"word": "world", "start": 10.5, "end": 10.9},
    ]
    result = cap.words_from_payload(words, clip_start=10.0, clip_end=12.0, fallback_text="hello world")
    assert [w.text for w in result] == ["hello", "world"]
    assert result[0].start == 0.0  # rebased to clip start
    assert result[1].start == pytest.approx(0.5)


def test_words_from_payload_clamps_words_at_clip_boundary():
    words = [{"word": "before", "start": 5.0, "end": 9.0}, {"word": "in", "start": 10.2, "end": 10.5}]
    result = cap.words_from_payload(words, 10.0, 12.0, "before in")
    # The straddling word clamps to 0 (never a negative time).
    assert all(w.start >= 0.0 for w in result)


def test_words_from_payload_falls_back_when_text_edited():
    """Edited transcript invalidates the stored word timings and redistributes text."""
    words = [{"word": "old", "start": 0.0, "end": 0.5}]
    result = cap.words_from_payload(words, 0.0, 2.0, fallback_text="brand new words")
    assert [w.text for w in result] == ["brand", "new", "words"]


def test_words_from_payload_empty_fallback_returns_empty():
    assert cap.words_from_payload([], 0.0, 2.0, fallback_text="") == []


# --- group_caption_lines ----------------------------------------------------
def test_group_caption_lines_chunks_by_words_per_line():
    words = [cap.CaptionWord(text=str(i), start=i, end=i + 0.5) for i in range(10)]
    groups = cap.group_caption_lines(words, words_per_line=3, max_lines=2)
    assert [len(g) for g in groups] == [6, 4]  # 3 words * 2 lines = 6 per group


# --- draw_captions smoke test ----------------------------------------------
def test_draw_captions_does_not_mutate_shape_and_activates_group():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    words = [cap.CaptionWord(text="hello", start=0.0, end=1.0)]
    groups = cap.group_caption_lines(words, 3, 2)
    result = cap.draw_captions(frame, 0.5, groups, {"uppercase": True, "text_color": "#FFFFFF"})
    assert result.shape == (100, 200, 3)
    assert result.sum() > 0  # something was drawn


def test_draw_captions_noop_outside_active_window():
    frame = np.zeros((50, 50, 3), dtype=np.uint8)
    words = [cap.CaptionWord(text="hello", start=0.0, end=1.0)]
    groups = cap.group_caption_lines(words, 3, 2)
    result = cap.draw_captions(frame.copy(), 9.9, groups, {})
    assert result.sum() == 0


# --- framing ----------------------------------------------------------------
def test_compute_crop_box_preserves_target_aspect_ratio():
    x, y, w, h = framing.compute_crop_box(1920, 1080, 1080, 1920, 0.5, 0.4, 1.0)
    assert abs((w / h) - (1080 / 1920)) < 0.02


def test_crop_and_fit_returns_target_size():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    out = framing.crop_and_fit(frame, 1080, 1920, focus_x=0.5, focus_y=0.4)
    assert out.shape == (1920, 1080, 3)


# --- subtitles --------------------------------------------------------------
SAMPLE_WORDS = [
    {"word": token, "start": index * 0.4, "end": index * 0.4 + 0.38}
    for index, token in enumerate("welcome to the show folks".split())
]


def test_build_subtitle_entries_is_time_ordered():
    entries = build_subtitle_entries(SAMPLE_WORDS, 0.0, 2.0, "welcome to the show folks")
    assert entries
    starts = [entry[0] for entry in entries]
    assert starts == sorted(starts)


def test_to_srt_and_vtt_formatting():
    entries = build_subtitle_entries(SAMPLE_WORDS, 0.0, 2.0, "welcome to the show folks")
    srt = to_srt(entries)
    assert srt.splitlines()[1].count("-->") == 1
    assert "," in srt.splitlines()[1]  # SRT uses a comma for milliseconds

    vtt = to_vtt(entries)
    assert vtt.startswith("WEBVTT")
    vtt_timing = next(line for line in vtt.splitlines() if "-->" in line)
    assert "." in vtt_timing  # WebVTT uses a dot


def test_render_subtitles_returns_media_types():
    doc, media_type = render_subtitles("srt", SAMPLE_WORDS, 0.0, 2.0, "welcome to the show folks")
    assert media_type == "application/x-subrip"
    assert "-->" in doc

    doc, media_type = render_subtitles("vtt", SAMPLE_WORDS, 0.0, 2.0, "welcome to the show folks")
    assert media_type == "text/vtt"
    assert doc.startswith("WEBVTT")


def test_render_subtitles_rejects_unknown_format():
    with pytest.raises(ValueError):
        render_subtitles("docx", SAMPLE_WORDS, 0.0, 2.0)
