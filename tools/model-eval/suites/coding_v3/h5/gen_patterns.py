"""H5 の照合用: 乱数のパターン（構文の誤りを含む）を作る（作成時と tests/test_hard.py が使う）。"""

import random

PIECES = ["a", "b", "c", "d", ".", "\\.", "\\a", "[ab]", "[^a]", "[a-c]", "[b-]", "[\\]a]", "^", "$", "x"]


def gen(rng, depth):
    if depth <= 0 or rng.random() < 0.3:
        return rng.choice(PIECES)
    kind = rng.random()
    if kind < 0.35:
        return gen(rng, depth - 1) + gen(rng, depth - 1)
    if kind < 0.55:
        return gen(rng, depth - 1) + "|" + gen(rng, depth - 1)
    if kind < 0.85:
        return "(" + gen(rng, depth - 1) + ")" + rng.choice(["*", "+", "?", ""])
    return gen(rng, depth - 1) + rng.choice(["*", "+", "?"])


def mutate(rng, text):
    if not text or rng.random() < 0.7:
        return text
    i = rng.randrange(len(text) + 1)
    return text[:i] + rng.choice(["(", ")", "*", "|", "[", "]", "\\", "?", "-"]) + text[i:]


def patterns(seed, count, depth=4):
    rng = random.Random(seed)
    return [mutate(rng, gen(rng, depth)) for _ in range(count)]


def alphabets(seed, count):
    rng = random.Random(seed)
    pool = ["ab", "abc", "ba", "cab", "abcd", "a", "dcba"]
    return [rng.choice(pool) for _ in range(count)]
