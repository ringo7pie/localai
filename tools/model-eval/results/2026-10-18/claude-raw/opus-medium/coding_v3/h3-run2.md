```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 1 << 60


def _tokenize(src):
    toks = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n":
            i += 1
            continue
        if "0" <= c <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            toks.append(("INT", src[i:j]))
            i = j
            continue
        if ("a" <= c <= "z") or c == "_":
            j = i + 1
            while j < n:
                d = src[j]
                if ("a" <= d <= "z") or ("A" <= d <= "Z") or ("0" <= d <= "9") or d == "_" or d == "'":
                    j += 1
                else:
                    break
            word = src[i:j]
            if word in _KEYWORDS:
                toks.append((word, None))
            else:
                toks.append(("NAME", word))
            i = j
            continue
        if c == "-":
            if i + 1 < n and src[i + 1] == ">":
                toks.append(("->", None))
                i += 2
            else:
                toks.append(("-", None))
                i += 1
            continue
        if c == ":":
            if i + 1 < n and src[i + 1] == ":":
                toks.append(("::", None))
                i += 2
                continue
            raise SyntaxError("unexpected ':'")
        if c == "[":
            if i + 1 < n and src[i + 1] == "]":
                toks.append(("[]", None))
                i += 2
                continue
            raise SyntaxError("'[' must be followed by ']'")
        if c in "(),+*=<":
            toks.append((c, None))
            i += 1
            continue
        raise SyntaxError("unexpected character %r" % c)
    toks.append(("EOF", None))
    return toks


_ATOM_START = {"INT", "NAME", "true", "false", "[]", "("}


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos][0]

    def advance(self):
        tok = self.toks[self.pos]
        if tok[0] != "EOF":
            self.pos += 1
        return tok

    def expect(self, kind):
        tok = self.toks[self.pos]
        if tok[0] != kind:
            raise SyntaxError("expected %s" % kind)
        self.advance()
        return tok

    def parse_top(self):
        expr = self.parse_expr()
        if self.peek() != "EOF":
            raise SyntaxError("unexpected token")
        return expr

    def parse_name(self):
        tok = self.toks[self.pos]
        if tok[0] != "NAME":
            raise SyntaxError("expected name")
        self.advance()
        return tok[1]

    def parse_expr(self):
        kind = self.peek()
        if kind == "fun":
            self.advance()
            params = [self.parse_name()]
            while self.peek() == "NAME":
                params.append(self.parse_name())
            self.expect("->")
            body = self.parse_expr()
            for param in reversed(params):
                body = ("fun", param, body)
            return body
        if kind == "let":
            self.advance()
            is_rec = False
            if self.peek() == "rec":
                self.advance()
                is_rec = True
            name = self.parse_name()
            params = []
            while self.peek() == "NAME":
                params.append(self.parse_name())
            if is_rec and not params:
                raise SyntaxError("let rec needs arguments")
            self.expect("=")
            bound = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            for param in reversed(params):
                bound = ("fun", param, bound)
            return ("letrec" if is_rec else "let", name, bound, body)
        if kind == "if":
            self.advance()
            cond = self.parse_expr()
            self.expect("then")
            then_e = self.parse_expr()
            self.expect("else")
            else_e = self.parse_expr()
            return ("if", cond, then_e, else_e)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.peek() in ("=", "<"):
            op = self.advance()[0]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        items = [self.parse_add()]
        while self.peek() == "::":
            self.advance()
            items.append(self.parse_add())
        result = items[-1]
        for item in reversed(items[:-1]):
            result = ("bin", "::", item, result)
        return result

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() in ("+", "-"):
            op = self.advance()[0]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.peek() == "*":
            self.advance()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def parse_app(self):
        func = self.parse_atom()
        while self.peek() in _ATOM_START:
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        tok = self.toks[self.pos]
        kind = tok[0]
        if kind == "INT":
            self.advance()
            return ("int",)
        if kind == "true" or kind == "false":
            self.advance()
            return ("bool",)
        if kind == "NAME":
            self.advance()
            return ("var", tok[1])
        if kind == "[]":
            self.advance()
            return ("nil",)
        if kind == "(":
            self.advance()
            first = self.parse_expr()
            if self.peek() == ",":
                self.advance()
                second = self.parse_expr()
                self.expect(")")
                return ("tuple", first, second)
            self.expect(")")
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
    while type(t) is _TV and t.ref is not None:
        t = t.ref
    return t


def _bind(var, t):
    stack = [t]
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _TV:
            if cur is var:
                raise TypeError("occurs check")
            if cur.level > var.level:
                cur.level = var.level
        else:
            stack.extend(cur[1:])
    var.ref = t


def _unify(a, b):
    stack = [(a, b)]
    while stack:
        x, y = stack.pop()
        x = _prune(x)
        y = _prune(y)
        if x is y:
            continue
        if type(x) is _TV:
            _bind(x, y)
        elif type(y) is _TV:
            _bind(y, x)
        else:
            if x[0] != y[0] or len(x) != len(y):
                raise TypeError("type mismatch")
            for idx in range(1, len(x)):
                stack.append((x[idx], y[idx]))


def _generalize(t, level):
    stack = [t]
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _TV:
            if cur.level > level and cur.level != _GENERIC:
                cur.level = _GENERIC
        else:
            stack.extend(cur[1:])


def _instantiate(t, level):
    memo = {}

    def go(cur):
        cur = _prune(cur)
        if type(cur) is _TV:
            if cur.level == _GENERIC:
                fresh = memo.get(cur)
                if fresh is None:
                    fresh = _TV(level)
                    memo[cur] = fresh
                return fresh
            return cur
        if len(cur) == 1:
            return cur
        if len(cur) == 2:
            return (cur[0], go(cur[1]))
        return (cur[0], go(cur[1]), go(cur[2]))

    return go(t)


def _builtins():
    env = {}
    a = _TV(_GENERIC)
    b = _TV(_GENERIC)
    env["fst"] = ("->", ("*", a, b), a)
    a = _TV(_GENERIC)
    b = _TV(_GENERIC)
    env["snd"] = ("->", ("*", a, b), b)
    a = _TV(_GENERIC)
    env["hd"] = ("->", ("list", a), a)
    a = _TV(_GENERIC)
    env["tl"] = ("->", ("list", a), ("list", a))
    a = _TV(_GENERIC)
    env["null"] = ("->", ("list", a), _BOOL)
    return env


def _infer_expr(env, expr, level):
    tag = expr[0]
    if tag == "int":
        return _INT
    if tag == "bool":
        return _BOOL
    if tag == "var":
        name = expr[1]
        if name not in env:
            raise NameError("undefined name: %s" % name)
        return _instantiate(env[name], level)
    if tag == "nil":
        return ("list", _TV(level))
    if tag == "tuple":
        first = _infer_expr(env, expr[1], level)
        second = _infer_expr(env, expr[2], level)
        return ("*", first, second)
    if tag == "app":
        func_t = _infer_expr(env, expr[1], level)
        arg_t = _infer_expr(env, expr[2], level)
        res = _TV(level)
        _unify(func_t, ("->", arg_t, res))
        return res
    if tag == "bin":
        op = expr[1]
        left = _infer_expr(env, expr[2], level)
        right = _infer_expr(env, expr[3], level)
        if op in ("+", "-", "*"):
            _unify(left, _INT)
            _unify(right, _INT)
            return _INT
        if op == "<":
            _unify(left, _INT)
            _unify(right, _INT)
            return _BOOL
        if op == "=":
            _unify(left, right)
            return _BOOL
        # "::"
        _unify(right, ("list", left))
        return right
    if tag == "fun":
        param_t = _TV(level)
        new_env = dict(env)
        new_env[expr[1]] = param_t
        body_t = _infer_expr(new_env, expr[2], level)
        return ("->", param_t, body_t)
    if tag == "let":
        bound_t = _infer_expr(env, expr[2], level + 1)
        _generalize(bound_t, level)
        new_env = dict(env)
        new_env[expr[1]] = bound_t
        return _infer_expr(new_env, expr[3], level)
    if tag == "letrec":
        self_t = _TV(level + 1)
        inner_env = dict(env)
        inner_env[expr[1]] = self_t
        bound_t = _infer_expr(inner_env, expr[2], level + 1)
        _unify(self_t, bound_t)
        _generalize(self_t, level)
        new_env = dict(env)
        new_env[expr[1]] = self_t
        return _infer_expr(new_env, expr[3], level)
    if tag == "if":
        cond_t = _infer_expr(env, expr[1], level)
        _unify(cond_t, _BOOL)
        then_t = _infer_expr(env, expr[2], level)
        else_t = _infer_expr(env, expr[3], level)
        _unify(then_t, else_t)
        return then_t
    raise SyntaxError("unknown node")


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix else "")


def _format(t):
    names = {}

    def fmt(cur, prec):
        cur = _prune(cur)
        if type(cur) is _TV:
            name = names.get(cur)
            if name is None:
                name = _var_name(len(names))
                names[cur] = name
            return name
        tag = cur[0]
        if tag == "int" or tag == "bool":
            return tag
        if tag == "->":
            text = fmt(cur[1], 1) + " -> " + fmt(cur[2], 0)
            lvl = 0
        elif tag == "*":
            text = fmt(cur[1], 2) + " * " + fmt(cur[2], 2)
            lvl = 1
        else:
            text = fmt(cur[1], 2) + " list"
            lvl = 2
        if lvl < prec:
            return "(" + text + ")"
        return text

    return fmt(t, 0)


def _infer_impl(src):
    toks = _tokenize(src)
    ast = _Parser(toks).parse_top()
    env = _builtins()
    result_t = _infer_expr(env, ast, 0)
    return _format(result_t)


def infer(src: str) -> str:
    if sys.getrecursionlimit() < 1000000:
        sys.setrecursionlimit(1000000)
    box = {}

    def work():
        try:
            box["value"] = _infer_impl(src)
        except BaseException as exc:
            box["error"] = exc

    old_size = None
    try:
        old_size = threading.stack_size(512 * 1024 * 1024)
    except (ValueError, RuntimeError):
        old_size = None
    try:
        worker = threading.Thread(target=work)
        worker.start()
        worker.join()
    finally:
        if old_size is not None:
            try:
                threading.stack_size(old_size)
            except (ValueError, RuntimeError):
                pass
    if "error" in box:
        raise box["error"]
    return box["value"]
```
