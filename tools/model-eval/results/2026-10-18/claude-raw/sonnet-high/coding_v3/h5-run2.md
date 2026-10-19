```python
def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) < 1 or len(alphabet) > 8:
        raise ValueError("bad alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate characters in alphabet")


def _parse(pattern, alphabet):
    index_of = {ch: i for i, ch in enumerate(alphabet)}
    full = frozenset(range(len(alphabet)))
    length = len(pattern)
    state = {"pos": 0}

    def literal_node(ch):
        if ch in index_of:
            return ("set", frozenset([index_of[ch]]))
        return ("set", frozenset())

    def read_class_char():
        pos = state["pos"]
        if pos >= length:
            raise ValueError("unclosed class")
        ch = pattern[pos]
        if ch == "\\":
            if pos + 1 >= length:
                raise ValueError("dangling backslash")
            state["pos"] = pos + 2
            return pattern[pos + 1]
        state["pos"] = pos + 1
        return ch

    def parse_class():
        state["pos"] += 1  # '['
        negate = False
        if state["pos"] < length and pattern[state["pos"]] == "^":
            negate = True
            state["pos"] += 1
        members = set()
        items = 0
        while True:
            pos = state["pos"]
            if pos >= length:
                raise ValueError("unclosed class")
            if pattern[pos] == "]":
                state["pos"] += 1
                break
            low = read_class_char()
            pos = state["pos"]
            if pos + 1 < length and pattern[pos] == "-" and pattern[pos + 1] != "]":
                state["pos"] += 1
                high = read_class_char()
                if low > high:
                    raise ValueError("bad range")
                for idx, ch in enumerate(alphabet):
                    if low <= ch <= high:
                        members.add(idx)
            else:
                if low in index_of:
                    members.add(index_of[low])
            items += 1
        if items == 0:
            raise ValueError("empty class")
        if negate:
            return ("set", frozenset(full - members))
        return ("set", frozenset(members))

    def parse_seq(depth):
        items = []
        while state["pos"] < length:
            ch = pattern[state["pos"]]
            if ch == "|":
                break
            if ch == ")":
                if depth == 0:
                    raise ValueError("unbalanced )")
                break
            if ch in "*+?":
                raise ValueError("nothing to repeat")
            if ch == "(":
                state["pos"] += 1
                node = parse_alt(depth + 1)
                if state["pos"] >= length or pattern[state["pos"]] != ")":
                    raise ValueError("unbalanced (")
                state["pos"] += 1
            elif ch == "[":
                node = parse_class()
            elif ch == ".":
                state["pos"] += 1
                node = ("set", full)
            elif ch == "\\":
                if state["pos"] + 1 >= length:
                    raise ValueError("dangling backslash")
                node = literal_node(pattern[state["pos"] + 1])
                state["pos"] += 2
            else:
                state["pos"] += 1
                node = literal_node(ch)
            if state["pos"] < length and pattern[state["pos"]] in "*+?":
                quant = pattern[state["pos"]]
                state["pos"] += 1
                kind = {"*": "star", "+": "plus", "?": "opt"}[quant]
                node = (kind, node)
                if state["pos"] < length and pattern[state["pos"]] in "*+?":
                    raise ValueError("stacked quantifier")
            items.append(node)
        return ("cat", items)

    def parse_alt(depth):
        branches = [parse_seq(depth)]
        while state["pos"] < length and pattern[state["pos"]] == "|":
            state["pos"] += 1
            branches.append(parse_seq(depth))
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    tree = parse_alt(0)
    if state["pos"] != length:
        raise ValueError("unbalanced )")
    return tree


def _build_min_dfa(pattern, alphabet):
    """Return (start, transitions, accepting, state_count) of the minimal complete DFA."""
    _check_alphabet(alphabet)
    tree = _parse(pattern, alphabet)
    symbols = len(alphabet)

    eps = []
    moves = []

    def new_state():
        eps.append([])
        moves.append([[] for _ in range(symbols)])
        return len(eps) - 1

    def build(node):
        kind = node[0]
        if kind == "set":
            start = new_state()
            end = new_state()
            for sym in node[1]:
                moves[start][sym].append(end)
            return start, end
        if kind == "cat":
            items = node[1]
            if not items:
                single = new_state()
                return single, single
            first_start, last_end = build(items[0])
            for item in items[1:]:
                sub_start, sub_end = build(item)
                eps[last_end].append(sub_start)
                last_end = sub_end
            return first_start, last_end
        if kind == "alt":
            start = new_state()
            end = new_state()
            for branch in node[1]:
                sub_start, sub_end = build(branch)
                eps[start].append(sub_start)
                eps[sub_end].append(end)
            return start, end
        sub_start, sub_end = build(node[1])
        start = new_state()
        end = new_state()
        eps[start].append(sub_start)
        eps[sub_end].append(end)
        if kind in ("star", "opt"):
            eps[start].append(end)
        if kind in ("star", "plus"):
            eps[sub_end].append(sub_start)
        return start, end

    nfa_start, nfa_end = build(tree)
    count = len(eps)

    closure = [0] * count
    for origin in range(count):
        seen = 1 << origin
        stack = [origin]
        while stack:
            cur = stack.pop()
            for nxt in eps[cur]:
                bit = 1 << nxt
                if not seen & bit:
                    seen |= bit
                    stack.append(nxt)
        closure[origin] = seen

    relevant = 1 << nfa_end
    for origin in range(count):
        for sym in range(symbols):
            if moves[origin][sym]:
                relevant |= 1 << origin
                break

    target_mask = [[0] * symbols for _ in range(count)]
    for origin in range(count):
        if not (relevant >> origin) & 1:
            continue
        for sym in range(symbols):
            combined = 0
            for nxt in moves[origin][sym]:
                combined |= closure[nxt]
            target_mask[origin][sym] = combined & relevant

    end_bit = 1 << nfa_end
    start_mask = closure[nfa_start] & relevant
    ids = {start_mask: 0}
    masks = [start_mask]
    table = []
    cursor = 0
    while cursor < len(masks):
        current = masks[cursor]
        targets = [0] * symbols
        remaining = current
        while remaining:
            low = remaining & -remaining
            row = target_mask[low.bit_length() - 1]
            for sym in range(symbols):
                targets[sym] |= row[sym]
            remaining ^= low
        row_ids = []
        for sym in range(symbols):
            mask = targets[sym]
            found = ids.get(mask)
            if found is None:
                found = len(masks)
                ids[mask] = found
                masks.append(mask)
            row_ids.append(found)
        table.append(row_ids)
        cursor += 1

    total = len(masks)
    accepting = [bool(mask & end_bit) for mask in masks]

    # Hopcroft minimization
    inverse = [[[] for _ in range(total)] for _ in range(symbols)]
    for src in range(total):
        row = table[src]
        for sym in range(symbols):
            inverse[sym][row[sym]].append(src)

    accept_set = set(i for i in range(total) if accepting[i])
    reject_set = set(i for i in range(total) if not accepting[i])
    blocks = []
    for group in (accept_set, reject_set):
        if group:
            blocks.append(group)
    block_of = [0] * total
    for block_id, group in enumerate(blocks):
        for item in group:
            block_of[item] = block_id

    work = []
    in_work = set()
    if len(blocks) == 2:
        smaller = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        for sym in range(symbols):
            work.append((smaller, sym))
            in_work.add((smaller, sym))

    while work:
        block_id, sym = work.pop()
        in_work.discard((block_id, sym))
        splitter = list(blocks[block_id])
        sources = set()
        inv_sym = inverse[sym]
        for member in splitter:
            sources.update(inv_sym[member])
        touched = {}
        for item in sources:
            touched.setdefault(block_of[item], []).append(item)
        for victim, members in touched.items():
            if len(members) == len(blocks[victim]):
                continue
            new_id = len(blocks)
            new_set = set(members)
            blocks[victim] -= new_set
            blocks.append(new_set)
            for item in members:
                block_of[item] = new_id
            for other in range(symbols):
                if (victim, other) in in_work:
                    in_work.add((new_id, other))
                    work.append((new_id, other))
                else:
                    pick = victim if len(blocks[victim]) <= len(new_set) else new_id
                    if (pick, other) not in in_work:
                        in_work.add((pick, other))
                        work.append((pick, other))

    block_count = len(blocks)
    min_table = []
    min_accept = []
    for group in blocks:
        rep = next(iter(group))
        min_table.append([block_of[table[rep][sym]] for sym in range(symbols)])
        min_accept.append(accepting[rep])
    return block_of[0], min_table, min_accept, block_count


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    return _build_min_dfa(pattern, alphabet)[3]


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    start1, table1, accept1, _ = _build_min_dfa(p1, alphabet)
    start2, table2, accept2, count2 = _build_min_dfa(p2, alphabet)
    symbols = len(alphabet)
    if accept1[start1] != accept2[start2]:
        return ""
    first = start1 * count2 + start2
    parent = {first: None}
    queue = [first]
    cursor = 0
    while cursor < len(queue):
        pair = queue[cursor]
        cursor += 1
        s1, s2 = divmod(pair, count2)
        row1 = table1[s1]
        row2 = table2[s2]
        for sym in range(symbols):
            n1 = row1[sym]
            n2 = row2[sym]
            nxt = n1 * count2 + n2
            if nxt in parent:
                continue
            parent[nxt] = (pair, sym)
            if accept1[n1] != accept2[n2]:
                chars = []
                node = nxt
                while parent[node] is not None:
                    node, via = parent[node]
                    chars.append(alphabet[via])
                chars.reverse()
                return "".join(chars)
            queue.append(nxt)
    return None
```
