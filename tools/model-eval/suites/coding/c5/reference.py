"""C5 の参照解。隠しテストが正しいことを tests/test_units.py で確かめるためだけに使う。モデルには見せない。

パターンを構文木にし、Thompson の NFA に落として、状態集合を 1 文字ずつ進める（探索は各位置で開始状態を足す）。
"""

CHAR, ANY, SPLIT, EPS, BOL, EOL, MATCH = range(7)


class _Parser:
    def __init__(self, pattern: str):
        self.pattern = pattern
        self.position = 0

    def peek(self, offset: int = 0):
        index = self.position + offset
        return self.pattern[index] if index < len(self.pattern) else None

    def take(self) -> str:
        char = self.pattern[self.position]
        self.position += 1
        return char

    def parse(self):
        tree = self.parse_alternation()
        if self.position != len(self.pattern):
            raise ValueError("unbalanced parenthesis")
        return tree

    def parse_alternation(self):
        branches = [self.parse_sequence()]
        while self.peek() == "|":
            self.take()
            branches.append(self.parse_sequence())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def parse_sequence(self):
        items = []
        while self.peek() not in (None, "|", ")"):
            items.append(self.parse_piece())
        return ("seq", items)

    def parse_piece(self):
        atom = self.parse_atom()
        if self.peek() in ("*", "+", "?"):
            quantifier = self.take()
            if atom[0] in ("bol", "eol"):
                raise ValueError("nothing to repeat")
            if self.peek() in ("*", "+", "?"):
                raise ValueError("multiple repeat")
            return ({"*": "star", "+": "plus", "?": "opt"}[quantifier], atom)
        return atom

    def parse_atom(self):
        char = self.take()
        if char == "(":
            inner = self.parse_alternation()
            if self.peek() != ")":
                raise ValueError("missing )")
            self.take()
            return inner
        if char == "[":
            return self.parse_class()
        if char == ".":
            return ("any",)
        if char == "^":
            return ("bol",)
        if char == "$":
            return ("eol",)
        if char == "\\":
            if self.peek() is None:
                raise ValueError("trailing backslash")
            return ("lit", self.take())
        if char in ("*", "+", "?"):
            raise ValueError("nothing to repeat")
        return ("lit", char)

    def class_char(self) -> str:
        if self.peek() is None:
            raise ValueError("unterminated class")
        char = self.take()
        if char == "\\":
            if self.peek() is None:
                raise ValueError("unterminated class")
            return self.take()
        return char

    def parse_class(self):
        negated = False
        if self.peek() == "^":
            negated = True
            self.take()
        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        while True:
            if self.peek() is None:
                raise ValueError("unterminated class")
            if self.peek() == "]":
                if not chars and not ranges:
                    raise ValueError("empty class")
                self.take()
                return ("class", negated, frozenset(chars), ranges)
            low = self.class_char()
            if self.peek() == "-" and self.peek(1) not in (None, "]"):
                self.take()
                high = self.class_char()
                if low > high:
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                chars.add(low)


class _Compiler:
    """状態は [種類, 判定, out1, out2] のリスト。断片は (開始状態, 未接続の出口 [(状態, 添字)])。"""

    def __init__(self):
        self.states: list[list] = []

    def add(self, kind, test=None):
        self.states.append([kind, test, None, None])
        return len(self.states) - 1

    def patch(self, outs, target):
        for state, slot in outs:
            self.states[state][slot] = target

    def build(self, node):
        kind = node[0]
        if kind == "lit":
            state = self.add(CHAR, (lambda char, lit=node[1]: char == lit))
            return state, [(state, 2)]
        if kind == "any":
            state = self.add(ANY)
            return state, [(state, 2)]
        if kind == "bol":
            state = self.add(BOL)
            return state, [(state, 2)]
        if kind == "eol":
            state = self.add(EOL)
            return state, [(state, 2)]
        if kind == "class":
            _, negated, chars, ranges = node

            def test(char, negated=negated, chars=chars, ranges=ranges):
                hit = char in chars or any(low <= char <= high for low, high in ranges)
                return hit != negated

            state = self.add(CHAR, test)
            return state, [(state, 2)]
        if kind == "seq":
            if not node[1]:
                state = self.add(EPS)
                return state, [(state, 2)]
            start, outs = self.build(node[1][0])
            for item in node[1][1:]:
                next_start, next_outs = self.build(item)
                self.patch(outs, next_start)
                outs = next_outs
            return start, outs
        if kind == "alt":
            start, outs = self.build(node[1][0])
            for item in node[1][1:]:
                other_start, other_outs = self.build(item)
                split = self.add(SPLIT)
                self.states[split][2] = start
                self.states[split][3] = other_start
                start, outs = split, outs + other_outs
            return start, outs
        if kind == "star":
            inner_start, inner_outs = self.build(node[1])
            split = self.add(SPLIT)
            self.states[split][2] = inner_start
            self.patch(inner_outs, split)
            return split, [(split, 3)]
        if kind == "plus":
            inner_start, inner_outs = self.build(node[1])
            split = self.add(SPLIT)
            self.states[split][2] = inner_start
            self.patch(inner_outs, split)
            return inner_start, [(split, 3)]
        if kind == "opt":
            inner_start, inner_outs = self.build(node[1])
            split = self.add(SPLIT)
            self.states[split][2] = inner_start
            return split, inner_outs + [(split, 3)]
        raise ValueError(f"unknown node {kind}")


def _compile(pattern: str):
    tree = _Parser(pattern).parse()
    compiler = _Compiler()
    start, outs = compiler.build(tree)
    match = compiler.add(MATCH)
    compiler.patch(outs, match)
    return start, compiler.states


def _closure(states, seeds, position, length, mark, generation):
    """ε 遷移（分岐・空・アサーション）をたどり、文字を消費する状態と MATCH だけを返す。"""

    result = []
    stack = list(seeds)
    while stack:
        state = stack.pop()
        if mark[state] == generation:
            continue
        mark[state] = generation
        kind, _, out1, out2 = states[state]
        if kind == SPLIT:
            stack.append(out1)
            stack.append(out2)
        elif kind == EPS:
            stack.append(out1)
        elif kind == BOL:
            if position == 0:
                stack.append(out1)
        elif kind == EOL:
            if position == length:
                stack.append(out1)
        else:
            result.append(state)
    return result


def regex_search(pattern: str, text: str) -> bool:
    start, states = _compile(pattern)
    length = len(text)
    mark = [0] * len(states)
    generation = 1
    current = _closure(states, [start], 0, length, mark, generation)
    for position in range(length + 1):
        if any(states[state][0] == MATCH for state in current):
            return True
        if position == length:
            break
        char = text[position]
        seeds = [start]
        for state in current:
            kind, test, out1, _ = states[state]
            if kind == ANY or (kind == CHAR and test(char)):
                seeds.append(out1)
        generation += 1
        current = _closure(states, seeds, position + 1, length, mark, generation)
    return False
