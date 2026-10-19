```python
from collections import deque

_QUANTIFIERS = "*+?"


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str):
        raise ValueError("alphabet must be a string")
    if len(alphabet) == 0:
        raise ValueError("empty alphabet")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("duplicate character in alphabet")


class _Parser:
    """Parses a pattern and builds the Glushkov (position) automaton.

    Fragments are tuples (nullable, first_bits, last_bits); position 0 is
    reserved for the start state.
    """

    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.length = len(pattern)
        self.pos = 0
        self.alphabet = alphabet
        self.alpha_set = frozenset(alphabet)
        self.char_index = {ch: idx for idx, ch in enumerate(alphabet)}
        self.follow = [0]
        self.masks = [0] * len(alphabet)

    def _new_position(self, chars):
        position = len(self.follow)
        self.follow.append(0)
        bit = 1 << position
        for ch in chars:
            self.masks[self.char_index[ch]] |= bit
        return (False, bit, bit)

    def _add_follow(self, last, first):
        if not first:
            return
        follow = self.follow
        bits = last
        while bits:
            low = bits & -bits
            follow[low.bit_length() - 1] |= first
            bits ^= low

    def _concat(self, left, right):
        self._add_follow(left[2], right[1])
        first = left[1] | (right[1] if left[0] else 0)
        last = right[2] | (left[2] if right[0] else 0)
        return (left[0] and right[0], first, last)

    def _apply_quantifier(self, atom, quantifier):
        nullable, first, last = atom
        if quantifier == "*":
            self._add_follow(last, first)
            return (True, first, last)
        if quantifier == "+":
            self._add_follow(last, first)
            return (nullable, first, last)
        return (True, first, last)

    def parse(self):
        fragment = self._parse_alt()
        if self.pos < self.length:
            raise ValueError("unbalanced parenthesis")
        return fragment

    def _parse_alt(self):
        fragment = self._parse_cat()
        while self.pos < self.length and self.pattern[self.pos] == "|":
            self.pos += 1
            other = self._parse_cat()
            fragment = (
                fragment[0] or other[0],
                fragment[1] | other[1],
                fragment[2] | other[2],
            )
        return fragment

    def _parse_cat(self):
        pattern = self.pattern
        length = self.length
        fragment = (True, 0, 0)
        while self.pos < length:
            ch = pattern[self.pos]
            if ch == "|" or ch == ")":
                break
            if ch in _QUANTIFIERS:
                raise ValueError("nothing to repeat")
            atom = self._parse_atom()
            if self.pos < length and pattern[self.pos] in _QUANTIFIERS:
                quantifier = pattern[self.pos]
                self.pos += 1
                if self.pos < length and pattern[self.pos] in _QUANTIFIERS:
                    raise ValueError("multiple repeat")
                atom = self._apply_quantifier(atom, quantifier)
            fragment = self._concat(fragment, atom)
        return fragment

    def _parse_atom(self):
        pattern = self.pattern
        ch = pattern[self.pos]
        if ch == "(":
            self.pos += 1
            inner = self._parse_alt()
            if self.pos >= self.length or pattern[self.pos] != ")":
                raise ValueError("missing )")
            self.pos += 1
            return inner
        if ch == ".":
            self.pos += 1
            return self._new_position(self.alphabet)
        if ch == "\\":
            if self.pos + 1 >= self.length:
                raise ValueError("bad escape at end of pattern")
            literal = pattern[self.pos + 1]
            self.pos += 2
            return self._new_position([literal] if literal in self.alpha_set else [])
        if ch == "[":
            return self._parse_class()
        self.pos += 1
        return self._new_position([ch] if ch in self.alpha_set else [])

    def _class_char(self, index):
        pattern = self.pattern
        if index >= self.length:
            raise ValueError("unterminated character class")
        ch = pattern[index]
        if ch == "\\":
            if index + 1 >= self.length:
                raise ValueError("bad escape in character class")
            return pattern[index + 1], index + 2
        return ch, index + 1

    def _parse_class(self):
        pattern = self.pattern
        length = self.length
        index = self.pos + 1
        negate = False
        if index < length and pattern[index] == "^":
            negate = True
            index += 1
        chosen = set()
        item_count = 0
        while True:
            if index >= length:
                raise ValueError("unterminated character class")
            if pattern[index] == "]":
                break
            low_char, index = self._class_char(index)
            if index + 1 < length and pattern[index] == "-" and pattern[index + 1] != "]":
                high_char, index = self._class_char(index + 1)
                if ord(low_char) > ord(high_char):
                    raise ValueError("bad character range")
                for letter in self.alphabet:
                    if low_char <= letter <= high_char:
                        chosen.add(letter)
            else:
                if low_char in self.alpha_set:
                    chosen.add(low_char)
            item_count += 1
        if item_count == 0:
            raise ValueError("empty character class")
        self.pos = index + 1
        if negate:
            chars = [letter for letter in self.alphabet if letter not in chosen]
        else:
            chars = [letter for letter in self.alphabet if letter in chosen]
        return self._new_position(chars)


def _build_dfa(pattern, alphabet):
    parser = _Parser(pattern, alphabet)
    nullable, first, last = parser.parse()
    follow = parser.follow
    follow[0] = first
    accept_mask = last | (1 if nullable else 0)
    masks = parser.masks
    index_of = {1: 0}
    subsets = [1]
    delta = []
    current = 0
    while current < len(subsets):
        subset = subsets[current]
        reach = 0
        bits = subset
        while bits:
            low = bits & -bits
            reach |= follow[low.bit_length() - 1]
            bits ^= low
        row = []
        for mask in masks:
            target = reach & mask
            target_index = index_of.get(target)
            if target_index is None:
                target_index = len(subsets)
                index_of[target] = target_index
                subsets.append(target)
            row.append(target_index)
        delta.append(row)
        current += 1
    accept = [bool(subset & accept_mask) for subset in subsets]
    return delta, accept


def _hopcroft(delta, accept, letter_count):
    state_count = len(delta)
    inverse = [[[] for _ in range(state_count)] for _ in range(letter_count)]
    for state, row in enumerate(delta):
        for letter in range(letter_count):
            inverse[letter][row[letter]].append(state)
    block_of = [0] * state_count
    blocks = []
    accepting = [state for state in range(state_count) if accept[state]]
    rejecting = [state for state in range(state_count) if not accept[state]]
    for group in (accepting, rejecting):
        if group:
            block_id = len(blocks)
            blocks.append(set(group))
            for state in group:
                block_of[state] = block_id
    pending = set()
    stack = []
    if len(blocks) == 2:
        first_id = 0 if len(blocks[0]) <= len(blocks[1]) else 1
        pending.add(first_id)
        stack.append(first_id)
    while stack:
        splitter = stack.pop()
        pending.discard(splitter)
        splitter_states = list(blocks[splitter])
        for letter in range(letter_count):
            inverse_letter = inverse[letter]
            touched = {}
            for target in splitter_states:
                predecessors = inverse_letter[target]
                for state in predecessors:
                    block_id = block_of[state]
                    members = touched.get(block_id)
                    if members is None:
                        touched[block_id] = [state]
                    else:
                        members.append(state)
            for block_id, members in touched.items():
                block = blocks[block_id]
                if len(members) == len(block):
                    continue
                new_id = len(blocks)
                block.difference_update(members)
                blocks.append(set(members))
                for state in members:
                    block_of[state] = new_id
                if block_id in pending:
                    pending.add(new_id)
                    stack.append(new_id)
                else:
                    chosen = new_id if len(members) <= len(block) else block_id
                    pending.add(chosen)
                    stack.append(chosen)
    return block_of, len(blocks)


def _minimal_dfa(pattern, alphabet):
    delta, accept = _build_dfa(pattern, alphabet)
    block_of, count = _hopcroft(delta, accept, len(alphabet))
    min_delta = [None] * count
    min_accept = [False] * count
    for state, row in enumerate(delta):
        block_id = block_of[state]
        if min_delta[block_id] is None:
            min_delta[block_id] = [block_of[target] for target in row]
            min_accept[block_id] = accept[state]
    return block_of[0], min_delta, min_accept


def min_dfa_size(pattern: str, alphabet: str) -> int:
    _check_alphabet(alphabet)
    delta, accept = _build_dfa(pattern, alphabet)
    _, count = _hopcroft(delta, accept, len(alphabet))
    return count


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    start1, delta1, accept1 = _minimal_dfa(p1, alphabet)
    start2, delta2, accept2 = _minimal_dfa(p2, alphabet)
    letter_count = len(alphabet)
    width = len(delta2)
    start_key = start1 * width + start2
    parent = {start_key: None}
    queue = deque([start_key])
    while queue:
        key = queue.popleft()
        state1, state2 = divmod(key, width)
        if accept1[state1] != accept2[state2]:
            letters = []
            current = key
            while parent[current] is not None:
                previous, letter = parent[current]
                letters.append(alphabet[letter])
                current = previous
            letters.reverse()
            return "".join(letters)
        row1 = delta1[state1]
        row2 = delta2[state2]
        for letter in range(letter_count):
            next_key = row1[letter] * width + row2[letter]
            if next_key not in parent:
                parent[next_key] = (key, letter)
                queue.append(next_key)
    return None
```
