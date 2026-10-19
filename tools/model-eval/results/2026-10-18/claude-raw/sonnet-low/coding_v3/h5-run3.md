```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0 or len(set(alphabet)) != len(alphabet):
        raise ValueError("bad alphabet")
    if len(alphabet) > 8:
        raise ValueError("bad alphabet")


class _NFA:
    def __init__(self):
        self.eps = []
        self.trans = []

    def new(self):
        self.eps.append(set())
        self.trans.append({})
        return len(self.eps) - 1


def _build_nfa(pattern, alphabet):
    nfa = _NFA()
    alpha_set = set(alphabet)
    n = len(pattern)
    pos = [0]

    def empty_frag():
        s = nfa.new()
        e = nfa.new()
        nfa.eps[s].add(e)
        return s, e

    def set_frag(chars):
        s = nfa.new()
        e = nfa.new()
        for ch in chars:
            nfa.trans[s].setdefault(ch, set()).add(e)
        return s, e

    def read_class_char():
        if pos[0] >= n:
            raise ValueError("unclosed class")
        ch = pattern[pos[0]]
        if ch == "\\":
            pos[0] += 1
            if pos[0] >= n:
                raise ValueError("dangling escape")
            ch = pattern[pos[0]]
        pos[0] += 1
        return ch

    def parse_class():
        # pos is just after '['
        negate = False
        if pos[0] < n and pattern[pos[0]] == "^":
            negate = True
            pos[0] += 1
        listed = set()
        count = 0
        while True:
            if pos[0] >= n:
                raise ValueError("unclosed class")
            if pattern[pos[0]] == "]":
                pos[0] += 1
                break
            first = read_class_char()
            if (pos[0] + 1 < n and pattern[pos[0]] == "-"
                    and pattern[pos[0] + 1] != "]"):
                pos[0] += 1
                last = read_class_char()
                if first > last:
                    raise ValueError("bad range")
                for ch in alphabet:
                    if first <= ch <= last:
                        listed.add(ch)
            else:
                listed.add(first)
            count += 1
        if count == 0:
            raise ValueError("empty class")
        if negate:
            return alpha_set - listed
        return alpha_set & listed

    def parse_alt():
        frags = [parse_seq()]
        while pos[0] < n and pattern[pos[0]] == "|":
            pos[0] += 1
            frags.append(parse_seq())
        if len(frags) == 1:
            return frags[0]
        s = nfa.new()
        e = nfa.new()
        for fs, fe in frags:
            nfa.eps[s].add(fs)
            nfa.eps[fe].add(e)
        return s, e

    def parse_seq():
        result = None
        while pos[0] < n and pattern[pos[0]] not in "|)":
            ch = pattern[pos[0]]
            if ch in "*+?":
                raise ValueError("nothing to repeat")
            if ch == "(":
                pos[0] += 1
                frag = parse_alt()
                if pos[0] >= n or pattern[pos[0]] != ")":
                    raise ValueError("unbalanced (")
                pos[0] += 1
            elif ch == "[":
                pos[0] += 1
                frag = set_frag(parse_class())
            elif ch == ".":
                pos[0] += 1
                frag = set_frag(alpha_set)
            elif ch == "\\":
                pos[0] += 1
                if pos[0] >= n:
                    raise ValueError("dangling escape")
                lit = pattern[pos[0]]
                pos[0] += 1
                frag = set_frag({lit} & alpha_set)
            else:
                pos[0] += 1
                frag = set_frag({ch} & alpha_set)
            if pos[0] < n and pattern[pos[0]] in "*+?":
                q = pattern[pos[0]]
                pos[0] += 1
                s1, e1 = frag
                if q == "*":
                    s = nfa.new()
                    e = nfa.new()
                    nfa.eps[s].update((s1, e))
                    nfa.eps[e1].update((s1, e))
                    frag = (s, e)
                elif q == "+":
                    e = nfa.new()
                    nfa.eps[e1].update((s1, e))
                    frag = (s1, e)
                else:
                    s = nfa.new()
                    e = nfa.new()
                    nfa.eps[s].update((s1, e))
                    nfa.eps[e1].add(e)
                    frag = (s, e)
                if pos[0] < n and pattern[pos[0]] in "*+?":
                    raise ValueError("repeated quantifier")
            if result is None:
                result = frag
            else:
                nfa.eps[result[1]].add(frag[0])
                result = (result[0], frag[1])
        if result is None:
            result = empty_frag()
        return result

    start, end = parse_alt()
    if pos[0] < n:
        raise ValueError("unbalanced )")
    return nfa, start, end


def _build_min_dfa(pattern, alphabet):
    nfa, start, end = _build_nfa(pattern, alphabet)
    count = len(nfa.eps)
    closure = []
    for state in range(count):
        seen = {state}
        stack = [state]
        while stack:
            cur = stack.pop()
            for nxt in nfa.eps[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        closure.append(frozenset(seen))

    start_set = closure[start]
    index = {start_set: 0}
    sets = [start_set]
    table = []
    queue = deque([start_set])
    while queue:
        cur = queue.popleft()
        row = []
        for ch in alphabet:
            target = set()
            for state in cur:
                dests = nfa.trans[state].get(ch)
                if dests:
                    for dest in dests:
                        target |= closure[dest]
            target = frozenset(target)
            if target not in index:
                index[target] = len(sets)
                sets.append(target)
                queue.append(target)
            row.append(index[target])
        table.append(row)
    size = len(sets)
    accepting = [end in sets[i] for i in range(size)]

    # Moore partition refinement
    block = [1 if accepting[i] else 0 for i in range(size)]
    num_blocks = len(set(block))
    while True:
        signature_ids = {}
        new_block = [0] * size
        for i in range(size):
            sig = (block[i],) + tuple(block[t] for t in table[i])
            if sig not in signature_ids:
                signature_ids[sig] = len(signature_ids)
            new_block[i] = signature_ids[sig]
        new_count = len(signature_ids)
        block = new_block
        if new_count == num_blocks:
            break
        num_blocks = new_count

    min_table = [None] * num_blocks
    min_accept = [False] * num_blocks
    for i in range(size):
        b = block[i]
        if min_table[b] is None:
            min_table[b] = [block[t] for t in table[i]]
            min_accept[b] = accepting[i]
    return block[0], min_table, min_accept


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    _, table, _ = _build_min_dfa(pattern, alphabet)
    return len(table)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    start1, table1, acc1 = _build_min_dfa(p1, alphabet)
    start2, table2, acc2 = _build_min_dfa(p2, alphabet)
    first = (start1, start2)
    if acc1[start1] != acc2[start2]:
        return ""
    parent = {first: None}
    queue = deque([first])
    while queue:
        pair = queue.popleft()
        for idx, ch in enumerate(alphabet):
            nxt = (table1[pair[0]][idx], table2[pair[1]][idx])
            if nxt in parent:
                continue
            parent[nxt] = (pair, ch)
            if acc1[nxt[0]] != acc2[nxt[1]]:
                chars = []
                cur = nxt
                while parent[cur] is not None:
                    cur, letter = parent[cur]
                    chars.append(letter)
                return "".join(reversed(chars))
            queue.append(nxt)
    return None
```
