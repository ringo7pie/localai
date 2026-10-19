"""H5 のオラクル（参照解とは別の作り: Brzozowski の微分）。

正規表現を ACI（結合・可換・冪等）で正規化した微分で直接たどり、DFA の状態を「微分した式」にする。
構文は参照解と同じ規則を別の書き方で読む（文字ごとの状態機械ではなく、位置を返す関数の組）。
最小化は「区別できる組」を印付けする表の方法（Myhill–Nerode の表）。区別は短い順の全列挙（小さい入力だけ）。
"""

from itertools import product

EMPTY = ("empty",)   # 空の言語
EPS = ("eps",)       # 空文字列だけ


def chars(s):
    return ("chars", frozenset(s)) if s else EMPTY


def cat(a, b):
    if a == EMPTY or b == EMPTY:
        return EMPTY
    if a == EPS:
        return b
    if b == EPS:
        return a
    if a[0] == "cat":
        return cat(a[1], cat(a[2], b))
    return ("cat", a, b)


def alt(*items):
    flat = set()
    for item in items:
        if item[0] == "alt":
            flat |= item[1]
        elif item != EMPTY:
            flat.add(item)
    if not flat:
        return EMPTY
    if len(flat) == 1:
        return next(iter(flat))
    return ("alt", frozenset(flat))


def star(a):
    if a in (EMPTY, EPS):
        return EPS
    if a[0] == "star":
        return a
    return ("star", a)


def nullable(r):
    kind = r[0]
    if kind in ("eps", "star"):
        return True
    if kind in ("empty", "chars"):
        return False
    if kind == "cat":
        return nullable(r[1]) and nullable(r[2])
    return any(nullable(x) for x in r[1])


def deriv(r, ch):
    kind = r[0]
    if kind in ("empty", "eps"):
        return EMPTY
    if kind == "chars":
        return EPS if ch in r[1] else EMPTY
    if kind == "cat":
        first = cat(deriv(r[1], ch), r[2])
        return alt(first, deriv(r[2], ch)) if nullable(r[1]) else first
    if kind == "star":
        return cat(deriv(r[1], ch), r)
    return alt(*(deriv(x, ch) for x in r[1]))


def parse(pattern, alphabet):
    sigma = set(alphabet)
    n = len(pattern)

    def p_alt(i):
        node, i = p_seq(i)
        options = [node]
        while i < n and pattern[i] == "|":
            node, i = p_seq(i + 1)
            options.append(node)
        return alt(*options), i

    def p_seq(i):
        node = EPS
        while i < n and pattern[i] not in "|)":
            atom, i = p_atom(i)
            if i < n and pattern[i] in "*+?":
                q = pattern[i]
                i += 1
                if i < n and pattern[i] in "*+?":
                    raise ValueError
                atom = star(atom) if q == "*" else cat(atom, star(atom)) if q == "+" else alt(EPS, atom)
            node = cat(node, atom)
        return node, i

    def p_atom(i):
        ch = pattern[i]
        if ch == "(":
            node, j = p_alt(i + 1)
            if j >= n or pattern[j] != ")":
                raise ValueError
            return node, j + 1
        if ch == ")":
            raise ValueError
        if ch in "*+?":
            raise ValueError
        if ch == ".":
            return chars(sigma), i + 1
        if ch == "\\":
            if i + 1 >= n:
                raise ValueError
            return chars({pattern[i + 1]} & sigma), i + 2
        if ch == "[":
            return p_class(i + 1)
        return chars({ch} & sigma), i + 1

    def read(i):
        if i >= n:
            raise ValueError
        if pattern[i] == "\\":
            if i + 1 >= n:
                raise ValueError
            return pattern[i + 1], i + 2
        return pattern[i], i + 1

    def p_class(i):
        neg = i < n and pattern[i] == "^"
        if neg:
            i += 1
        members = set()
        count = 0
        while True:
            if i >= n:
                raise ValueError
            if pattern[i] == "]":
                if count == 0:
                    raise ValueError
                picked = {c for c in sigma if (c in members) != neg}
                return chars(picked), i + 1
            lo, i = read(i)
            count += 1
            if i + 1 < n and pattern[i] == "-" and pattern[i + 1] != "]":
                hi, i = read(i + 1)
                if lo > hi:
                    raise ValueError
                members |= {c for c in sigma if lo <= c <= hi}
            else:
                members.add(lo)

    node, i = p_alt(0)
    if i != n:
        raise ValueError
    return node


def check_alphabet(alphabet):
    if not alphabet or len(set(alphabet)) != len(alphabet):
        raise ValueError


def explore(pattern, alphabet):
    root = parse(pattern, alphabet)
    states = [root]
    index = {root: 0}
    trans = []
    k = 0
    while k < len(states):
        row = []
        for ch in alphabet:
            d = deriv(states[k], ch)
            if d not in index:
                index[d] = len(states)
                states.append(d)
            row.append(index[d])
        trans.append(row)
        k += 1
    return trans, [nullable(s) for s in states]


def min_dfa_size_oracle(pattern, alphabet):
    check_alphabet(alphabet)
    trans, acc = explore(pattern, alphabet)
    n = len(trans)
    marked = [[acc[i] != acc[j] for j in range(n)] for i in range(n)]
    changed = True
    while changed:
        changed = False
        for i in range(n):
            for j in range(i):
                if marked[i][j]:
                    continue
                for a in range(len(alphabet)):
                    x, y = trans[i][a], trans[j][a]
                    if marked[x][y] or marked[y][x]:
                        marked[i][j] = marked[j][i] = True
                        changed = True
                        break
    reps = 0
    for i in range(n):
        if all(marked[i][j] for j in range(i)):
            reps += 1
    return reps


def matches(pattern_tree, word):
    r = pattern_tree
    for ch in word:
        r = deriv(r, ch)
    return nullable(r)


def distinguish_oracle(p1, p2, alphabet, max_len=8):
    check_alphabet(alphabet)
    r1, r2 = parse(p1, alphabet), parse(p2, alphabet)
    for length in range(max_len + 1):
        for word in product(alphabet, repeat=length):
            if matches(r1, word) != matches(r2, word):
                return "".join(word)
    return None
