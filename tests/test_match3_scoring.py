from core.match3_solver import find_all_swaps, find_best_swap


def test_find_all_swaps_returns_scored_moves_sorted_by_score():
    board = [
        ["red", "blue", "red", "green"],
        ["blue", "red", "blue", "green"],
        ["green", "green", "blue", "yellow"],
        ["yellow", "purple", "purple", "yellow"],
    ]

    swaps = find_all_swaps(board)

    assert swaps
    assert swaps == sorted(swaps, key=lambda item: item.score, reverse=True)
    assert find_best_swap(board) == swaps[0].swap


def test_match3_scoring_prefers_match_four_over_match_three():
    board = [
        ["red", "red", "red", "blue"],
        ["green", "blue", "green", "red"],
        ["yellow", "yellow", "blue", "red"],
        ["purple", "purple", "green", "red"],
    ]

    best = find_all_swaps(board)[0]

    assert "match_4" in best.reasons
    assert best.score >= 12


def test_match3_scoring_can_prioritize_target_cells():
    board = [
        ["red", "blue", "red"],
        ["blue", "red", "blue"],
        ["green", "green", "blue"],
    ]
    swaps_without_target = find_all_swaps(board)
    swaps_with_target = find_all_swaps(board, target_cells={(0, 0), (0, 1), (0, 2)})

    assert swaps_without_target
    assert swaps_with_target[0].score >= swaps_without_target[0].score
    assert "target" in swaps_with_target[0].reasons


def test_match3_scoring_skips_blocked_swap_cells():
    board = [
        ["red", "blue", "red"],
        ["blue", "red", "blue"],
        ["green", "green", "blue"],
    ]

    swaps = find_all_swaps(board, blocked_cells={((0, 1))})

    assert swaps == []
