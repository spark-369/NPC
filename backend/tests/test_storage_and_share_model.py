"""Local storage helpers and the ClipShare activity gate."""

from datetime import datetime, timedelta, timezone

import pytest

from models.clip import ClipShare
from services import storage


def test_build_stored_filename_keeps_extension_and_is_unique():
    first = storage.build_stored_filename("my episode.mp4")
    second = storage.build_stored_filename("my episode.mp4")
    assert first.endswith(".mp4")
    assert first != second  # uuid suffix guarantees uniqueness


def test_build_stored_filename_rejects_unsupported_extension():
    with pytest.raises(ValueError):
        storage.build_stored_filename("notes.pdf")


def test_build_stored_filename_defaults_to_mp4_without_suffix():
    assert storage.build_stored_filename("noextension").endswith(".mp4")


def test_relative_and_absolute_media_path_roundtrip():
    relative = "clips/1/2/render.mp4"
    absolute = storage.absolute_media_path(relative)
    assert absolute.is_absolute()
    assert storage.relative_media_path(absolute) == relative


def test_absolute_media_path_passes_through_absolute_inputs(tmp_path):
    target = tmp_path / "x.mp4"
    assert storage.absolute_media_path(str(target)) == target


def test_sanitize_filename_strips_unsafe_characters():
    assert storage.sanitize_filename("../../etc/passwd") == "passwd"
    assert storage.sanitize_filename("a/b/c.mp4") == "c.mp4"
    assert storage.sanitize_filename("") == "episode"


def test_human_size_formats_units():
    assert storage.human_size(0) == "0.0 B"
    assert storage.human_size(1024) == "1.0 KB"
    assert storage.human_size(1024 * 1024) == "1.0 MB"


def test_delete_path_removes_file(tmp_path):
    target = tmp_path / "file.bin"
    target.write_bytes(b"data")
    assert storage.delete_path(str(target)) is True
    assert not target.exists()


def test_delete_path_is_quiet_for_unknown_targets():
    assert storage.delete_path(None) is False


# --- ClipShare.is_active gate ----------------------------------------------
def _share(**kwargs) -> ClipShare:
    return ClipShare(clip_id=1, owner_id=1, token="t", **kwargs)


def test_fresh_share_is_active():
    assert _share().is_active is True


def test_future_expiry_is_active():
    future = datetime.now(timezone.utc) + timedelta(days=7)
    assert _share(expires_at=future).is_active is True


def test_past_expiry_is_inactive():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    assert _share(expires_at=past).is_active is False


def test_revoked_share_is_inactive():
    assert _share(revoked_at=datetime.now(timezone.utc)).is_active is False


def test_naive_expiry_is_compared_defensively():
    """SQLite returns naive datetimes; the gate must not raise TypeError."""
    naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    assert _share(expires_at=naive_past).is_active is False
