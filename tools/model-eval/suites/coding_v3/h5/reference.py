"""H5 の参照解（構文木 → Thompson の NFA → 部分集合構成の完全な DFA → Moore の分割で最小化、区別は積の幅優先探索）。"""


class _Parser:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.alphabet = alphabet
        self.position = 0

    def peek(self, offset=0):
        index = self.position + offset
        return self.pattern[index] if index < len(self.pattern) else None

    def take(self):
        char = self.pattern[self.position]
        self.position += 1
        return char

    def parse(self):
        tree = self.alternation()
        if self.position != len(self.pattern):
            raise ValueError("unbalanced parenthesis")
        return tree

    def alternation(self):
        branches = [self.sequence()]
        while self.peek() == "|":
            self.take()
            branches.append(self.sequence())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def sequence(self):
        items = []
        while self.peek() not in (None, "|", ")"):
            items.append(self.piece())
        return ("seq", items)

    def piece(self):
        atom = self.atom()
        if self.peek() in ("*", "+", "?"):
            quantifier = self.take()
            if self.peek() in ("*", "+", "?"):
                raise ValueError("multiple repeat")
            return ({"*": "star", "+": "plus", "?": "opt"}[quantifier], atom)
        return atom

    def atom(self):
        char = self.take()
        if char == "(":
            inner = self.alternation()
            if self.peek() != ")":
                raise ValueError("missing )")
            self.take()
            return inner
        if char == ")":
            raise ValueError("unbalanced )")
        if char == "[":
            return self.char_class()
        if char == ".":
            return ("set", frozenset(self.alphabet))
        if char == "\\":
            if self.peek() is None:
                raise ValueError("trailing backslash")
            return ("set", frozenset({self.take()}) & frozenset(self.alphabet))
        if char in ("*", "+", "?"):
            raise ValueError("nothing to repeat")
        return ("set", frozenset({char}) & frozenset(self.alphabet))

    def class_char(self):
        if self.peek() is None:
            raise ValueError("unterminated class")
        char = self.take()
        if char == "\\":
            if self.peek() is None:
                raise ValueError("unterminated class")
            return self.take()
        return char

    def char_class(self):
        negated = False
        if self.peek() == "^":
            negated = True
            self.take()
        members = set()
        items = 0
        while True:
            if self.peek() is None:
                raise ValueError("unterminated class")
            if self.peek() == "]":
                if not items:
                    raise ValueError("empty class")
                self.take()
                chosen = {ch for ch in self.alphabet if (ch in members) != negated}
                return ("set", frozenset(chosen))
            low = self.class_char()
            items += 1
            if self.peek() == "-" and self.peek(1) not in (None, "]"):
                self.take()
                high = self.class_char()
                if low > high:
                    raise ValueError("bad range")
                members.update(ch for ch in self.alphabet if low <= ch <= high)
            else:
                members.add(low)


class _NFA:
    def __init__(self):
        self.eps = []
        self.edges = []  # 状態 → [(文字の集合, 行き先)]

    def new(self):
        self.eps.append([])
        self.edges.append([])
        return len(self.eps) - 1

    def build(self, node):
        """(入口, 出口) を返す。"""

        kind = node[0]
        if kind == "set":
            start, end = self.new(), self.new()
            if node[1]:
                self.edges[start].append((node[1], end))
            return start, end
        if kind == "seq":
            start = end = self.new()
            for item in node[1]:
                s, e = self.build(item)
                self.eps[end].append(s)
                end = e
            return start, end
        if kind == "alt":
            start, end = self.new(), self.new()
            for branch in node[1]:
                s, e = self.build(branch)
                self.eps[start].append(s)
                self.eps[e].append(end)
            return start, end
        s, e = self.build(node[1])
        start, end = self.new(), self.new()
        self.eps[start].append(s)
        self.eps[e].append(end)
        if kind in ("star", "opt"):
            self.eps[start].append(end)
        if kind in ("star", "plus"):
            self.eps[e].append(s)
        return start, end


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or not alphabet or len(set(alphabet)) != len(alphabet):
        raise ValueError("bad alphabet")


def _dfa(pattern, alphabet):
    """完全な DFA: (遷移の表 [状態][文字の添字], 受理の表, 開始 0)。"""

    tree = _Parser(pattern, alphabet).parse()
    nfa = _NFA()
    start, accept = nfa.build(tree)

    def closure(states):
        stack = list(states)
        seen = set(states)
        while stack:
            for nxt in nfa.eps[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return frozenset(seen)

    first = closure({start})
    index = {first: 0}
    order = [first]
    table = []
    pos = 0
    while pos < len(order):
        current = order[pos]
        pos += 1
        row = []
        for ch in alphabet:
            moved = {dst for st in current for chars, dst in nfa.edges[st] if ch in chars}
            target = closure(moved) if moved else frozenset()
            if target not in index:
                index[target] = len(order)
                order.append(target)
            row.append(index[target])
        table.append(row)
    accepting = [accept in subset for subset in order]
    return table, accepting


def _minimize_count(table, accepting):
    block = [1 if acc else 0 for acc in accepting]
    count = len(set(block))
    while True:
        signatures = {}
        new_block = []
        for state, row in enumerate(table):
            key = (block[state],) + tuple(block[t] for t in row)
            if key not in signatures:
                signatures[key] = len(signatures)
            new_block.append(signatures[key])
        if len(signatures) == count:
            return count
        block, count = new_block, len(signatures)


def min_dfa_size(pattern, alphabet):
    _check_alphabet(alphabet)
    table, accepting = _dfa(pattern, alphabet)
    return _minimize_count(table, accepting)


def distinguish(p1, p2, alphabet):
    _check_alphabet(alphabet)
    t1, a1 = _dfa(p1, alphabet)
    t2, a2 = _dfa(p2, alphabet)
    start = (0, 0)
    parent = {start: None}
    queue = [start]
    pos = 0
    while pos < len(queue):
        state = queue[pos]
        pos += 1
        if a1[state[0]] != a2[state[1]]:
            chars = []
            while parent[state] is not None:
                state, ch = parent[state]
                chars.append(ch)
            return "".join(reversed(chars))
        for k, ch in enumerate(alphabet):
            nxt = (t1[state[0]][k], t2[state[1]][k])
            if nxt not in parent:
                parent[nxt] = (state, ch)
                queue.append(nxt)
    return None
