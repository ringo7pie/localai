"""C6 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。

ビットマスクで候補を持ち、候補が 1 つのマス（裸の単一候補）と、単位（行・列・ブロック）の中で 1 マスにしか入らない数字
（隠れた単一候補）を先に確定し、残りは候補の最も少ないマスから分岐する。解は 2 つ見つかった時点で打ち切る。
"""

ALL_DIGITS = 0b1111111110  # ビット 1〜9
ROW_OF = [index // 9 for index in range(81)]
COL_OF = [index % 9 for index in range(81)]
BOX_OF = [(index // 27) * 3 + (index % 9) // 3 for index in range(81)]
POPCOUNT = [bin(mask).count("1") for mask in range(1 << 10)]
UNITS = (
    [[row * 9 + col for col in range(9)] for row in range(9)]
    + [[row * 9 + col for row in range(9)] for col in range(9)]
    + [[(box_row * 3 + row) * 9 + box_col * 3 + col for row in range(3) for col in range(3)]
       for box_row in range(3) for box_col in range(3)]
)


def _place(cells, rows, cols, boxes, index, digit):
    bit = 1 << digit
    cells[index] = digit
    rows[ROW_OF[index]] |= bit
    cols[COL_OF[index]] |= bit
    boxes[BOX_OF[index]] |= bit


def _hidden_single(candidates):
    """単位の中で 1 マスにしか入らない数字を探す。戻り値は (マス, 数字)、矛盾なら (-1, 0)、無ければ None。"""

    for unit in UNITS:
        seen_once = 0
        seen_twice = 0
        for index in unit:
            mask = candidates[index]
            seen_twice |= seen_once & mask
            seen_once |= mask
        single = seen_once & ~seen_twice
        if single:
            for index in unit:
                mask = candidates[index] & single
                if mask:
                    if POPCOUNT[mask] > 1:
                        return -1, 0  # 同じマスに 2 つの数字が入らなければならない
                    return index, mask.bit_length() - 1
    return None


def _search(cells, rows, cols, boxes, solutions):
    while True:
        best_index, best_mask, best_count = -1, 0, 10
        candidates = [0] * 81
        for index in range(81):
            if cells[index] == 0:
                mask = ALL_DIGITS & ~(rows[ROW_OF[index]] | cols[COL_OF[index]] | boxes[BOX_OF[index]])
                candidates[index] = mask
                count = POPCOUNT[mask]
                if count < best_count:
                    best_index, best_mask, best_count = index, mask, count
        if best_index < 0:
            solutions.append(cells[:])
            return
        if best_count == 0:
            return
        if best_count == 1:
            _place(cells, rows, cols, boxes, best_index, best_mask.bit_length() - 1)
            continue
        hidden = _hidden_single(candidates)
        if hidden is not None:
            index, digit = hidden
            if index < 0:
                return
            _place(cells, rows, cols, boxes, index, digit)
            continue
        for digit in range(1, 10):
            if best_mask & (1 << digit):
                next_cells, next_rows, next_cols, next_boxes = cells[:], rows[:], cols[:], boxes[:]
                _place(next_cells, next_rows, next_cols, next_boxes, best_index, digit)
                _search(next_cells, next_rows, next_cols, next_boxes, solutions)
                if len(solutions) >= 2:
                    return
        return


def solve_sudoku(grid: str) -> str:
    if len(grid) != 81:
        raise ValueError("grid must have 81 characters")
    cells = []
    for char in grid:
        if char == ".":
            cells.append(0)
        elif char in "123456789":
            cells.append(ord(char) - ord("0"))
        else:
            raise ValueError(f"bad character {char!r}")
    rows, cols, boxes = [0] * 9, [0] * 9, [0] * 9
    for index, digit in enumerate(cells):
        if digit:
            bit = 1 << digit
            if rows[ROW_OF[index]] & bit or cols[COL_OF[index]] & bit or boxes[BOX_OF[index]] & bit:
                raise ValueError("given digits conflict")
            rows[ROW_OF[index]] |= bit
            cols[COL_OF[index]] |= bit
            boxes[BOX_OF[index]] |= bit
    solutions: list[list[int]] = []
    _search(cells, rows, cols, boxes, solutions)
    if not solutions:
        raise ValueError("no solution")
    if len(solutions) > 1:
        raise ValueError("multiple solutions")
    return "".join(str(digit) for digit in solutions[0])
