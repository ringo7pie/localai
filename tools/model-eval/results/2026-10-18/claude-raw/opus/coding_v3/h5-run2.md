```python
from collections import deque

_QUANTIFIERS = {"*": "star", "+": "plus", "?": "opt"}


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str) or len(alphabet) == 0:
        raise ValueError("alphabet must be a non-empty string")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet has duplicate characters")


class _Parser:
    def __init__(self, pattern, alphabet):
        self.text = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.index_of = {char: idx for idx, char in enumerate(alphabet)}
        self.full_mask = (1 << len(alphabet)) - 1

    def parse(self):
        node = self._parse_alt()
        if self.pos != self.length:
            raise ValueError("unbalanced parenthesis")
        return node

    def _parse_alt(self):
        branches = [self._parse_concat()]
        while self.pos < self.length and self.text[self.pos] == "|":
            self.pos += 1
            branches.append(self._parse_concat())
        if len(branches) == 1:
            return branches[0]
        return ("alt", branches)

    def _parse_concat(self):
        items = []
        while self.pos < self.length:
            char = self.text[self.pos]
            if char == "|" or char == ")":
                break
            if char in "*+?":
                raise ValueError("nothing to repeat")
            atom = self._parse_atom()
            if self.pos < self.length and self.text[self.pos] in "*+?":
                quant = self.text[self.pos]
                self.pos += 1
                if self.pos < self.length and self.text[self.pos] in "*+?":
                    raise ValueError("multiple repeat")
                atom = (_QUANTIFIERS[quant], atom)
            items.append(atom)
        if not items:
            return ("empty",)
        if len(items) == 1:
            return items[0]
        return ("cat", items)

    def _literal(self, char):
        idx = self.index_of.get(char)
        return ("leaf", 0 if idx is None else 1 << idx)

    def _parse_atom(self):
        char = self.text[self.pos]
        if char == "(":
            self.pos += 1
            node = self._parse_alt()
            if self.pos >= self.length or self.text[self.pos] != ")":
                raise ValueError("missing )")
            self.pos += 1
            return node
        if char == "[":
            return self._parse_class()
        if char == ".":
            self.pos += 1
            return ("leaf", self.full_mask)
        if char == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("trailing backslash")
            escaped = self.text[self.pos + 1]
            self.pos += 2
            return self._literal(escaped)
        self.pos += 1
        return self._literal(char)

    def _parse_class(self):
        text = self.text
        length = self.length
        cursor = self.pos + 1
        negate = False
        if cursor < length and text[cursor] == "^":
            negate = True
            cursor += 1
        ranges = []
        while True:
            if cursor >= length:
                raise ValueError("unterminated character class")
            char = text[cursor]
            if char == "]":
                cursor += 1
                break
            if char == "\\":
                if cursor + 1 >= length:
                    raise ValueError("unterminated character class")
                low_char = text[cursor + 1]
                cursor += 2
            else:
                low_char = char
                cursor += 1
            if cursor + 1 < length and text[cursor] == "-" and text[cursor + 1] != "]":
                cursor += 1
                if text[cursor] == "\\":
                    if cursor + 1 >= length:
                        raise ValueError("unterminated character class")
                    high_char = text[cursor + 1]
                    cursor += 2
                else:
                    high_char = text[cursor]
                    cursor += 1
                if ord(low_char) > ord(high_char):
                    raise ValueError("bad character range")
                ranges.append((ord(low_char), ord(high_char)))
            else:
                ranges.append((ord(low_char), ord(low_char)))
        if not ranges:
            raise ValueError("empty character class")
        self.pos = cursor
        mask = 0
        for idx, symbol in enumerate(self.alphabet):
            code = ord(symbol)
            inside = any(low <= code <= high for low, high in ranges)
            if inside != negate:
                mask |= 1 << idx
        return ("leaf", mask)


def _add_follow(follow, last_mask, first_mask):
    if not first_mask:
        return
    while last_mask:
        low_bit = last_mask & -last_mask
        follow[low_bit.bit_length() - 1] |= first_mask
        last_mask ^= low_bit


def _analyze(node, leaf_masks, follow):
    kind = node[0]
    if kind == "leaf":
        position = len(leaf_masks)
        leaf_masks.append(node[1])
        follow.append(0)
        bit = 1 << position
        return False, bit, bit
    if kind == "empty":
        return True, 0, 0
    if kind == "cat":
        nullable, first, last = True, 0, 0
        for child in node[1]:
            child_null, child_first, child_last = _analyze(child, leaf_masks, follow)
            _add_follow(follow, last, child_first)
            if nullable:
                first |= child_first
            if child_null:
                last |= child_last
            else:
                last = child_last
            nullable = nullable and child_null
        return nullable, first, last
    if kind == "alt":
        nullable, first, last = False, 0, 0
        for child in node[1]:
            child_null, child_first, child_last = _analyze(child, leaf_masks, follow)
            nullable = nullable or child_null
            first |= child_first
            last |= child_last
        return nullable, first, last
    child_null, child_first, child_last = _analyze(node[1], leaf_masks, follow)
    if kind == "star":
        _add_follow(follow, child_last, child_first)
        return True, child_first, child_last
    if kind == "plus":
        _add_follow(follow, child_last, child_first)
        return child_null, child_first, child_last
    return True, child_first, child_last


def _build_dfa(pattern, alphabet):
    """Glushkov 自動機械を部分集合構成した完全 DFA（到達可能な状態だけ）。状態 0 が開始。"""
    tree = _Parser(pattern, alphabet).parse()
    leaf_masks = [0]
    follow = [0]
    nullable, first, last = _analyze(tree, leaf_masks, follow)
    follow[0] = first
    accept_mask = last | (1 if nullable else 0)
    position_count = len(follow)
    symbol_count = len(alphabet)

    char_masks = [0] * symbol_count
    for position in range(1, position_count):
        leaf_mask = leaf_masks[position]
        for symbol in range(symbol_count):
            if (leaf_mask >> symbol) & 1:
                char_masks[symbol] |= 1 << position

    tables = []
    for chunk in range((position_count + 7) // 8):
        table = [0] * 256
        base = chunk * 8
        for byte in range(1, 256):
            low_bit = byte & -byte
            position = base + low_bit.bit_length() - 1
            extra = follow[position] if position < position_count else 0
            table[byte] = table[byte ^ low_bit] | extra
        tables.append(table)

    state_ids = {1: 0}
    order = [1]
    transitions = []
    cursor = 0
    while cursor < len(order):
        rest = order[cursor]
        cursor += 1
        reach = 0
        for table in tables:
            if not rest:
                break
            reach |= table[rest & 255]
            rest >>= 8
        row = []
        for char_mask in char_masks:
            target = reach & char_mask
            target_id = state_ids.get(target)
            if target_id is None:
                target_id = len(order)
                state_ids[target] = target_id
                order.append(target)
            row.append(target_id)
        transitions.append(row)
    accepting = [bool(state & accept_mask) for state in order]
    return transitions, accepting


def _minimize(transitions, accepting, symbol_count):
    """Hopcroft のアルゴリズム。(各状態のブロック番号, ブロック数) を返す。"""
    state_count = len(transitions)
    inverse = [[[] for _ in range(state_count)] for _ in range(symbol_count)]
    for state, row in enumerate(transitions):
        for symbol in range(symbol_count):
            inverse[symbol][row[symbol]].append(state)

    blocks = []
    block_of = [0] * state_count
    accept_group = [state for state in range(state_count) if accepting[state]]
    reject_group = [state for state in range(state_count) if not accepting[state]]
    for group in (accept_group, reject_group):
        if group:
            block_id = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = block_id

    work = list(range(len(blocks)))
    in_work = [True] * len(blocks)
    while work:
        splitter_id = work.pop()
        in_work[splitter_id] = False
        splitter = list(blocks[splitter_id])
        for symbol in range(symbol_count):
            inverse_symbol = inverse[symbol]
            touched = {}
            for target in splitter:
                for source in inverse_symbol[target]:
                    block_id = block_of[source]
                    members = touched.get(block_id)
                    if members is None:
                        touched[block_id] = [source]
                    else:
                        members.append(source)
            for block_id, members in touched.items():
                block = blocks[block_id]
                if len(members) == len(block):
                    continue
                new_id = len(blocks)
                new_block = set(members)
                block.difference_update(new_block)
                blocks.append(new_block)
                for state in members:
                    block_of[state] = new_id
                if in_work[block_id]:
                    work.append(new_id)
                    in_work.append(True)
                elif len(new_block) <= len(block):
                    work.append(new_id)
                    in_work.append(True)
                else:
                    in_work.append(False)
                    work.append(block_id)
                    in_work[block_id] = True
    return block_of, len(blocks)


def _minimal_dfa(pattern, alphabet):
    transitions, accepting = _build_dfa(pattern, alphabet)
    symbol_count = len(alphabet)
    block_of, block_count = _minimize(transitions, accepting, symbol_count)
    new_transitions = [None] * block_count
    new_accepting = [False] * block_count
    for state, row in enumerate(transitions):
        block_id = block_of[state]
        if new_transitions[block_id] is None:
            new_transitions[block_id] = [block_of[target] for target in row]
            new_accepting[block_id] = accepting[state]
    return new_transitions, new_accepting, block_of[0]


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    transitions, accepting = _build_dfa(pattern, alphabet)
    _, block_count = _minimize(transitions, accepting, len(alphabet))
    return block_count


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    trans_one, accept_one, start_one = _minimal_dfa(p1, alphabet)
    trans_two, accept_two, start_two = _minimal_dfa(p2, alphabet)
    symbol_count = len(alphabet)
    width = len(trans_two)
    start_key = start_one * width + start_two
    parent = {start_key: None}
    queue = deque([start_key])
    while queue:
        key = queue.popleft()
        state_one, state_two = divmod(key, width)
        if accept_one[state_one] != accept_two[state_two]:
            chars = []
            while parent[key] is not None:
                previous, symbol = parent[key]
                chars.append(alphabet[symbol])
                key = previous
            return "".join(reversed(chars))
        row_one = trans_one[state_one]
        row_two = trans_two[state_two]
        for symbol in range(symbol_count):
            next_key = row_one[symbol] * width + row_two[symbol]
            if next_key not in parent:
                parent[next_key] = (key, symbol)
                queue.append(next_key)
    return None
```
