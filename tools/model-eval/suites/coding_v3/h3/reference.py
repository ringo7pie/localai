"""H3 infer の参照解（再帰下降の構文解析 + レベル付きの単一化による Hindley–Milner）。

入れ子 300 段に耐えるよう、再帰の上限を一時的に上げる。型変数は書き換え可能な箱（union-find）で、
let の一般化はレベル（Rémy の方法）で決める。
"""

import sys

KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
SYMBOLS = ("->", "::", "(", ")", ",", "+", "-", "*", "=", "<", "[")


def tokenize(src):
    tokens = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n\r":
            i += 1
        elif ch.isdigit() and ch.isascii():
            j = i
            while j < n and src[j].isascii() and src[j].isdigit():
                j += 1
            tokens.append(("int", src[i:j]))
            i = j
        elif ch == "_" or ("a" <= ch <= "z"):
            j = i + 1
            while j < n and (src[j] == "_" or src[j] == "'" or (src[j].isascii() and src[j].isalnum())):
                j += 1
            word = src[i:j]
            tokens.append(("kw", word) if word in KEYWORDS else ("id", word))
            i = j
        else:
            for sym in SYMBOLS:
                if src.startswith(sym, i):
                    if sym == "[":
                        k = i + 1
                        if k < n and src[k] == "]":
                            tokens.append(("sym", "[]"))
                            i = k + 1
                            break
                        raise SyntaxError("'[' must be followed by ']'")
                    tokens.append(("sym", sym))
                    i += len(sym)
                    break
            else:
                raise SyntaxError(f"bad character {ch!r}")
    tokens.append(("eof", ""))
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def take(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind, value):
        token = self.take()
        if token != (kind, value):
            raise SyntaxError(f"expected {value!r}, got {token[1]!r}")

    def ident(self):
        token = self.take()
        if token[0] != "id":
            raise SyntaxError(f"expected a name, got {token[1]!r}")
        return token[1]

    def parse(self):
        expr = self.expr()
        if self.peek()[0] != "eof":
            raise SyntaxError(f"unexpected {self.peek()[1]!r}")
        return expr

    def expr(self):
        token = self.peek()
        if token == ("kw", "fun"):
            self.take()
            params = [self.ident()]
            while self.peek()[0] == "id":
                params.append(self.ident())
            self.expect("sym", "->")
            body = self.expr()
            for name in reversed(params):
                body = ("fun", name, body)
            return body
        if token == ("kw", "let"):
            self.take()
            recursive = False
            if self.peek() == ("kw", "rec"):
                self.take()
                recursive = True
            name = self.ident()
            params = []
            while self.peek()[0] == "id":
                params.append(self.ident())
            if recursive and not params:
                raise SyntaxError("let rec needs a parameter")
            self.expect("sym", "=")
            value = self.expr()
            self.expect("kw", "in")
            body = self.expr()
            for param in reversed(params):
                value = ("fun", param, value)
            return ("letrec" if recursive else "let", name, value, body)
        if token == ("kw", "if"):
            self.take()
            # 条件の位置（if の直後）には fun / let / if を括弧なしで書けない（問題文の規則）
            cond = self.compare()
            self.expect("kw", "then")
            then = self.expr()
            self.expect("kw", "else")
            other = self.expr()
            return ("if", cond, then, other)
        return self.compare()

    def compare(self):
        left = self.cons()
        while self.peek() in (("sym", "="), ("sym", "<")):
            op = self.take()[1]
            left = ("op", op, left, self.cons())
        return left

    def cons(self):
        left = self.additive()
        if self.peek() == ("sym", "::"):
            self.take()
            return ("op", "::", left, self.cons())
        return left

    def additive(self):
        left = self.multiplicative()
        while self.peek() in (("sym", "+"), ("sym", "-")):
            op = self.take()[1]
            left = ("op", op, left, self.multiplicative())
        return left

    def multiplicative(self):
        left = self.application()
        while self.peek() == ("sym", "*"):
            self.take()
            left = ("op", "*", left, self.application())
        return left

    def starts_atom(self):
        kind, value = self.peek()
        return kind in ("int", "id") or (kind, value) in (("kw", "true"), ("kw", "false"), ("sym", "("), ("sym", "[]"))

    def application(self):
        expr = self.atom()
        while self.starts_atom():
            expr = ("app", expr, self.atom())
        return expr

    def atom(self):
        kind, value = self.take()
        if kind == "int":
            return ("int",)
        if kind == "id":
            return ("var", value)
        if (kind, value) in (("kw", "true"), ("kw", "false")):
            return ("bool",)
        if (kind, value) == ("sym", "[]"):
            return ("nil",)
        if (kind, value) == ("sym", "("):
            first = self.expr()
            if self.peek() == ("sym", ","):
                self.take()
                second = self.expr()
                self.expect("sym", ")")
                return ("pair", first, second)
            self.expect("sym", ")")
            return first
        raise SyntaxError(f"unexpected {value!r}")


class TVar:
    __slots__ = ("link", "level", "generic")

    def __init__(self, level):
        self.link = None
        self.level = level
        self.generic = False


def con(name, *args):
    return (name,) + args


def prune(t):
    while isinstance(t, TVar) and t.link is not None:
        t = t.link
    return t


def occurs_adjust(var, t):
    """var が t に現れるか調べ、t の型変数のレベルを var のレベル以下に下げる。"""

    stack = [t]
    while stack:
        cur = prune(stack.pop())
        if isinstance(cur, TVar):
            if cur is var:
                return True
            if cur.level > var.level:
                cur.level = var.level
        else:
            stack.extend(cur[1:])
    return False


def unify(a, b):
    stack = [(a, b)]
    while stack:
        x, y = stack.pop()
        x, y = prune(x), prune(y)
        if x is y:
            continue
        if isinstance(x, TVar):
            if occurs_adjust(x, y):
                raise TypeError("recursive type")
            x.link = y
            continue
        if isinstance(y, TVar):
            stack.append((y, x))
            continue
        if x[0] != y[0] or len(x) != len(y):
            raise TypeError(f"cannot unify {x[0]} with {y[0]}")
        stack.extend(zip(x[1:], y[1:]))


def instantiate(t, level):
    mapping = {}

    def go(cur):
        cur = prune(cur)
        if isinstance(cur, TVar):
            if cur.generic:
                if cur not in mapping:
                    mapping[cur] = TVar(level)
                return mapping[cur]
            return cur
        if len(cur) == 1:
            return cur
        return (cur[0],) + tuple(go(arg) for arg in cur[1:])

    return go(t)


def generalize(t, level):
    stack = [t]
    while stack:
        cur = prune(stack.pop())
        if isinstance(cur, TVar):
            if cur.level > level:
                cur.generic = True
        else:
            stack.extend(cur[1:])


INT, BOOL = con("int"), con("bool")


def builtins():
    env = {}

    def scheme(build):
        a, b = TVar(1), TVar(1)
        a.generic = b.generic = True
        return build(a, b)

    env["fst"] = scheme(lambda a, b: con("->", con("*", a, b), a))
    env["snd"] = scheme(lambda a, b: con("->", con("*", a, b), b))
    env["hd"] = scheme(lambda a, b: con("->", con("list", a), a))
    env["tl"] = scheme(lambda a, b: con("->", con("list", a), con("list", a)))
    env["null"] = scheme(lambda a, b: con("->", con("list", a), BOOL))
    return env


def infer_expr(expr, env, level):
    kind = expr[0]
    if kind == "int":
        return INT
    if kind == "bool":
        return BOOL
    if kind == "nil":
        return con("list", TVar(level))
    if kind == "var":
        if expr[1] not in env:
            raise NameError(expr[1])
        return instantiate(env[expr[1]], level)
    if kind == "pair":
        first = infer_expr(expr[1], env, level)
        second = infer_expr(expr[2], env, level)
        return con("*", first, second)
    if kind == "fun":
        param = TVar(level)
        inner = dict(env)
        inner[expr[1]] = param
        body = infer_expr(expr[2], inner, level)
        return con("->", param, body)
    if kind == "app":
        fn = infer_expr(expr[1], env, level)
        arg = infer_expr(expr[2], env, level)
        result = TVar(level)
        unify(fn, con("->", arg, result))
        return result
    if kind == "if":
        cond = infer_expr(expr[1], env, level)
        then = infer_expr(expr[2], env, level)
        other = infer_expr(expr[3], env, level)
        unify(cond, BOOL)
        unify(then, other)
        return then
    if kind == "op":
        op = expr[1]
        left = infer_expr(expr[2], env, level)
        right = infer_expr(expr[3], env, level)
        if op in "+-*":
            unify(left, INT)
            unify(right, INT)
            return INT
        if op == "<":
            unify(left, INT)
            unify(right, INT)
            return BOOL
        if op == "=":
            unify(left, right)
            return BOOL
        unify(right, con("list", left))
        return right
    if kind == "let":
        value = infer_expr(expr[2], env, level + 1)
        generalize(value, level)
        inner = dict(env)
        inner[expr[1]] = value
        return infer_expr(expr[3], inner, level)
    if kind == "letrec":
        self_type = TVar(level + 1)
        inner = dict(env)
        inner[expr[1]] = self_type
        value = infer_expr(expr[2], inner, level + 1)
        unify(self_type, value)
        generalize(value, level)
        body_env = dict(env)
        body_env[expr[1]] = value
        return infer_expr(expr[3], body_env, level)
    raise AssertionError(kind)


LETTERS = "abcdefghijklmnopqrstuvwxyz"


def show(t):
    names = {}

    def name(var):
        if var not in names:
            index = len(names)
            names[var] = "'" + LETTERS[index % 26] + (str(index // 26) if index >= 26 else "")
        return names[var]

    def go(cur, context):
        cur = prune(cur)
        if isinstance(cur, TVar):
            return name(cur)
        head = cur[0]
        if head in ("int", "bool"):
            return head
        if head == "list":
            inner = go(cur[1], "list")
            text = inner + " list"
            return text
        if head == "*":
            left = go(cur[1], "pair")
            right = go(cur[2], "pair")
            text = f"{left} * {right}"
            return f"({text})" if context in ("pair", "list") else text
        left = go(cur[1], "arrow_left")
        right = go(cur[2], "arrow_right")
        text = f"{left} -> {right}"
        return f"({text})" if context in ("pair", "list", "arrow_left") else text

    return go(t, "top")


def infer(src):
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 20000))
    try:
        tree = Parser(tokenize(src)).parse()
        return show(infer_expr(tree, builtins(), 1))
    finally:
        sys.setrecursionlimit(old_limit)
