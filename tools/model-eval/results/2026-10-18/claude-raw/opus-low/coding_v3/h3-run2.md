```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 10 ** 9


def _tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n\r":
            i += 1
            continue
        if ch.isdigit() and ch.isascii():
            j = i
            while j < n and src[j].isascii() and src[j].isdigit():
                j += 1
            toks.append(("int", int(src[i:j])))
            i = j
            continue
        if ("a" <= ch <= "z") or ch == "_":
            j = i + 1
            while j < n and (src[j].isascii() and (src[j].isalnum() or src[j] in "_'")):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append(("kw", word))
            else:
                toks.append(("name", word))
            i = j
            continue
        if src.startswith("->", i):
            toks.append(("sym", "->"))
            i += 2
            continue
        if src.startswith("::", i):
            toks.append(("sym", "::"))
            i += 2
            continue
        if ch == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("nil", None))
                i += 2
                continue
            raise SyntaxError("bad [")
        if ch in "(),+-*=<":
            toks.append(("sym", ch))
            i += 1
            continue
        raise SyntaxError("bad char")
    toks.append(("eof", None))
    return toks


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def next(self):
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind, val=None):
        tok = self.next()
        if tok[0] != kind or (val is not None and tok[1] != val):
            raise SyntaxError("unexpected token")
        return tok

    def is_sym(self, val):
        tok = self.peek()
        return tok[0] == "sym" and tok[1] == val

    def is_kw(self, val):
        tok = self.peek()
        return tok[0] == "kw" and tok[1] == val

    def parse_top(self):
        expr = self.expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("trailing")
        return expr

    def expr(self):
        tok = self.peek()
        if tok[0] == "kw":
            if tok[1] == "fun":
                self.next()
                params = []
                while self.peek()[0] == "name":
                    params.append(self.next()[1])
                if not params:
                    raise SyntaxError("fun needs params")
                self.expect("sym", "->")
                body = self.expr()
                for p in reversed(params):
                    body = ("fun", p, body)
                return body
            if tok[1] == "let":
                self.next()
                rec = False
                if self.is_kw("rec"):
                    self.next()
                    rec = True
                name = self.expect("name")[1]
                params = []
                while self.peek()[0] == "name":
                    params.append(self.next()[1])
                if rec and not params:
                    raise SyntaxError("let rec needs params")
                self.expect("sym", "=")
                e1 = self.expr()
                self.expect("kw", "in")
                e2 = self.expr()
                for p in reversed(params):
                    e1 = ("fun", p, e1)
                return ("letrec" if rec else "let", name, e1, e2)
            if tok[1] == "if":
                self.next()
                c = self.expr()
                self.expect("kw", "then")
                t = self.expr()
                self.expect("kw", "else")
                e = self.expr()
                return ("if", c, t, e)
        return self.cmp()

    def cmp(self):
        left = self.cons()
        while self.is_sym("=") or self.is_sym("<"):
            op = self.next()[1]
            right = self.cons()
            left = ("bin", op, left, right)
        return left

    def cons(self):
        left = self.add()
        if self.is_sym("::"):
            self.next()
            right = self.cons()
            return ("bin", "::", left, right)
        return left

    def add(self):
        left = self.mul()
        while self.is_sym("+") or self.is_sym("-"):
            op = self.next()[1]
            right = self.mul()
            left = ("bin", op, left, right)
        return left

    def mul(self):
        left = self.app()
        while self.is_sym("*"):
            self.next()
            right = self.app()
            left = ("bin", "*", left, right)
        return left

    def starts_atom(self):
        tok = self.peek()
        if tok[0] in ("int", "name", "nil"):
            return True
        if tok[0] == "kw" and tok[1] in ("true", "false"):
            return True
        return tok[0] == "sym" and tok[1] == "("

    def app(self):
        func = self.atom()
        while self.starts_atom():
            arg = self.atom()
            func = ("app", func, arg)
        return func

    def atom(self):
        tok = self.next()
        kind = tok[0]
        if kind == "int":
            return ("int",)
        if kind == "name":
            return ("var", tok[1])
        if kind == "nil":
            return ("nil",)
        if kind == "kw" and tok[1] in ("true", "false"):
            return ("bool",)
        if kind == "sym" and tok[1] == "(":
            first = self.expr()
            if self.is_sym(","):
                self.next()
                second = self.expr()
                self.expect("sym", ")")
                return ("tuple", first, second)
            self.expect("sym", ")")
            return first
        raise SyntaxError("unexpected token")


class _TV:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


_INT = ("int",)
_BOOL = ("bool",)


def _prune(t):
    while isinstance(t, _TV) and t.ref is not None:
        t = t.ref
    return t


def _occurs_adjust(tv, t):
    t = _prune(t)
    if isinstance(t, _TV):
        if t is tv:
            raise TypeError("occurs check")
        if t.level > tv.level:
            t.level = tv.level
        return
    for sub in t[1:]:
        _occurs_adjust(tv, sub)


def _unify(a, b):
    a = _prune(a)
    b = _prune(b)
    if a is b:
        return
    if isinstance(a, _TV):
        _occurs_adjust(a, b)
        a.ref = b
        return
    if isinstance(b, _TV):
        _occurs_adjust(b, a)
        b.ref = a
        return
    if a[0] != b[0] or len(a) != len(b):
        raise TypeError("mismatch")
    for x, y in zip(a[1:], b[1:]):
        _unify(x, y)


def _generalize(t, level):
    t = _prune(t)
    if isinstance(t, _TV):
        if t.level > level:
            t.level = _GENERIC
        return
    for sub in t[1:]:
        _generalize(sub, level)


def _instantiate(t, level, mapping):
    t = _prune(t)
    if isinstance(t, _TV):
        if t.level == _GENERIC:
            nv = mapping.get(id(t))
            if nv is None:
                nv = _TV(level)
                mapping[id(t)] = nv
            return nv
        return t
    if len(t) == 1:
        return t
    return (t[0],) + tuple(_instantiate(sub, level, mapping) for sub in t[1:])


def _builtins():
    env = {}

    def g():
        return _TV(_GENERIC)

    a, b = g(), g()
    env["fst"] = ("->", ("*", a, b), a)
    a, b = g(), g()
    env["snd"] = ("->", ("*", a, b), b)
    a = g()
    env["hd"] = ("->", ("list", a), a)
    a = g()
    env["tl"] = ("->", ("list", a), ("list", a))
    a = g()
    env["null"] = ("->", ("list", a), _BOOL)
    return env


def _infer(env, e, level):
    kind = e[0]
    if kind == "int":
        return _INT
    if kind == "bool":
        return _BOOL
    if kind == "nil":
        return ("list", _TV(level))
    if kind == "var":
        if e[1] not in env:
            raise NameError(e[1])
        return _instantiate(env[e[1]], level, {})
    if kind == "tuple":
        return ("*", _infer(env, e[1], level), _infer(env, e[2], level))
    if kind == "fun":
        tv = _TV(level)
        new_env = dict(env)
        new_env[e[1]] = tv
        body = _infer(new_env, e[2], level)
        return ("->", tv, body)
    if kind == "app":
        ft = _infer(env, e[1], level)
        at = _infer(env, e[2], level)
        rt = _TV(level)
        _unify(ft, ("->", at, rt))
        return rt
    if kind == "if":
        _unify(_infer(env, e[1], level), _BOOL)
        tt = _infer(env, e[2], level)
        et = _infer(env, e[3], level)
        _unify(tt, et)
        return tt
    if kind == "bin":
        op = e[1]
        lt = _infer(env, e[2], level)
        rt = _infer(env, e[3], level)
        if op in ("+", "-", "*"):
            _unify(lt, _INT)
            _unify(rt, _INT)
            return _INT
        if op == "<":
            _unify(lt, _INT)
            _unify(rt, _INT)
            return _BOOL
        if op == "=":
            _unify(lt, rt)
            return _BOOL
        _unify(rt, ("list", lt))
        return rt
    if kind == "let":
        t1 = _infer(env, e[2], level + 1)
        _generalize(t1, level)
        new_env = dict(env)
        new_env[e[1]] = t1
        return _infer(new_env, e[3], level)
    if kind == "letrec":
        tv = _TV(level + 1)
        inner = dict(env)
        inner[e[1]] = tv
        t1 = _infer(inner, e[2], level + 1)
        _unify(tv, t1)
        _generalize(tv, level)
        new_env = dict(env)
        new_env[e[1]] = tv
        return _infer(new_env, e[3], level)
    raise TypeError("unknown")


def _var_name(i):
    letter = chr(ord("a") + i % 26)
    k = i // 26
    return "'" + letter + (str(k) if k else "")


def _show(t, ctx, names):
    t = _prune(t)
    if isinstance(t, _TV):
        key = id(t)
        if key not in names:
            names[key] = _var_name(len(names))
        return names[key]
    head = t[0]
    if head == "int" or head == "bool":
        return head
    if head == "list":
        return _show(t[1], 3, names) + " list"
    if head == "*":
        s = _show(t[1], 2, names) + " * " + _show(t[2], 2, names)
        return "(" + s + ")" if ctx >= 2 else s
    s = _show(t[1], 1, names) + " -> " + _show(t[2], 0, names)
    return "(" + s + ")" if ctx >= 1 else s


def _run(src):
    toks = _tokenize(src)
    ast = _Parser(toks).parse_top()
    t = _infer(_builtins(), ast, 0)
    return _show(t, 0, {})


def infer(src: str) -> str:
    result = {}

    def worker():
        try:
            result["ok"] = _run(src)
        except BaseException as exc:
            result["err"] = exc

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    try:
        sys.setrecursionlimit(max(old_limit, 1000000))
        threading.stack_size(512 * 1024 * 1024)
        th = threading.Thread(target=worker)
        th.start()
        th.join()
    finally:
        threading.stack_size(old_stack)
        sys.setrecursionlimit(old_limit)
    if "err" in result:
        raise result["err"]
    return result["ok"]
```
