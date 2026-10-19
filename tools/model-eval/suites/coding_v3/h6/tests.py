"""H6 count_tilings の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は reference.py で計算した。小さい盤面は oracle.py の素朴な探索、中くらいの盤面はメモ化の再帰と一致し、
大きい盤面は参照解を転置せずに回した値とも一致することを作成時に確かめた（tests/test_hard.py）。
"""

import random

FORBIDDEN_CALLS = ()


def _checksum(values):
    acc = 0
    for index, value in enumerate(values):
        acc = (acc * 1000003 + value % ((1 << 61) - 1) + index) % ((1 << 61) - 1)
    return acc


def _boards(seed, count, max_rows, max_cols, min_side=1):
    rng = random.Random(seed)
    boards = []
    for _ in range(count):
        rows, cols = rng.randint(min_side, max_rows), rng.randint(min_side, max_cols)
        hole = rng.choice((0.0, 0.08, 0.2))
        boards.append(["".join("#" if rng.random() < hole else "." for _ in range(cols)) for _ in range(rows)])
    return boards


def _full(rows, cols):
    return ["." * cols for _ in range(rows)]


def case_examples(sol, t):
    t.eq(sol.count_tilings(["..", ".."]), 2)
    t.eq(sol.count_tilings(["...", "..."]), 5)
    t.eq(sol.count_tilings([".#", ".."]), 1)
    t.eq(sol.count_tilings(["."]), 0)


def case_nothing_to_cover(sol, t):
    t.eq(sol.count_tilings([]), 1)
    t.eq(sol.count_tilings([""]), 1)
    t.eq(sol.count_tilings(["", ""]), 1)
    t.eq(sol.count_tilings(["##", "##"]), 1)


def case_single_rows_and_columns(sol, t):
    t.eq(sol.count_tilings([".."]), 1)
    t.eq(sol.count_tilings(["..."]), 0)
    t.eq(sol.count_tilings(["......"]), 1)
    t.eq(sol.count_tilings([".", ".", ".", "."]), 1)
    t.eq(sol.count_tilings([".", ".", "."]), 0)
    t.eq(sol.count_tilings(["..#.."]), 1)


def case_invalid_boards(sol, t):
    t.raises(ValueError, sol.count_tilings, ["..", "."])
    t.raises(ValueError, sol.count_tilings, ["..", ".x"])
    t.raises(ValueError, sol.count_tilings, ["..", ". "])


def case_each_l_orientation(sol, t):
    for board in ([".#", ".."], ["#.", ".."], ["..", ".#"], ["..", "#."]):
        t.eq(sol.count_tilings(board), 1)


def case_l_reaching_down_left(sol, t):
    # 1 行目の右のマスから、左下へ伸びる L しか置けない
    t.eq(sol.count_tilings(["#.", ".."]), 1)
    t.eq(sol.count_tilings(["##.", "..."]), EXPECTED["down_left_a"])
    t.eq(sol.count_tilings(["#..#", "...."]), EXPECTED["down_left_b"])


def case_two_by_n_sequence(sol, t):
    t.eq([sol.count_tilings(_full(2, n)) for n in range(1, 13)], EXPECTED["two_by_n"])


def case_three_by_n_sequence(sol, t):
    t.eq([sol.count_tilings(_full(3, n)) for n in range(1, 11)], EXPECTED["three_by_n"])


def case_small_full_boards(sol, t):
    t.eq([sol.count_tilings(_full(n, n)) for n in range(1, 7)], EXPECTED["square"])


def case_holes_and_isolated_cells(sol, t):
    t.eq(sol.count_tilings(["...", ".#.", "..."]), EXPECTED["ring3"])
    t.eq(sol.count_tilings(["#.#", "...", "#.#"]), EXPECTED["plus"])
    t.eq(sol.count_tilings([".#.", "###", "..."]), 0)
    t.eq(sol.count_tilings(["..#..", "..#..", "#####", "....#"]), EXPECTED["regions"])


def case_disconnected_regions_multiply(sol, t):
    left = ["...", "..."]
    t.eq(sol.count_tilings(["...#...", "...#..."]), 25)
    t.eq(sol.count_tilings([row + "#" + row for row in left] + ["#######", ".#.....", "......."]), EXPECTED["multiply"])


def case_ring_and_l_regions(sol, t):
    ring = ["......", ".####.", ".####.", ".####.", ".####.", "......"]
    t.eq(sol.count_tilings(ring), EXPECTED["ring6"])
    ell = ["..####", "..####", "..####", "......", "......"]
    t.eq(sol.count_tilings(ell), EXPECTED["ell"])


def case_transposed_boards_agree(sol, t):
    board = ["..#...", "......", ".#....", "....#."]
    transposed = ["".join(row[c] for row in board) for c in range(len(board[0]))]
    t.eq(sol.count_tilings(board), EXPECTED["asym"])
    t.eq(sol.count_tilings(transposed), EXPECTED["asym"])


def case_random_small_boards(sol, t):
    t.eq(_checksum([sol.count_tilings(b) for b in _boards(61, 300, 5, 5)]), EXPECTED["small_boards"])


def case_random_medium_boards(sol, t):
    t.eq(_checksum([sol.count_tilings(b) for b in _boards(62, 30, 7, 8, 4)]), EXPECTED["medium_boards"])


def case_tall_thin_boards(sol, t):
    t.eq(sol.count_tilings(_full(16, 2)), EXPECTED["tall2"])
    t.eq(sol.count_tilings(_full(16, 3)), EXPECTED["tall3"])
    t.eq(sol.count_tilings(_full(3, 16)), EXPECTED["tall3"])


def case_big_answer_exact(sol, t):
    t.eq(sol.count_tilings(_full(8, 8)), EXPECTED["eight"])


def case_performance_wide_board(sol, t):
    t.eq(sol.count_tilings(_full(10, 16)), EXPECTED["full_10_16"])


def case_performance_tall_board(sol, t):
    t.eq(sol.count_tilings(_full(16, 10)), EXPECTED["full_10_16"])


def case_performance_wide_board_with_holes(sol, t):
    rng = random.Random(65)
    board = ["".join("#" if rng.random() < 0.07 else "." for _ in range(16)) for _ in range(9)]
    t.eq(sol.count_tilings(board), EXPECTED["holes_9_16"])


def case_performance_patterned_holes(sol, t):
    board = ["".join("#" if (r * 7 + c * 3) % 11 == 0 else "." for c in range(15)) for r in range(10)]
    t.eq(sol.count_tilings(board), EXPECTED["pattern_10_15"])


EXPECTED = {
    'down_left_a': 1,
    'down_left_b': 2,
    'two_by_n': [1, 2, 5, 11, 24, 53, 117, 258, 569, 1255, 2768, 6105],
    'three_by_n': [0, 5, 8, 55, 140, 633, 1984, 7827, 26676, 99621],
    'square': [0, 2, 8, 380, 21272, 5350806],
    'ring3': 2,
    'plus': 0,
    'regions': 4,
    'multiply': 1100,
    'ring6': 7,
    'ell': 517,
    'asym': 551,
    'small_boards': 1483601752720462660,
    'medium_boards': 1616457807633992664,
    'tall2': 144467,
    'tall3': 215457835,
    'eight': 6652506271144,
    'full_10_16': 22180224945601426126611261464370852,
    'holes_9_16': 5023686524066525462339736114,
    'pattern_10_15': 24361436009848958779729535,
}

CASES = [
    case_examples, case_nothing_to_cover, case_single_rows_and_columns, case_invalid_boards, case_each_l_orientation,
    case_l_reaching_down_left, case_two_by_n_sequence, case_three_by_n_sequence, case_small_full_boards,
    case_holes_and_isolated_cells, case_disconnected_regions_multiply, case_ring_and_l_regions,
    case_transposed_boards_agree, case_random_small_boards, case_random_medium_boards, case_tall_thin_boards,
    case_big_answer_exact, case_performance_wide_board, case_performance_tall_board,
    case_performance_wide_board_with_holes, case_performance_patterned_holes,
]
