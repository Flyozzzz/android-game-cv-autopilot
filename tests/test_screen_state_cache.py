from io import BytesIO

from PIL import Image, ImageDraw

from core.frame_source import Frame
from core.perception.element import ElementCandidate
from core.perception.state_cache import ScreenStateCache, average_hash, hamming_distance


def _png(width=100, height=100, color="white", box=None) -> bytes:
    image = Image.new("RGB", (width, height), color)
    if box:
        draw = ImageDraw.Draw(image)
        draw.rectangle(box, fill="black")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frame(png: bytes, width=100, height=100) -> Frame:
    return Frame(
        timestamp_ms=1,
        width=width,
        height=height,
        rgb_or_bgr_array=None,
        png_bytes=png,
        source_name="replay",
        latency_ms=0.1,
    )


def test_average_hash_is_stable_for_same_image_and_changes_for_different_image():
    first = average_hash(_png(color="white"))
    same = average_hash(_png(color="white"))
    different = average_hash(_png(color="black"))

    assert first == same
    assert hamming_distance(first, same) == 0
    assert hamming_distance(first, different) > 0


def test_screen_state_cache_returns_cached_elements_for_same_screen():
    cache = ScreenStateCache(hamming_threshold=0)
    frame = _frame(_png(box=(20, 20, 40, 40)))
    element = ElementCandidate.from_bbox(
        name="Continue",
        bbox=(10, 10, 110, 70),
        confidence=0.9,
        source="template",
    )

    stored = cache.put(
        frame,
        screen_id="tutorial_continue",
        profile_id="game",
        elements=[element],
        last_action="tap_continue",
    )
    found = cache.get(frame, profile_id="game")

    assert found is stored
    assert found.screen_id == "tutorial_continue"
    assert found.last_elements == [element]
    assert found.last_action == "tap_continue"

    cache.update_action(stored.screen_hash, "tap_again")
    assert cache.get(frame, profile_id="game").last_action == "tap_again"


def test_screen_state_cache_separates_profiles_and_resolution():
    cache = ScreenStateCache(hamming_threshold=0)
    png = _png(width=100, height=100)
    cache.put(_frame(png, 100, 100), screen_id="home", profile_id="game-a")

    assert cache.get(_frame(png, 100, 100), profile_id="game-b") is None
    assert cache.get(_frame(png, 200, 100), profile_id="game-a") is None


def test_screen_state_cache_roi_hash_can_ignore_outside_changes():
    cache = ScreenStateCache(hamming_threshold=0)
    roi = (40, 40, 80, 80)
    first = _frame(_png(box=(0, 0, 20, 20)))
    second = _frame(_png(box=(85, 85, 99, 99)))

    cache.put(first, screen_id="popup", profile_id="game", roi=roi)
    found = cache.get(second, profile_id="game", roi=roi)

    assert found is not None
    assert found.screen_id == "popup"


def test_screen_state_cache_evicts_oldest_entry():
    cache = ScreenStateCache(max_entries=1, hamming_threshold=0)
    first = _frame(_png(color="white"))
    second = _frame(_png(color="black"))

    cache.put(first, screen_id="first")
    cache.put(second, screen_id="second")

    assert len(cache) == 1
    assert cache.get(first) is None
    assert cache.get(second).screen_id == "second"


def test_screen_state_cache_rejects_frames_without_png():
    cache = ScreenStateCache()
    frame = Frame(1, 100, 100, None, None, "test", 0)

    try:
        cache.hash_frame(frame)
    except RuntimeError as exc:
        assert "PNG" in str(exc)
    else:
        raise AssertionError("missing png should fail")
