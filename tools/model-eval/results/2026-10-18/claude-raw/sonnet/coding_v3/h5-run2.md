```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str):
        raise ValueError("alphabet must be a string")
    if len(alphabet) == 0 or len(alphabet) > 8:
        raise ValueError("alphabet must have 1 to 8 characters")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet has duplicated characters")


def _build_nfa(pattern, alphabet):
    size = len(alphabet)
    full_mask = (1 << size) - 1
    index_of = {char: position for position, char in enumerate(alphabet)}
    eps = []
    moves = []
    length = len(pattern)
    cursor = 0

    def new_state():
        eps.append([])
        moves.append(None)
        return len(eps) - 1

    def atom_fragment(mask):
        begin = new_state()
        finish = new_state()
        moves[begin] = (mask, finish)
        return begin, finish

    def empty_fragment():
        begin = new_state()
        finish = new_state()
        eps[begin].append(finish)
        return begin, finish

    def read_class_char():
        nonlocal cursor
        char = pattern[cursor]
        if char == "\\":
            if cursor + 1 >= length:
                raise ValueError("trailing backslash")
            char = pattern[cursor + 1]
            cursor += 2
        else:
            cursor += 1
        return ord(char)

    def parse_class():
        nonlocal cursor
        cursor += 1
        negate = False
        if cursor < length and pattern[cursor] == "^":
            negate = True
            cursor += 1
        ranges = []
        while True:
            if cursor >= length:
                raise ValueError("unclosed class")
            if pattern[cursor] == "]":
                cursor += 1
                break
            low = read_class_char()
            high = low
            if (
                cursor + 1 < length
                and pattern[cursor] == "-"
                and pattern[cursor + 1] != "]"
            ):
                cursor += 1
                high = read_class_char()
                if low > high:
                    raise ValueError("bad range")
            ranges.append((low, high))
        if not ranges:
            raise ValueError("empty class")
        mask = 0
        for position, char in enumerate(alphabet):
            code = ord(char)
            inside = False
            for low, high in ranges:
                if low <= code <= high:
                    inside = True
                    break
            if inside != negate:
                mask |= 1 << position
        return mask

    def parse_atom():
        nonlocal cursor
        char = pattern[cursor]
        if char == "(":
            cursor += 1
            fragment = parse_alt()
            if cursor >= length or pattern[cursor] != ")":
                raise ValueError("unbalanced parenthesis")
            cursor += 1
            return fragment
        if char == "[":
            return atom_fragment(parse_class())
        if char == ".":
            cursor += 1
            return atom_fragment(full_mask)
        if char == "\\":
            if cursor + 1 >= length:
                raise ValueError("trailing backslash")
            literal = pattern[cursor + 1]
            cursor += 2
        else:
            literal = char
            cursor += 1
        if literal in index_of:
            return atom_fragment(1 << index_of[literal])
        return atom_fragment(0)

    def parse_quantified():
        nonlocal cursor
        if pattern[cursor] in "*+?":
            raise ValueError("nothing to repeat")
        begin, finish = parse_atom()
        if cursor < length and pattern[cursor] in "*+?":
            quantifier = pattern[cursor]
            cursor += 1
            if cursor < length and pattern[cursor] in "*+?":
                raise ValueError("multiple repeat")
            outer_begin = new_state()
            outer_finish = new_state()
            if quantifier == "*":
                eps[outer_begin].extend([begin, outer_finish])
                eps[finish].extend([begin, outer_finish])
            elif quantifier == "+":
                eps[outer_begin].append(begin)
                eps[finish].extend([begin, outer_finish])
            else:
                eps[outer_begin].extend([begin, outer_finish])
                eps[finish].append(outer_finish)
            return outer_begin, outer_finish
        return begin, finish

    def parse_seq():
        nonlocal cursor
        result = None
        while cursor < length and pattern[cursor] not in "|)":
            item = parse_quantified()
            if result is None:
                result = item
            else:
                eps[result[1]].append(item[0])
                result = (result[0], item[1])
        if result is None:
            result = empty_fragment()
        return result

    def parse_alt():
        nonlocal cursor
        branches = [parse_seq()]
        while cursor < length and pattern[cursor] == "|":
            cursor += 1
            branches.append(parse_seq())
        if len(branches) == 1:
            return branches[0]
        begin = new_state()
        finish = new_state()
        for branch_begin, branch_finish in branches:
            eps[begin].append(branch_begin)
            eps[branch_finish].append(finish)
        return begin, finish

    start_state, final_state = parse_alt()
    if cursor != length:
        raise ValueError("unbalanced parenthesis")
    return eps, moves, start_state, final_state


def _determinize(pattern, alphabet):
    size = len(alphabet)
    eps, moves, start_state, final_state = _build_nfa(pattern, alphabet)
    important = {}
    for state, move in enumerate(moves):
        if move is not None:
            important[state] = len(important)
    if final_state not in important:
        important[final_state] = len(important)
    cache = {}

    def closure(state):
        if state in cache:
            return cache[state]
        seen = {state}
        stack = [state]
        mask = 0
        while stack:
            current = stack.pop()
            bit = important.get(current)
            if bit is not None:
                mask |= 1 << bit
            for following in eps[current]:
                if following not in seen:
                    seen.add(following)
                    stack.append(following)
        cache[state] = mask
        return mask

    sparse = [None] * len(important)
    for state, bit in important.items():
        entries = []
        move = moves[state]
        if move is not None:
            symbol_mask, target = move
            reach = closure(target)
            for symbol in range(size):
                if (symbol_mask >> symbol) & 1:
                    entries.append((symbol, reach))
        sparse[bit] = entries
    final_bit = 1 << important[final_state]
    start_mask = closure(start_state)
    ids = {start_mask: 0}
    subsets = [start_mask]
    trans = []
    position = 0
    while position < len(subsets):
        subset = subsets[position]
        position += 1
        targets = [0] * size
        rest = subset
        while rest:
            low = rest & -rest
            rest ^= low
            for symbol, reach in sparse[low.bit_length() - 1]:
                targets[symbol] |= reach
        row = []
        for target in targets:
            identifier = ids.get(target)
            if identifier is None:
                identifier = len(subsets)
                ids[target] = identifier
                subsets.append(target)
            row.append(identifier)
        trans.append(row)
    accept = [bool(subset & final_bit) for subset in subsets]
    return trans, accept


def _minimize(trans, accept, size):
    count = len(trans)
    inverse = [[[] for _ in range(count)] for _ in range(size)]
    for state in range(count):
        row = trans[state]
        for symbol in range(size):
            inverse[symbol][row[symbol]].append(state)
    accepting = set(state for state in range(count) if accept[state])
    rejecting = set(range(count)) - accepting
    blocks = [group for group in (accepting, rejecting) if group]
    block_of = [0] * count
    for block_id, group in enumerate(blocks):
        for state in group:
            block_of[state] = block_id
    pending = []
    queued = set()
    if len(blocks) == 2:
        smaller = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        for symbol in range(size):
            pending.append((smaller, symbol))
            queued.add((smaller, symbol))
    while pending:
        block_id, symbol = pending.pop()
        queued.discard((block_id, symbol))
        splitter = list(blocks[block_id])
        predecessors = set()
        for target in splitter:
            predecessors.update(inverse[symbol][target])
        groups = {}
        for state in predecessors:
            groups.setdefault(block_of[state], []).append(state)
        for victim, members in groups.items():
            block = blocks[victim]
            if len(members) == len(block):
                continue
            new_id = len(blocks)
            moved = set(members)
            block -= moved
            blocks.append(moved)
            for state in members:
                block_of[state] = new_id
            for other in range(size):
                if (victim, other) in queued:
                    pending.append((new_id, other))
                    queued.add((new_id, other))
                else:
                    pick = victim if len(block) <= len(moved) else new_id
                    pending.append((pick, other))
                    queued.add((pick, other))
    min_trans = []
    min_accept = []
    for group in blocks:
        representative = next(iter(group))
        min_trans.append([block_of[target] for target in trans[representative]])
        min_accept.append(accept[representative])
    return min_trans, min_accept, block_of[0]


def _minimal_dfa(pattern, alphabet):
    trans, accept = _determinize(pattern, alphabet)
    return _minimize(trans, accept, len(alphabet))


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    min_trans, _, _ = _minimal_dfa(pattern, alphabet)
    return len(min_trans)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    trans1, accept1, start1 = _minimal_dfa(p1, alphabet)
    trans2, accept2, start2 = _minimal_dfa(p2, alphabet)
    size = len(alphabet)
    if accept1[start1] != accept2[start2]:
        return ""
    start = (start1, start2)
    parent = {start: None}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        left, right = current
        for symbol in range(size):
            following = (trans1[left][symbol], trans2[right][symbol])
            if following in parent:
                continue
            parent[following] = (current, symbol)
            if accept1[following[0]] != accept2[following[1]]:
                chars = []
                node = following
                while parent[node] is not None:
                    previous, used = parent[node]
                    chars.append(alphabet[used])
                    node = previous
                return "".join(reversed(chars))
            queue.append(following)
    return None
```
