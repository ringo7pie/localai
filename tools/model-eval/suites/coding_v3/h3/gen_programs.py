"""H3 の照合用: 乱数で式を作り、必要なところにだけ括弧を付けた文字列にする（作成時と tests/test_hard.py が使う）。

構文が正しく、定義されていない名前を含まないプログラムだけを作る（型の誤りと名前の誤りが両方あるときに、どちらを先に
出すかは問題文で決めていないため。2026-10-18 に、計測を始めたあとで直した）。
"""

import random

PREC = {"top": 0, "=": 1, "<": 1, "::": 2, "+": 3, "-": 3, "*": 4, "app": 5, "atom": 6}
NAMES = ["x", "y", "f", "g", "h", "p", "q", "l", "n", "k"]
BUILTINS = ["fst", "snd", "hd", "tl", "null"]


def gen(rng, depth, scope):
    if depth <= 0 or rng.random() < 0.18:
        choice = rng.random()
        if choice < 0.45 and scope:
            return ("var", rng.choice(scope))
        if choice < 0.6:
            return ("var", rng.choice(BUILTINS))
        if choice < 0.75:
            return ("int", str(rng.randint(0, 9)))
        if choice < 0.85:
            return ("bool", rng.choice(["true", "false"]))
        return ("nil",)
    kind = rng.choice(["fun", "fun", "let", "let", "letrec", "if", "op", "op", "app", "app", "app", "pair"])
    if kind == "fun":
        params = [rng.choice(NAMES) for _ in range(rng.randint(1, 2))]
        return ("fun", params, gen(rng, depth - 1, scope + params))
    if kind == "let":
        name = rng.choice(NAMES)
        params = [rng.choice(NAMES) for _ in range(rng.randint(0, 2))]
        return ("let", name, params, gen(rng, depth - 1, scope + params), gen(rng, depth - 1, scope + [name]))
    if kind == "letrec":
        name = rng.choice(NAMES)
        params = [rng.choice(NAMES) for _ in range(rng.randint(1, 2))]
        return ("letrec", name, params, gen(rng, depth - 1, scope + [name] + params), gen(rng, depth - 1, scope + [name]))
    if kind == "if":
        return ("if", gen(rng, depth - 1, scope), gen(rng, depth - 1, scope), gen(rng, depth - 1, scope))
    if kind == "op":
        return ("op", rng.choice(["=", "<", "::", "+", "-", "*"]), gen(rng, depth - 1, scope), gen(rng, depth - 1, scope))
    if kind == "pair":
        return ("pair", gen(rng, depth - 1, scope), gen(rng, depth - 1, scope))
    return ("app", gen(rng, depth - 1, scope), gen(rng, depth - 1, scope))


def prec(node):
    kind = node[0]
    if kind in ("fun", "let", "letrec", "if"):
        return 0
    if kind == "op":
        return PREC[node[1]]
    if kind == "app":
        return 5
    return 6


def show(node, rng=None):
    def wrap(text, need):
        if need or (rng is not None and rng.random() < 0.05):
            return "(" + text + ")"
        return text

    kind = node[0]
    if kind in ("int", "bool"):
        return node[1]
    if kind == "var":
        return node[1]
    if kind == "nil":
        return "[]"
    if kind == "pair":
        return "(" + show(node[1], rng) + ", " + show(node[2], rng) + ")"
    if kind == "fun":
        return "fun " + " ".join(node[1]) + " -> " + show(node[2], rng)
    if kind == "let":
        return "let " + " ".join([node[1]] + node[2]) + " = " + show(node[3], rng) + " in " + show(node[4], rng)
    if kind == "letrec":
        return "let rec " + " ".join([node[1]] + node[2]) + " = " + show(node[3], rng) + " in " + show(node[4], rng)
    if kind == "if":
        # 条件の位置には fun / let / if を括弧なしで書けないので包む
        cond = show(node[1], rng)
        return "if " + (f"({cond})" if prec(node[1]) == 0 else cond) + " then " + show(node[2], rng) + " else " + show(node[3], rng)
    if kind == "app":
        left, right = node[1], node[2]
        return wrap(show(left, rng), prec(left) < 5) + " " + wrap(show(right, rng), prec(right) < 6)
    op, left, right = node[1], node[2], node[3]
    p = PREC[op]
    if op == "::":
        need_left, need_right = prec(left) <= p, prec(right) < p or prec(right) == 0
    else:
        need_left, need_right = prec(left) < p or prec(left) == 0, prec(right) <= p
    return wrap(show(left, rng), need_left) + " " + op + " " + wrap(show(right, rng), need_right)


def programs(seed, count, depth=5):
    rng = random.Random(seed)
    return [show(gen(rng, depth, []), rng) for _ in range(count)]
