```python
import sys
import threading

_RESERVED = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}


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
            toks.append(("int", src[i:j]))
            i = j
            continue
        if ch == "_" or ("a" <= ch <= "z"):
            j = i + 1
            while j < n and (src[j] == "_" or src[j] == "'" or (src[j].isascii() and src[j].isalnum())):
                j += 1
            word = src[i:j]
            if word in _RESERVED:
                toks.append(("kw", word))
            else:
                toks.append(("name", word))
            i = j
            continue
        two = src[i:i + 2]
        if two in ("->", "::"):
            toks.append(("sym", two))
            i += 2
            continue
        if ch == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("nil", "[]"))
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

    def expect(self, kind, val):
        tok = self.next()
        if tok[0] != kind or tok[1] != val:
            raise SyntaxError("expected " + str(val))
        return tok

    def is_tok(self, kind, val):
        tok = self.peek()
        return tok[0] == kind and tok[1] == val

    def parse(self):
        e = self.expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("trailing")
        return e

    def name(self):
        tok = self.next()
        if tok[0] != "name":
            raise SyntaxError("expected name")
        return tok[1]

    def expr(self):
        tok = self.peek()
        if tok[0] == "kw":
            if tok[1] == "fun":
                self.next()
                params = [self.name()]
                while self.peek()[0] == "name":
                    params.append(self.name())
                self.expect("sym", "->")
                body = self.expr()
                for p in reversed(params):
                    body = ("fun", p, body)
                return body
            if tok[1] == "let":
                self.next()
                rec = False
                if self.is_tok("kw", "rec"):
                    self.next()
                    rec = True
                fname = self.name()
                params = []
                while self.peek()[0] == "name":
                    params.append(self.name())
                if rec and not params:
                    raise SyntaxError("rec needs params")
                self.expect("sym", "=")
                e1 = self.expr()
                self.expect("kw", "in")
                e2 = self.expr()
                for p in reversed(params):
                    e1 = ("fun", p, e1)
                return ("letrec" if rec else "let", fname, e1, e2)
            if tok[1] == "if":
                self.next()
                c = self.expr()
                self.expect("kw", "then")
                a = self.expr()
                self.expect("kw", "else")
                b = self.expr()
                return ("if", c, a, b)
        return self.cmp()

    def cmp(self):
        left = self.cons()
        while self.is_tok("sym", "=") or self.is_tok("sym", "<"):
            op = self.next()[1]
            right = self.cons()
            left = ("op", op, left, right)
        return left

    def cons(self):
        left = self.add()
        if self.is_tok("sym", "::"):
            self.next()
            right = self.cons()
            return ("op", "::", left, right)
        return left

    def add(self):
        left = self.mul()
        while self.is_tok("sym", "+") or self.is_tok("sym", "-"):
            op = self.next()[1]
            right = self.mul()
            left = ("op", op, left, right)
        return left

    def mul(self):
        left = self.app()
        while self.is_tok("sym", "*"):
            self.next()
            right = self.app()
            left = ("op", "*", left, right)
        return left

    def starts_atom(self):
        tok = self.peek()
        if tok[0] in ("int", "name", "nil"):
            return True
        if tok[0] == "kw" and tok[1] in ("true", "false"):
            return True
        return tok[0] == "sym" and tok[1] == "("

    def app(self):
        if not self.starts_atom():
            raise SyntaxError("expected expression")
        func = self.atom()
        while self.starts_atom():
            arg = self.atom()
            func = ("app", func, arg)
        return func

    def atom(self):
        tok = self.next()
        if tok[0] == "int":
            return ("int",)
        if tok[0] == "name":
            return ("var", tok[1])
        if tok[0] == "nil":
            return ("nil",)
        if tok[0] == "kw" and tok[1] in ("true", "false"):
            return ("bool",)
        if tok == ("sym", "("):
            e = self.expr()
            if self.is_tok("sym", ","):
                self.next()
                e2 = self.expr()
                self.expect("sym", ")")
                return ("pair", e, e2)
            self.expect("sym", ")")
            return e
        raise SyntaxError("unexpected token")


class _TV:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TC:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


def _prune(t):
    while isinstance(t, _TV) and t.ref is not None:
        t = t.ref
    return t


def _occurs_adjust(tv, t):
    stack = [t]
    while stack:
        cur = _prune(stack.pop())
        if cur is tv:
            raise TypeError("occurs check")
        if isinstance(cur, _TV):
            if cur.level > tv.level:
                cur.level = tv.level
        else:
            stack.extend(cur.args)


def _unify(a, b):
    stack = [(a, b)]
    while stack:
        x, y = stack.pop()
        x = _prune(x)
        y = _prune(y)
        if x is y:
            continue
        if isinstance(x, _TV):
            _occurs_adjust(x, y)
            x.ref = y
        elif isinstance(y, _TV):
            _occurs_adjust(y, x)
            y.ref = x
        else:
            if x.name != y.name or len(x.args) != len(y.args):
                raise TypeError("mismatch")
            for p, q in zip(x.args, y.args):
                stack.append((p, q))


_INT = _TC("int", [])
_BOOL = _TC("bool", [])


def _arrow(a, b):
    return _TC("->", [a, b])


def _lst(a):
    return _TC("list", [a])


def _pair(a, b):
    return _TC("*", [a, b])


def _generalize(t, level):
    gen = set()
    stack = [t]
    while stack:
        cur = _prune(stack.pop())
        if isinstance(cur, _TV):
            if cur.level > level:
                gen.add(cur)
        else:
            stack.extend(cur.args)
    return (gen, t)


def _instantiate(scheme, level):
    gen, t = scheme
    if not gen:
        return t
    mapping = {}

    def copy(x):
        x = _prune(x)
        if isinstance(x, _TV):
            if x in gen:
                if x not in mapping:
                    mapping[x] = _TV(level)
                return mapping[x]
            return x
        if not x.args:
            return x
        return _TC(x.name, [copy(arg) for arg in x.args])

    return copy(t)


def _builtins():
    env = {}

    def mk(build):
        tvs = [_TV(10 ** 9) for _ in range(2)]
        t = build(*tvs)
        return _generalize(t, 0)

    env["fst"] = mk(lambda a, b: _arrow(_pair(a, b), a))
    env["snd"] = mk(lambda a, b: _arrow(_pair(a, b), b))
    env["hd"] = mk(lambda a, b: _arrow(_lst(a), a))
    env["tl"] = mk(lambda a, b: _arrow(_lst(a), _lst(a)))
    env["null"] = mk(lambda a, b: _arrow(_lst(a), _BOOL))
    return env


def _infer(node, env, level):
    kind = node[0]
    if kind == "int":
        return _INT
    if kind == "bool":
        return _BOOL
    if kind == "nil":
        return _lst(_TV(level))
    if kind == "var":
        if node[1] not in env:
            raise NameError(node[1])
        return _instantiate(env[node[1]], level)
    if kind == "pair":
        return _pair(_infer(node[1], env, level), _infer(node[2], env, level))
    if kind == "fun":
        tv = _TV(level)
        new_env = dict(env)
        new_env[node[1]] = (set(), tv)
        body = _infer(node[2], new_env, level)
        return _arrow(tv, body)
    if kind == "app":
        ft = _infer(node[1], env, level)
        at = _infer(node[2], env, level)
        res = _TV(level)
        _unify(ft, _arrow(at, res))
        return res
    if kind == "if":
        ct = _infer(node[1], env, level)
        _unify(ct, _BOOL)
        at = _infer(node[2], env, level)
        bt = _infer(node[3], env, level)
        _unify(at, bt)
        return at
    if kind == "op":
        op = node[1]
        lt = _infer(node[2], env, level)
        rt = _infer(node[3], env, level)
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
        if op == "::":
            _unify(rt, _lst(lt))
            return rt
    if kind == "let":
        t1 = _infer(node[2], env, level + 1)
        new_env = dict(env)
        new_env[node[1]] = _generalize(t1, level)
        return _infer(node[3], new_env, level)
    if kind == "letrec":
        tv = _TV(level + 1)
        rec_env = dict(env)
        rec_env[node[1]] = (set(), tv)
        t1 = _infer(node[2], rec_env, level + 1)
        _unify(tv, t1)
        new_env = dict(env)
        new_env[node[1]] = _generalize(tv, level)
        return _infer(node[3], new_env, level)
    raise TypeError("unknown node")


def _show(t):
    names = {}

    def vname(tv):
        if tv not in names:
            idx = len(names)
            letter = chr(97 + idx % 26)
            suffix = idx // 26
            names[tv] = "'" + letter + (str(suffix) if suffix else "")
        return names[tv]

    def go(x, ctx):
        x = _prune(x)
        if isinstance(x, _TV):
            return vname(x)
        if x.name == "->":
            s = go(x.args[0], 1) + " -> " + go(x.args[1], 0)
            return "(" + s + ")" if ctx >= 1 else s
        if x.name == "*":
            s = go(x.args[0], 2) + " * " + go(x.args[1], 2)
            return "(" + s + ")" if ctx >= 2 else s
        if x.name == "list":
            return go(x.args[0], 2) + " list"
        return x.name

    return go(t, 0)


def _run(src):
    toks = _tokenize(src)
    ast = _Parser(toks).parse()
    t = _infer(ast, _builtins(), 0)
    return _show(t)


def infer(src: str) -> str:
    result = {}

    def worker():
        try:
            result["value"] = _run(src)
        except BaseException as exc:
            result["error"] = exc

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    try:
        sys.setrecursionlimit(max(old_limit, 200000))
        threading.stack_size(512 * 1024 * 1024)
        th = threading.Thread(target=worker)
        th.start()
        th.join()
    finally:
        threading.stack_size(old_stack)
        sys.setrecursionlimit(old_limit)
    if "error" in result:
        err = result["error"]
        if isinstance(err, RecursionError):
            raise SyntaxError("too deep")
        raise err
    return result["value"]
```
