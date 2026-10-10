"""C6 solve_sudoku の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

盤面の解の有無・一意性は、参照解とは別の解法（exact cover）で照合して固定した。解が一意と確かめた盤面では、
返った解が規則を満たしヒントと矛盾しないことを確かめれば、それが唯一の解である。
"""

FORBIDDEN_CALLS = ()

EXAMPLE = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
EXAMPLE_SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
# 生成した盤面（ヒント 40・32・26・24 個）とその解
GENERATED = [
    ("9.8356...25.1.46891.7....34.1...8..5874.2...6.25...49..92..3...53..89.674......53",
     "948356172253174689167892534319648725874925316625731498792563841531489267486217953"),
    ("....3.8.273...914......4.6..6.5...14.1...63.7..7.4..8.59436...8.28......6..42....",
     "941635872736289145285714963869573214412896357357142689594361728128957436673428591"),
    (".2.75.39..1.......8.....2...6.3..7...71.6.58...5......75..9...4........6..4.7.1.3",
     "426751398519823467837649215968315742371462589245987631753196824182534976694278153"),
    (".6....4...82.3..9....9..1..4.6.8.....3..........6..7.3..12.8..6.......4.7..19.8..",
     "967821435182435697354967128476382519835719264219654783591248376628573941743196852"),
]
INKALA_2012 = "8..........36......7..9.2...5...7.......457.....1...3...1....68..85...1..9....4.."
INKALA_2012_SOLUTION = "812753649943682175675491283154237896369845721287169534521974368438526917796318452"
INKALA_2010 = "..53.....8......2..7..1.5..4....53...1..7...6..32...8..6.5....9..4....3......97.."
ESCARGOT = "1....7.9..3..2...8..96..5....53..9...1..8...26....4...3......1..4......7..7...3.."
ESCARGOT_SOLUTION = "162857493534129678789643521475312986913586742628794135356478219241935867897261354"
EASTER_MONSTER = "1.......2.9.4...5...6...7...5.9.3.......7.......85..4.7.....6...3...9.8...2.....1"
SEVENTEEN_A = "...8.1..........435............7.8........1...2..3....6......75..34........2..6.."
SEVENTEEN_A_SOLUTION = "237841569186795243594326718315674892469582137728139456642918375853467921971253684"
SEVENTEEN_B = "..............3.85..1.2.......5.7.....4...1...9.......5......73..2.1........4...9"
SEVENTEEN_B_SOLUTION = "987654321246173985351928746128537694634892157795461832519286473472319568863745219"
ROYLE_17_A = ".......1.4.........2...........5.4.7..8...3....1.9....3..4..2...5.1........8.6..."
ROYLE_17_B = ".......1.4.........2...........5.6.4..8...3....1.9....3..4..2...5.1........8.7..."
# 完成盤から、同じ帯の 2 行 × 2 列の長方形（数字 2 種の入れ替え）を消したもの。解はちょうど 2 つ
TWO_SOLUTIONS = "89.76213.62.91387.713854269561497382387125946942386517456231798239678451178549623"
# ヒント 17 個の盤面からヒントを 1 つ消したもの（解が複数になる）
UNDERDETERMINED = [
    "...8.1..........435............7.8........1......3....6......75..34........2..6..",
    "..............3.85..1.2.......5.7.....4.......9.......5......73..2.1........4...9",
    ".......1.4.........2...........5.4.7..8...3......9....3..4..2...5.1........8.6...",
]
# ヒントどうしに矛盾は無いが解が無い盤面（難問のヒントを 1 つ別の数字に変えたもの）
UNSOLVABLE = [
    "1..........36......7..9.2...5...7.......457.....1...3...1....68..85...1..9....4..",
    "8..........36......7..9.2...5...7.......457.....1...3...1....68..85...1..2....4..",
    "...8.1..........431............7.8........1...2..3....6......75..34........2..6..",
    "...8.1..........435............7.8........1...4..3....6......75..34........2..6..",
]


def _check_solution(t, puzzle, result):
    t.eq(type(result), str)
    t.eq(len(result), 81)
    t.eq(all(char in "123456789" for char in result), True)
    t.eq(all(given == "." or given == got for given, got in zip(puzzle, result)), True)
    for unit in range(9):
        row = result[unit * 9:unit * 9 + 9]
        col = result[unit::9]
        box_start = (unit // 3) * 27 + (unit % 3) * 3
        box = "".join(result[box_start + offset * 9:box_start + offset * 9 + 3] for offset in range(3))
        t.eq(sorted(row), list("123456789"))
        t.eq(sorted(col), list("123456789"))
        t.eq(sorted(box), list("123456789"))


def case_bad_length(sol, t):
    t.raises(ValueError, sol.solve_sudoku, "")
    t.raises(ValueError, sol.solve_sudoku, EXAMPLE[:80])
    t.raises(ValueError, sol.solve_sudoku, EXAMPLE + ".")
    t.raises(ValueError, sol.solve_sudoku, EXAMPLE_SOLUTION + "1")


def case_bad_characters(sol, t):
    for bad in ("0", " ", "a", "１", "٣", "\n", "-", "*"):
        t.raises(ValueError, sol.solve_sudoku, bad + EXAMPLE[1:])
        t.raises(ValueError, sol.solve_sudoku, EXAMPLE[:40] + bad + EXAMPLE[41:])


def case_conflicting_givens(sol, t):
    t.raises(ValueError, sol.solve_sudoku, "11" + "." * 79)
    t.raises(ValueError, sol.solve_sudoku, "1" + "." * 8 + "1" + "." * 71)
    t.raises(ValueError, sol.solve_sudoku, "1" + "." * 9 + "1" + "." * 70)
    t.raises(ValueError, sol.solve_sudoku, "." * 60 + "5" + "." * 19 + "5")


def case_conflict_inside_an_otherwise_full_grid(sol, t):
    swapped = list(EXAMPLE_SOLUTION)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    t.raises(ValueError, sol.solve_sudoku, "".join(swapped))
    changed = EXAMPLE_SOLUTION[:80] + ("1" if EXAMPLE_SOLUTION[80] != "1" else "2")
    t.raises(ValueError, sol.solve_sudoku, changed)


def case_already_solved(sol, t):
    t.eq(sol.solve_sudoku(EXAMPLE_SOLUTION), EXAMPLE_SOLUTION)
    t.eq(sol.solve_sudoku(SEVENTEEN_A_SOLUTION), SEVENTEEN_A_SOLUTION)


def case_single_blank(sol, t):
    for index in (0, 40, 80):
        puzzle = EXAMPLE_SOLUTION[:index] + "." + EXAMPLE_SOLUTION[index + 1:]
        t.eq(sol.solve_sudoku(puzzle), EXAMPLE_SOLUTION)


def case_example_puzzle(sol, t):
    t.eq(sol.solve_sudoku(EXAMPLE), EXAMPLE_SOLUTION)


def case_generated_puzzles(sol, t):
    for puzzle, solution in GENERATED:
        t.eq(sol.solve_sudoku(puzzle), solution)


def case_cell_without_candidates(sol, t):
    # 行 0 に 1〜8、同じ列の下に 9 があり、右上のマスに入る数字が無い。ヒントどうしは矛盾していない
    puzzle = "12345678." + "." * 8 + "9" + "." * 63
    t.raises(ValueError, sol.solve_sudoku, puzzle)


def case_empty_and_nearly_empty_have_many_solutions(sol, t):
    t.raises(ValueError, sol.solve_sudoku, "." * 81)
    t.raises(ValueError, sol.solve_sudoku, "5" + "." * 80)
    t.raises(ValueError, sol.solve_sudoku, "123456789" + "." * 72)


def case_exactly_two_solutions(sol, t):
    t.raises(ValueError, sol.solve_sudoku, TWO_SOLUTIONS)
    # 4 マスのうち 1 つを戻すと一意になる
    fixed = TWO_SOLUTIONS[:2] + "4" + TWO_SOLUTIONS[3:]
    _check_solution(t, fixed, sol.solve_sudoku(fixed))


def case_underdetermined_hard_puzzles(sol, t):
    for puzzle in UNDERDETERMINED:
        t.raises(ValueError, sol.solve_sudoku, puzzle)


def case_unsolvable_without_direct_conflict(sol, t):
    for puzzle in UNSOLVABLE:
        t.raises(ValueError, sol.solve_sudoku, puzzle)


def case_hard_inkala_2012(sol, t):
    t.eq(sol.solve_sudoku(INKALA_2012), INKALA_2012_SOLUTION)


def case_hard_inkala_2010_and_escargot(sol, t):
    _check_solution(t, INKALA_2010, sol.solve_sudoku(INKALA_2010))
    t.eq(sol.solve_sudoku(ESCARGOT), ESCARGOT_SOLUTION)


def case_hard_easter_monster(sol, t):
    _check_solution(t, EASTER_MONSTER, sol.solve_sudoku(EASTER_MONSTER))


def case_seventeen_clues_a(sol, t):
    t.eq(sol.solve_sudoku(SEVENTEEN_A), SEVENTEEN_A_SOLUTION)


def case_seventeen_clues_b(sol, t):
    t.eq(sol.solve_sudoku(SEVENTEEN_B), SEVENTEEN_B_SOLUTION)


def case_seventeen_clues_royle(sol, t):
    _check_solution(t, ROYLE_17_A, sol.solve_sudoku(ROYLE_17_A))
    _check_solution(t, ROYLE_17_B, sol.solve_sudoku(ROYLE_17_B))


def case_hard_puzzles_in_sequence(sol, t):
    # 難問をまとめて解く。1 問ずつは速くても、合計で遅い解法はここで落ちる
    for puzzle in (INKALA_2012, INKALA_2010, ESCARGOT, EASTER_MONSTER, SEVENTEEN_A, SEVENTEEN_B):
        _check_solution(t, puzzle, sol.solve_sudoku(puzzle))


CASES = [
    case_bad_length, case_bad_characters, case_conflicting_givens, case_conflict_inside_an_otherwise_full_grid,
    case_already_solved, case_single_blank, case_example_puzzle, case_generated_puzzles, case_cell_without_candidates,
    case_empty_and_nearly_empty_have_many_solutions, case_exactly_two_solutions, case_underdetermined_hard_puzzles,
    case_unsolvable_without_direct_conflict, case_hard_inkala_2012, case_hard_inkala_2010_and_escargot,
    case_hard_easter_monster, case_seventeen_clues_a, case_seventeen_clues_b, case_seventeen_clues_royle,
    case_hard_puzzles_in_sequence,
]
