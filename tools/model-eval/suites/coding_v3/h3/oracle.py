"""H3 のオラクル（参照解とは別の作り）。

- 構文解析: 字句を正規表現で切り、優先順位の表で読む（参照解は関数ごとの再帰下降）
- 型推論: 置換の辞書を持ち回る教科書どおりの Algorithm W（参照解は書き換え可能な箱とレベル）
- 一般化: 環境の自由な型変数を毎回数える
"""

import itertools
import re
import sys

TOKEN = re.compile(r"\s*(?:([0-9]+)|([a-z_][A-Za-z0-9_']*)|(->|::|\[\]|[(),+\-*=<]))")
KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
BINARY = {"=": (1, "left"), "<": (1, "left"), "::": (2, "right"), "+": (3, "left"), "-": (3, "left"),
          "*": (4, "left")}


def lex(src):
    pos, out = 0, []
    src = src.rstrip(" \t\n\r")
    while pos < len(src):
        match = TOKEN.match(src, pos)
        if not match or match.end() == pos:
            raise SyntaxError("lex")
        number, word, sym = match.groups()
        if number is not None:
            out.append(("num", number))
        elif word is not None:
            out.append(("kw" if word in KEYWORDS else "name", word))
        else:
            out.append(("sym", sym))
        pos = match.end()
    return out + [("end", None)]


class P:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def look(self):
        return self.toks[self.i]

    def eat(self, tok=None):
        cur = self.toks[self.i]
        if tok is not None and cur != tok:
            raise SyntaxError(f"want {tok}")
        self.i += 1
        return cur

    def name(self):
        cur = self.eat()
        if cur[0] != "name":
            raise SyntaxError("name")
        return cur[1]

    def full(self):
        node = self.top()
        self.eat(("end", None))
        return node

    def top(self):
        cur = self.look()
        if cur == ("kw", "fun"):
            self.eat()
            names = [self.name()]
            while self.look()[0] == "name":
                names.append(self.name())
            self.eat(("sym", "->"))
            body = self.top()
            for nm in names[::-1]:
                body = ["lam", nm, body]
            return body
        if cur == ("kw", "let"):
            self.eat()
            rec = self.look() == ("kw", "rec")
            if rec:
                self.eat()
            nm = self.name()
            params = []
            while self.look()[0] == "name":
                params.append(self.name())
            if rec and not params:
                raise SyntaxError("rec")
            self.eat(("sym", "="))
            rhs = self.top()
            self.eat(("kw", "in"))
            body = self.top()
            for prm in params[::-1]:
                rhs = ["lam", prm, rhs]
            return ["letrec" if rec else "let", nm, rhs, body]
        if cur == ("kw", "if"):
            self.eat()
            c = self.binary(1)
            self.eat(("kw", "then"))
            a = self.top()
            self.eat(("kw", "else"))
            return ["if", c, a, self.top()]
        return self.binary(1)

    def binary(self, min_prec):
        left = self.apps()
        while True:
            cur = self.look()
            if cur[0] != "sym" or cur[1] not in BINARY:
                return left
            prec, assoc = BINARY[cur[1]]
            if prec < min_prec:
                return left
            self.eat()
            right = self.binary(prec + 1 if assoc == "left" else prec)
            left = ["bin", cur[1], left, right]

    def is_atom_start(self):
        cur = self.look()
        return cur[0] in ("num", "name") or cur in (("kw", "true"), ("kw", "false"), ("sym", "("), ("sym", "[]"))

    def apps(self):
        node = self.atom()
        while self.is_atom_start():
            node = ["app", node, self.atom()]
        return node

    def atom(self):
        cur = self.eat()
        if cur[0] == "num":
            return ["lit", "int"]
        if cur[0] == "name":
            return ["ref", cur[1]]
        if cur in (("kw", "true"), ("kw", "false")):
            return ["lit", "bool"]
        if cur == ("sym", "[]"):
            return ["nil"]
        if cur == ("sym", "("):
            inner = self.top()
            if self.look() == ("sym", ","):
                self.eat()
                second = self.top()
                self.eat(("sym", ")"))
                return ["tup", inner, second]
            self.eat(("sym", ")"))
            return inner
        raise SyntaxError("atom")


# 型: ("v", n) は型変数、("c", 名前, 引数...) は型の構成子
fresh_counter = itertools.count()


def fresh():
    return ("v", next(fresh_counter))


def c(name, *args):
    return ("c", name) + args


def apply(s, t):
    if t[0] == "v":
        return apply(s, s[t[1]]) if t[1] in s else t
    return t[:2] + tuple(apply(s, x) for x in t[2:])


def ftv(t):
    if t[0] == "v":
        return {t[1]}
    out = set()
    for x in t[2:]:
        out |= ftv(x)
    return out


def bind(s, n, t):
    t = apply(s, t)
    if t == ("v", n):
        return s
    if n in ftv(t):
        raise TypeError("occurs")
    s2 = dict(s)
    s2[n] = t
    return s2


def mgu(s, a, b):
    a, b = apply(s, a), apply(s, b)
    if a[0] == "v":
        return bind(s, a[1], b)
    if b[0] == "v":
        return bind(s, b[1], a)
    if a[1] != b[1] or len(a) != len(b):
        raise TypeError("mismatch")
    for x, y in zip(a[2:], b[2:]):
        s = mgu(s, x, y)
    return s


def inst(scheme):
    qs, t = scheme
    m = {q: fresh() for q in qs}
    return apply({k: v for k, v in m.items()}, t)


def env_ftv(s, env):
    out = set()
    for qs, t in env.values():
        out |= ftv(apply(s, t)) - set(qs)
    return out


def gen(s, env, t):
    t = apply(s, t)
    return (tuple(sorted(ftv(t) - env_ftv(s, env))), t)


INTT, BOOLT = c("int"), c("bool")


def w(s, env, node):
    tag = node[0]
    if tag == "lit":
        return s, c(node[1])
    if tag == "nil":
        return s, c("list", fresh())
    if tag == "ref":
        if node[1] not in env:
            raise NameError(node[1])
        return s, inst(env[node[1]])
    if tag == "tup":
        s, a = w(s, env, node[1])
        s, b = w(s, env, node[2])
        return s, c("*", a, b)
    if tag == "lam":
        a = fresh()
        e2 = dict(env)
        e2[node[1]] = ((), a)
        s, body = w(s, e2, node[2])
        return s, c("->", a, body)
    if tag == "app":
        s, f = w(s, env, node[1])
        s, x = w(s, env, node[2])
        r = fresh()
        s = mgu(s, f, c("->", x, r))
        return s, r
    if tag == "if":
        s, cond = w(s, env, node[1])
        s, a = w(s, env, node[2])
        s, b = w(s, env, node[3])
        s = mgu(s, cond, BOOLT)
        s = mgu(s, a, b)
        return s, a
    if tag == "bin":
        op = node[1]
        s, a = w(s, env, node[2])
        s, b = w(s, env, node[3])
        if op in ("+", "-", "*", "<"):
            s = mgu(s, a, INTT)
            s = mgu(s, b, INTT)
            return s, (BOOLT if op == "<" else INTT)
        if op == "=":
            return mgu(s, a, b), BOOLT
        s = mgu(s, b, c("list", a))
        return s, b
    if tag == "let":
        s, a = w(s, env, node[2])
        e2 = dict(env)
        e2[node[1]] = gen(s, env, a)
        return w(s, e2, node[3])
    if tag == "letrec":
        f = fresh()
        e1 = dict(env)
        e1[node[1]] = ((), f)
        s, a = w(s, e1, node[2])
        s = mgu(s, f, a)
        e2 = dict(env)
        e2[node[1]] = gen(s, env, a)
        return w(s, e2, node[3])
    raise AssertionError(tag)


def render(t):
    names = {}

    def nm(n):
        if n not in names:
            k = len(names)
            names[n] = "'" + "abcdefghijklmnopqrstuvwxyz"[k % 26] + (str(k // 26) if k >= 26 else "")
        return names[n]

    def r(t, ctx):
        if t[0] == "v":
            return nm(t[1])
        name = t[1]
        if name in ("int", "bool"):
            return name
        if name == "list":
            return r(t[2], "L") + " list"
        if name == "*":
            text = r(t[2], "P") + " * " + r(t[3], "P")
            return "(" + text + ")" if ctx in ("P", "L") else text
        text = r(t[2], "A") + " -> " + r(t[3], "R")
        return "(" + text + ")" if ctx in ("P", "L", "A") else text

    return r(t, "T")


def builtin_env():
    a, b = ("v", -1), ("v", -2)
    return {
        "fst": ((-1, -2), c("->", c("*", a, b), a)),
        "snd": ((-1, -2), c("->", c("*", a, b), b)),
        "hd": ((-1,), c("->", c("list", a), a)),
        "tl": ((-1,), c("->", c("list", a), c("list", a))),
        "null": ((-1,), c("->", c("list", a), BOOLT)),
    }


def infer_oracle(src):
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 50000))
    try:
        tree = P(lex(src)).full()
        s, t = w({}, builtin_env(), tree)
        return render(apply(s, t))
    finally:
        sys.setrecursionlimit(old)
