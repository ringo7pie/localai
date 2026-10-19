```python
from collections import deque


def _check_alphabet(alphabet):
    if not isinstance(alphabet, str):
        raise ValueError("alphabet must be a string")
    if len(alphabet) == 0:
        raise ValueError("alphabet must not be empty")
    if len(set(alphabet)) != len(alphabet):
        raise ValueError("alphabet must not contain duplicates")


class _NfaBuilder:
    def __init__(self, pattern, alphabet):
        self.pattern = pattern
        self.alphabet = alphabet
        self.full_mask = (1 << len(alphabet)) - 1
        self.position = 0
        self.epsilon = []
        self.edges = []
        self.letter_index = {ch: index for index, ch in enumerate(alphabet)}

    def new_state(self):
        self.epsilon.append([])
        self.edges.append([])
        return len(self.epsilon) - 1

    def link(self, source, target):
        self.epsilon[source].append(target)

    def mask_fragment(self, mask):
        start = self.new_state()
        end = self.new_state()
        if mask:
            self.edges[start].append((mask, end))
        return start, end

    def literal_mask(self, ch):
        index = self.letter_index.get(ch)
        if index is None:
            return 0
        return 1 << index

    def parse(self):
        fragment = self.parse_alternation()
        if self.position != len(self.pattern):
            raise ValueError("unbalanced )")
        return fragment

    def parse_alternation(self):
        branches = [self.parse_concatenation()]
        while (self.position < len(self.pattern)
               and self.pattern[self.position] == "|"):
            self.position += 1
            branches.append(self.parse_concatenation())
        if len(branches) == 1:
            return branches[0]
        start = self.new_state()
        end = self.new_state()
        for branch_start, branch_end in branches:
            self.link(start, branch_start)
            self.link(branch_end, end)
        return start, end

    def parse_concatenation(self):
        fragments = []
        while (self.position < len(self.pattern)
               and self.pattern[self.position] not in "|)"):
            fragments.append(self.parse_quantified())
        if not fragments:
            state = self.new_state()
            return state, state
        for index in range(len(fragments) - 1):
            self.link(fragments[index][1], fragments[index + 1][0])
        return fragments[0][0], fragments[-1][1]

    def parse_quantified(self):
        fragment = self.parse_atom()
        pattern = self.pattern
        if self.position < len(pattern) and pattern[self.position] in "*+?":
            operator = pattern[self.position]
            self.position += 1
            if self.position < len(pattern) and pattern[self.position] in "*+?":
                raise ValueError("repeated quantifier")
            inner_start, inner_end = fragment
            start = self.new_state()
            end = self.new_state()
            self.link(start, inner_start)
            self.link(inner_end, end)
            if operator in "*?":
                self.link(start, end)
            if operator in "*+":
                self.link(inner_end, inner_start)
            fragment = (start, end)
        return fragment

    def parse_atom(self):
        pattern = self.pattern
        length = len(pattern)
        char = pattern[self.position]
        if char in "*+?":
            raise ValueError("nothing to repeat")
        if char == "(":
            self.position += 1
            fragment = self.parse_alternation()
            if self.position >= length or pattern[self.position] != ")":
                raise ValueError("unbalanced (")
            self.position += 1
            return fragment
        if char == "[":
            return self.mask_fragment(self.parse_class())
        if char == ".":
            self.position += 1
            return self.mask_fragment(self.full_mask)
        if char == "\\":
            if self.position + 1 >= length:
                raise ValueError("trailing backslash")
            escaped = pattern[self.position + 1]
            self.position += 2
            return self.mask_fragment(self.literal_mask(escaped))
        self.position += 1
        return self.mask_fragment(self.literal_mask(char))

    def parse_class(self):
        pattern = self.pattern
        length = len(pattern)
        position = self.position + 1
        negate = False
        if position < length and pattern[position] == "^":
            negate = True
            position += 1
        ranges = []
        while True:
            if position >= length:
                raise ValueError("unclosed class")
            char = pattern[position]
            if char == "]":
                position += 1
                break
            if char == "\\":
                if position + 1 >= length:
                    raise ValueError("unclosed class")
                low = pattern[position + 1]
                position += 2
            else:
                low = char
                position += 1
            if (position + 1 < length and pattern[position] == "-"
                    and pattern[position + 1] != "]"):
                position += 1
                char = pattern[position]
                if char == "\\":
                    if position + 1 >= length:
                        raise ValueError("unclosed class")
                    high = pattern[position + 1]
                    position += 2
                else:
                    high = char
                    position += 1
                if low > high:
                    raise ValueError("bad range")
                ranges.append((low, high))
            else:
                ranges.append((low, low))
        if not ranges:
            raise ValueError("empty class")
        self.position = position
        mask = 0
        for index, ch in enumerate(self.alphabet):
            for low, high in ranges:
                if low <= ch <= high:
                    mask |= 1 << index
                    break
        if negate:
            mask = self.full_mask & ~mask
        return mask


def _build_dfa(pattern, alphabet):
    _check_alphabet(alphabet)
    builder = _NfaBuilder(pattern, alphabet)
    start, accept = builder.parse()
    letter_count = len(alphabet)
    state_count = len(builder.epsilon)

    important = 1 << accept
    for state in range(state_count):
        if builder.edges[state]:
            important |= 1 << state

    kept = []
    for state in range(state_count):
        seen = 1 << state
        stack = [state]
        while stack:
            current = stack.pop()
            for following in builder.epsilon[current]:
                if not (seen >> following) & 1:
                    seen |= 1 << following
                    stack.append(following)
        kept.append(seen & important)

    moves = [[0] * state_count for _ in range(letter_count)]
    for state in range(state_count):
        for mask, target in builder.edges[state]:
            for letter in range(letter_count):
                if (mask >> letter) & 1:
                    moves[letter][state] |= kept[target]

    start_mask = kept[start]
    index_of = {start_mask: 0}
    masks = [start_mask]
    delta = []
    cursor = 0
    while cursor < len(masks):
        current_mask = masks[cursor]
        row = []
        for letter in range(letter_count):
            letter_moves = moves[letter]
            following_mask = 0
            remaining = current_mask
            while remaining:
                lowest = remaining & -remaining
                following_mask |= letter_moves[lowest.bit_length() - 1]
                remaining ^= lowest
            following_index = index_of.get(following_mask)
            if following_index is None:
                following_index = len(masks)
                index_of[following_mask] = following_index
                masks.append(following_mask)
            row.append(following_index)
        delta.append(row)
        cursor += 1
    accepting = [bool((mask >> accept) & 1) for mask in masks]
    return delta, accepting, letter_count


def _minimize(delta, accepting, letter_count):
    state_count = len(delta)
    accepting_states = [s for s in range(state_count) if accepting[s]]
    rejecting_states = [s for s in range(state_count) if not accepting[s]]
    if not accepting_states or not rejecting_states:
        return [[0] * letter_count], [accepting[0]], 0

    members = [accepting_states, rejecting_states]
    block_of = [0] * state_count
    for state in rejecting_states:
        block_of[state] = 1

    inverse = [[[] for _ in range(state_count)] for _ in range(letter_count)]
    for state in range(state_count):
        row = delta[state]
        for letter in range(letter_count):
            inverse[letter][row[letter]].append(state)

    work = []
    queued = set()
    smaller = 0 if len(members[0]) <= len(members[1]) else 1
    for letter in range(letter_count):
        work.append((smaller, letter))
        queued.add((smaller, letter))

    while work:
        block_id, letter = work.pop()
        queued.discard((block_id, letter))
        touched = {}
        letter_inverse = inverse[letter]
        for target in members[block_id]:
            for source in letter_inverse[target]:
                touched.setdefault(block_of[source], []).append(source)
        for other, hit in touched.items():
            if len(hit) == len(members[other]):
                continue
            hit_set = set(hit)
            rest = [s for s in members[other] if s not in hit_set]
            new_id = len(members)
            members[other] = rest
            members.append(hit)
            for state in hit:
                block_of[state] = new_id
            for next_letter in range(letter_count):
                if (other, next_letter) in queued:
                    work.append((new_id, next_letter))
                    queued.add((new_id, next_letter))
                else:
                    chosen = other if len(rest) <= len(hit) else new_id
                    work.append((chosen, next_letter))
                    queued.add((chosen, next_letter))

    new_delta = []
    new_accepting = []
    for block in members:
        representative = block[0]
        new_delta.append([block_of[delta[representative][letter]]
                          for letter in range(letter_count)])
        new_accepting.append(accepting[representative])
    return new_delta, new_accepting, block_of[0]


def _minimal_dfa(pattern, alphabet):
    delta, accepting, letter_count = _build_dfa(pattern, alphabet)
    return _minimize(delta, accepting, letter_count)


def min_dfa_size(pattern: str, alphabet: str) -> int:
    delta, _accepting, _start = _minimal_dfa(pattern, alphabet)
    return len(delta)


def distinguish(p1: str, p2: str, alphabet: str) -> str | None:
    _check_alphabet(alphabet)
    delta1, accepting1, start1 = _minimal_dfa(p1, alphabet)
    delta2, accepting2, start2 = _minimal_dfa(p2, alphabet)
    letter_count = len(alphabet)
    size2 = len(delta2)

    start_key = start1 * size2 + start2
    parents = {start_key: None}
    queue = deque([(start1, start2)])
    while queue:
        first, second = queue.popleft()
        key = first * size2 + second
        if accepting1[first] != accepting2[second]:
            letters = []
            while parents[key] is not None:
                key, letter = parents[key]
                letters.append(alphabet[letter])
            letters.reverse()
            return "".join(letters)
        row1 = delta1[first]
        row2 = delta2[second]
        for letter in range(letter_count):
            next_first = row1[letter]
            next_second = row2[letter]
            next_key = next_first * size2 + next_second
            if next_key not in parents:
                parents[next_key] = (key, letter)
                queue.append((next_first, next_second))
    return None
```
