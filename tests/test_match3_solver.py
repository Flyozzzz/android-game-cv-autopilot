from io import BytesIO

from PIL import Image, ImageDraw

from core.match3_solver import cell_center, classify_board_from_png, find_best_swap


def test_find_best_swap_creates_horizontal_match():
    board = [
        ["red", "blue", "red"],
        ["blue", "red", "blue"],
        ["green", "green", "blue"],
    ]

    assert find_best_swap(board) in {((0, 1), (0, 2)), ((0, 1), (1, 1))}


def test_classify_board_and_cell_center():
    image = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(image)
    colors = [
        ["red", "green", "blue"],
        ["blue", "red", "green"],
        ["green", "blue", "red"],
    ]
    rgb = {"red": (240, 20, 20), "green": (20, 220, 20), "blue": (20, 20, 240)}
    for r, row in enumerate(colors):
        for c, color in enumerate(row):
            draw.rectangle((c * 100, r * 100, c * 100 + 99, r * 100 + 99), fill=rgb[color])
    buf = BytesIO()
    image.save(buf, format="PNG")

    classified = classify_board_from_png(
        buf.getvalue(),
        rows=3,
        cols=3,
        bounds=(0, 0, 300, 300),
    )

    assert classified.board == colors
    assert cell_center(classified, (1, 2)) == (250, 150)
