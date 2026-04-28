"""Screen state cache keyed by lightweight perceptual hashes."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from io import BytesIO
import time

from PIL import Image

from core.frame_source import Frame
from core.perception.element import ElementCandidate
from core.perception.roi import PixelBox


@dataclass
class ScreenState:
    screen_hash: str
    screen_id: str
    last_elements: list[ElementCandidate] = field(default_factory=list)
    last_action: str = ""
    last_seen_ts: float = field(default_factory=time.time)
    resolution: tuple[int, int] = (0, 0)
    profile_id: str = ""


class ScreenStateCache:
    def __init__(
        self,
        *,
        max_entries: int = 100,
        hash_size: int = 8,
        hamming_threshold: int = 4,
    ):
        self.max_entries = max(1, int(max_entries or 1))
        self.hash_size = max(4, int(hash_size or 8))
        self.hamming_threshold = max(0, int(hamming_threshold or 0))
        self._states: OrderedDict[str, ScreenState] = OrderedDict()

    def put(
        self,
        frame: Frame,
        *,
        screen_id: str,
        profile_id: str = "",
        elements: list[ElementCandidate] | None = None,
        last_action: str = "",
        roi: PixelBox | None = None,
    ) -> ScreenState:
        screen_hash = self.hash_frame(frame, roi=roi)
        state = ScreenState(
            screen_hash=screen_hash,
            screen_id=screen_id,
            last_elements=list(elements or []),
            last_action=last_action,
            last_seen_ts=time.time(),
            resolution=(frame.width, frame.height),
            profile_id=profile_id,
        )
        self._states[screen_hash] = state
        self._states.move_to_end(screen_hash)
        while len(self._states) > self.max_entries:
            self._states.popitem(last=False)
        return state

    def get(
        self,
        frame: Frame,
        *,
        profile_id: str = "",
        roi: PixelBox | None = None,
    ) -> ScreenState | None:
        screen_hash = self.hash_frame(frame, roi=roi)
        for cached_hash, state in reversed(self._states.items()):
            if profile_id and state.profile_id and state.profile_id != profile_id:
                continue
            if state.resolution != (frame.width, frame.height):
                continue
            if hamming_distance(screen_hash, cached_hash) <= self.hamming_threshold:
                state.last_seen_ts = time.time()
                self._states.move_to_end(cached_hash)
                return state
        return None

    def update_action(self, screen_hash: str, action: str) -> None:
        state = self._states.get(screen_hash)
        if state:
            state.last_action = action
            state.last_seen_ts = time.time()
            self._states.move_to_end(screen_hash)

    def clear(self) -> None:
        self._states.clear()

    def hash_frame(self, frame: Frame, *, roi: PixelBox | None = None) -> str:
        if not frame.png_bytes:
            raise RuntimeError("ScreenStateCache requires PNG frame bytes")
        return average_hash(frame.png_bytes, hash_size=self.hash_size, roi=roi)

    def __len__(self) -> int:
        return len(self._states)


def average_hash(png: bytes, *, hash_size: int = 8, roi: PixelBox | None = None) -> str:
    image = Image.open(BytesIO(png)).convert("L")
    if roi is not None:
        image = image.crop(_clamped_roi(roi, image.size))
    image = image.resize((hash_size, hash_size))
    pixels = list(image.getdata())
    average = sum(pixels) / len(pixels)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | int(pixel >= average)
    return f"{int(round(average)):02x}{bits:0{hash_size * hash_size // 4}x}"


def hamming_distance(left: str, right: str) -> int:
    width = max(len(left), len(right))
    left_int = int(left, 16)
    right_int = int(right, 16)
    return (left_int ^ right_int).bit_count() + abs(len(left) - len(right)) * 4 if width else 0


def _clamped_roi(roi: PixelBox, size: tuple[int, int]) -> PixelBox:
    width, height = size
    x1, y1, x2, y2 = roi
    return (
        max(0, min(width - 1, int(x1))),
        max(0, min(height - 1, int(y1))),
        max(1, min(width, int(x2))),
        max(1, min(height, int(y2))),
    )
