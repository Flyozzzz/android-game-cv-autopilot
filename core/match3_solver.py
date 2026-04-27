"""Generic match-3 board solver utilities."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageStat


Cell = tuple[int, int]
Swap = tuple[Cell, Cell]


@dataclass(frozen=True)
class ClassifiedBoard:
    board: list[list[str]]
    bounds: tuple[int, int, int, int]
    rows: int
    cols: int


def find_best_swap(board: Sequence[Sequence[str]]) -> Swap | None:
    """Return the first adjacent swap that creates a match."""

    rows = len(board)
    cols = len(board[0]) if rows else 0
    if rows < 2 or cols < 2:
        return None

    mutable = [list(row) for row in board]
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                nr, nc = r + dr, c + dc
                if nr >= rows or nc >= cols or mutable[r][c] == mutable[nr][nc]:
                    continue
                mutable[r][c], mutable[nr][nc] = mutable[nr][nc], mutable[r][c]
                if _has_match_at(mutable, r, c) or _has_match_at(mutable, nr, nc):
                    mutable[r][c], mutable[nr][nc] = mutable[nr][nc], mutable[r][c]
                    return ((r, c), (nr, nc))
                mutable[r][c], mutable[nr][nc] = mutable[nr][nc], mutable[r][c]
    return None


def classify_board_from_png(
    screenshot_png: bytes,
    *,
    rows: int,
    cols: int,
    bounds: tuple[int, int, int, int] | None = None,
) -> ClassifiedBoard:
    image = Image.open(BytesIO(screenshot_png)).convert("RGB")
    width, height = image.size
    if bounds is None:
        side = int(min(width * 0.86, height * 0.48))
        x1 = (width - side) // 2
        y1 = int(height * 0.30)
        bounds = (x1, y1, x1 + side, y1 + side)

    x1, y1, x2, y2 = bounds
    cell_w = max(1, (x2 - x1) // cols)
    cell_h = max(1, (y2 - y1) // rows)
    board: list[list[str]] = []
    for r in range(rows):
        row: list[str] = []
        for c in range(cols):
            cx1 = x1 + c * cell_w + int(cell_w * 0.22)
            cy1 = y1 + r * cell_h + int(cell_h * 0.22)
            cx2 = x1 + (c + 1) * cell_w - int(cell_w * 0.22)
            cy2 = y1 + (r + 1) * cell_h - int(cell_h * 0.22)
            crop = image.crop((cx1, cy1, max(cx1 + 1, cx2), max(cy1 + 1, cy2)))
            row.append(_color_bucket(crop))
        board.append(row)
    return ClassifiedBoard(board=board, bounds=bounds, rows=rows, cols=cols)


def cell_center(
    classified: ClassifiedBoard,
    cell: Cell,
) -> tuple[int, int]:
    r, c = cell
    x1, y1, x2, y2 = classified.bounds
    cell_w = (x2 - x1) / classified.cols
    cell_h = (y2 - y1) / classified.rows
    return int(x1 + (c + 0.5) * cell_w), int(y1 + (r + 0.5) * cell_h)


def _has_match_at(board: Sequence[Sequence[str]], row: int, col: int) -> bool:
    color = board[row][col]
    if not color or color == "unknown":
        return False

    count = 1
    c = col - 1
    while c >= 0 and board[row][c] == color:
        count += 1
        c -= 1
    c = col + 1
    while c < len(board[row]) and board[row][c] == color:
        count += 1
        c += 1
    if count >= 3:
        return True

    count = 1
    r = row - 1
    while r >= 0 and board[r][col] == color:
        count += 1
        r -= 1
    r = row + 1
    while r < len(board) and board[r][col] == color:
        count += 1
        r += 1
    return count >= 3


def _color_bucket(crop: Image.Image) -> str:
    stat = ImageStat.Stat(crop)
    r, g, b = (float(v) for v in stat.mean[:3])
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx - mn < 18:
        if mx < 80:
            return "dark"
        if mx > 190:
            return "light"
        return "gray"
    if r > g * 1.15 and r > b * 1.15:
        return "red"
    if g > r * 1.12 and g > b * 1.08:
        return "green"
    if b > r * 1.12 and b > g * 1.08:
        return "blue"
    if r > 150 and g > 120 and b < 120:
        return "yellow"
    if r > 130 and b > 130 and g < 120:
        return "purple"
    return "mixed"
