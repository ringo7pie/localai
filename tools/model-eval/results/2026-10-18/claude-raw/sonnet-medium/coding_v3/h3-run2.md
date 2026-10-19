```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_DIGITS = "0123456789"
_NAME_START = "abcdefghijklmnopqrstuvwxyz_"
_NAME_REST = _NAME_START + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + _DIGITS + "'"
_SINGLE = "()," + "+-*=<[]"
_GENERIC = 10 ** 9


def _tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n":
            i += 1
        elif ch in _DIGITS:
            j = i
            while j < n and src[j] in _DIGITS:
                j += 1
            tokens.append(("int", src[i:j]))
            i = j
        elif ch in _NAME_START:
            j = i + 1
            while j < n and src[j] in _NAME_REST:
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            i = j
        elif ch == "-" and i + 1 < n and src[i + 1] == ">":
            tokens.append(("->", "->"))
            i += 2
        elif ch == ":" and i + 1 < n and src[i + 1] == ":":
            tokens.append(("::", "::"))
            i += 2
        elif ch in _SINGLE:
            tokens.append((ch, ch))
            i += 1
        else:
            raise SyntaxError("bad character %r" % ch)
    tokens.append(("eof", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos][0]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok[0] != "eof":
            self.pos += 1
        return tok

    def accept(self, kind):
        if self.peek() == kind:
            self.advance()
            return True
        return False

    def expect(self, kind):
        if self.peek() != kind:
            raise SyntaxError("expected %s" % kind)
        return self.advance()

    def parse_top(self):
        result = self.parse_expr()
        if self.peek() != "eof":
            raise SyntaxError("unexpected token")
        return result

    def parse_expr(self):
        kind = self.peek()
        if kind == "fun":
            self.advance()
            names = []
            while self.peek() == "name":
                names.append(self.advance()[1])
            if not names:
                raise SyntaxError("fun needs parameters")
            self.expect("->")
            body = self.parse_expr()
            return ("fun", names, body)
        if kind == "let":
            self.advance()
            is_rec = self.accept("rec")
            name = self.expect("name")[1]
            params = []
            while self.peek() == "name":
                params.append(self.advance()[1])
            if is_rec and not params:
                raise SyntaxError("let rec needs parameters")
            self.expect("=")
            bound = self.parse_expr()
            self.expect("in")
            body = self.parse_expr()
            if is_rec:
                return ("letrec", name, params, bound, body)
            if params:
                bound = ("fun", params, bound)
            return ("let", name, bound, body)
        if kind == "if":
            self.advance()
            cond = self.parse_expr()
            self.expect("then")
            then_branch = self.parse_expr()
            self.expect("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while self.peek() in ("=", "<"):
            op = self.advance()[0]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        operands = [self.parse_add()]
        while self.accept("::"):
            operands.append(self.parse_add())
        result = operands[-1]
        for item in reversed(operands[:-1]):
            result = ("cons", item, result)
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
        head = self.parse_atom()
        while self.peek() in ("int", "name", "true", "false", "[", "("):
            head = ("app", head, self.parse_atom())
        return head

    def parse_atom(self):
        kind = self.peek()
        if kind == "int":
            self.advance()
            return ("int",)
        if kind == "true" or kind == "false":
            self.advance()
            return ("bool",)
        if kind == "name":
            return ("var", self.advance()[1])
        if kind == "[":
            self.advance()
            self.expect("]")
            return ("nil",)
        if kind == "(":
            self.advance()
            first = self.parse_expr()
            if self.accept(","):
                second = self.parse_expr()
                self.expect(")")
                return ("tuple", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


class _TVar:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = args


_INT = _TCon("int")
_BOOL = _TCon("bool")


def _arrow(left, right):
    return _TCon("->", (left, right))


def _list(elem):
    return _TCon("list", (elem,))


def _pair(left, right):
    return _TCon("*", (left, right))


def _find(t):
    root = t
    while isinstance(root, _TVar) and root.ref is not None:
        root = root.ref
    while isinstance(t, _TVar) and t.ref is not None:
        nxt = t.ref
        t.ref = root
        t = nxt
    return root


def _occurs_adjust(var, t):
    t = _find(t)
    if isinstance(t, _TVar):
        if t is var:
            raise TypeError("infinite type")
        if t.level > var.level:
            t.level = var.level
    else:
        for arg in t.args:
            _occurs_adjust(var, arg)


def _unify(a, b):
    a = _find(a)
    b = _find(b)
    if a is b:
        return
    if isinstance(a, _TVar):
        _occurs_adjust(a, b)
        a.ref = b
        return
    if isinstance(b, _TVar):
        _occurs_adjust(b, a)
        b.ref = a
        return
    if a.name != b.name or len(a.args) != len(b.args):
        raise TypeError("type mismatch")
    for x, y in zip(a.args, b.args):
        _unify(x, y)


def _generalize(t, level):
    t = _find(t)
    if isinstance(t, _TVar):
        if t.level > level:
            t.level = _GENERIC
    else:
        for arg in t.args:
            _generalize(arg, level)


def _instantiate(t, level, mapping):
    t = _find(t)
    if isinstance(t, _TVar):
        if t.level == _GENERIC:
            found = mapping.get(id(t))
            if found is None:
                found = _TVar(level)
                mapping[id(t)] = found
            return found
        return t
    if not t.args:
        return t
    return _TCon(t.name, tuple(_instantiate(arg, level, mapping) for arg in t.args))


def _builtins():
    def gen():
        return _TVar(_GENERIC)

    a = gen()
    b = gen()
    c = gen()
    d = gen()
    e = gen()
    f = gen()
    g = gen()
    return {
        "fst": _arrow(_pair(a, b), a),
        "snd": _arrow(_pair(c, d), d),
        "hd": _arrow(_list(e), e),
        "tl": _arrow(_list(f), _list(f)),
        "null": _arrow(_list(g), _BOOL),
    }


_MISSING = object()


def _infer_type(ast):
    env = _builtins()

    def infer(e, level):
        kind = e[0]
        if kind == "int":
            return _INT
        if kind == "bool":
            return _BOOL
        if kind == "var":
            name = e[1]
            if name not in env:
                raise NameError(name)
            return _instantiate(env[name], level, {})
        if kind == "nil":
            return _list(_TVar(level))
        if kind == "tuple":
            first = infer(e[1], level)
            second = infer(e[2], level)
            return _pair(first, second)
        if kind == "app":
            func_type = infer(e[1], level)
            arg_type = infer(e[2], level)
            result = _TVar(level)
            _unify(func_type, _arrow(arg_type, result))
            return result
        if kind == "bin":
            op = e[1]
            left = infer(e[2], level)
            right = infer(e[3], level)
            if op == "=":
                _unify(left, right)
                return _BOOL
            _unify(left, _INT)
            _unify(right, _INT)
            return _BOOL if op == "<" else _INT
        if kind == "cons":
            head = infer(e[1], level)
            tail = infer(e[2], level)
            _unify(tail, _list(head))
            return tail
        if kind == "if":
            cond = infer(e[1], level)
            _unify(cond, _BOOL)
            then_type = infer(e[2], level)
            else_type = infer(e[3], level)
            _unify(then_type, else_type)
            return then_type
        if kind == "fun":
            names = e[1]
            saved = []
            param_types = []
            for name in names:
                param_type = _TVar(level)
                param_types.append(param_type)
                saved.append((name, env.get(name, _MISSING)))
                env[name] = param_type
            try:
                result = infer(e[2], level)
            finally:
                for name, old in reversed(saved):
                    if old is _MISSING:
                        env.pop(name, None)
                    else:
                        env[name] = old
            for param_type in reversed(param_types):
                result = _arrow(param_type, result)
            return result
        if kind == "let":
            name = e[1]
            bound_type = infer(e[2], level + 1)
            _generalize(bound_type, level)
            old = env.get(name, _MISSING)
            env[name] = bound_type
            try:
                return infer(e[3], level)
            finally:
                if old is _MISSING:
                    env.pop(name, None)
                else:
                    env[name] = old
        if kind == "letrec":
            name = e[1]
            params = e[2]
            old_name = env.get(name, _MISSING)
            func_var = _TVar(level + 1)
            env[name] = func_var
            saved = []
            param_types = []
            try:
                for param in params:
                    param_type = _TVar(level + 1)
                    param_types.append(param_type)
                    saved.append((param, env.get(param, _MISSING)))
                    env[param] = param_type
                try:
                    body_type = infer(e[3], level + 1)
                finally:
                    for param, old in reversed(saved):
                        if old is _MISSING:
                            env.pop(param, None)
                        else:
                            env[param] = old
                func_type = body_type
                for param_type in reversed(param_types):
                    func_type = _arrow(param_type, func_type)
                _unify(func_var, func_type)
                _generalize(func_var, level)
                env[name] = func_var
                return infer(e[4], level)
            finally:
                if old_name is _MISSING:
                    env.pop(name, None)
                else:
                    env[name] = old_name
        raise SyntaxError("unknown node")

    return infer(ast, 0)


def _var_name(index):
    letter = "abcdefghijklmnopqrstuvwxyz"[index % 26]
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix else "")


def _render(t):
    names = {}

    def show(t, prec):
        t = _find(t)
        if isinstance(t, _TVar):
            key = id(t)
            if key not in names:
                names[key] = _var_name(len(names))
            return names[key]
        if t.name == "->":
            text = show(t.args[0], 1) + " -> " + show(t.args[1], 0)
            return "(" + text + ")" if prec >= 1 else text
        if t.name == "*":
            text = show(t.args[0], 2) + " * " + show(t.args[1], 2)
            return "(" + text + ")" if prec >= 2 else text
        if t.name == "list":
            return show(t.args[0], 2) + " list"
        return t.name

    return show(t, 0)


def infer(src: str) -> str:
    tokens = _tokenize(src)
    ast = _Parser(tokens).parse_top()

    outcome = {}

    def work():
        try:
            outcome["value"] = _render(_infer_type(ast))
        except BaseException as exc:
            outcome["error"] = exc

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    sys.setrecursionlimit(1000000)
    try:
        threading.stack_size(512 * 1024 * 1024)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
    finally:
        sys.setrecursionlimit(old_limit)
        try:
            threading.stack_size(old_stack)
        except Exception:
            pass
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
