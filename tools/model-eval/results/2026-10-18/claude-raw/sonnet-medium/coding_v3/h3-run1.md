```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_GENERIC = 1 << 60


def _tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c in " \t\n":
            i += 1
        elif "0" <= c <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            tokens.append(("int", src[i:j]))
            i = j
        elif ("a" <= c <= "z") or c == "_":
            j = i + 1
            while j < n and (("a" <= src[j] <= "z") or ("A" <= src[j] <= "Z")
                             or ("0" <= src[j] <= "9") or src[j] in "_'"):
                j += 1
            word = src[i:j]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            i = j
        elif c == "-":
            if i + 1 < n and src[i + 1] == ">":
                tokens.append(("->", "->"))
                i += 2
            else:
                tokens.append(("-", "-"))
                i += 1
        elif c == ":":
            if i + 1 < n and src[i + 1] == ":":
                tokens.append(("::", "::"))
                i += 2
            else:
                raise SyntaxError("bad ':'")
        elif c == "[":
            j = i + 1
            while j < n and src[j] in " \t\n":
                j += 1
            if j < n and src[j] == "]":
                tokens.append(("[]", "[]"))
                i = j + 1
            else:
                raise SyntaxError("bad '['")
        elif c in "(),+*=<":
            tokens.append((c, c))
            i += 1
        else:
            raise SyntaxError("bad character")
    tokens.append(("eof", ""))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos][0]

    def next(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind):
        tok = self.tokens[self.pos]
        if tok[0] != kind:
            raise SyntaxError("expected " + kind)
        self.pos += 1
        return tok

    def parse_all(self):
        expr = self.parse_expr()
        if self.peek() != "eof":
            raise SyntaxError("trailing tokens")
        return expr

    def parse_expr(self):
        kind = self.peek()
        if kind == "fun":
            self.next()
            params = []
            while self.peek() == "name":
                params.append(self.next()[1])
            if not params:
                raise SyntaxError("fun needs params")
            self.expect("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if kind == "let":
            self.next()
            is_rec = False
            if self.peek() == "rec":
                self.next()
                is_rec = True
            name = self.expect("name")[1]
            params = []
            while self.peek() == "name":
                params.append(self.next()[1])
            if is_rec and not params:
                raise SyntaxError("let rec needs params")
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
            self.next()
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
            op = self.next()[0]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        left = self.parse_add()
        if self.peek() == "::":
            self.next()
            right = self.parse_cons()
            return ("bin", "::", left, right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek() in ("+", "-"):
            op = self.next()[0]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.peek() == "*":
            self.next()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def parse_app(self):
        left = self.parse_atom()
        while self.peek() in ("int", "name", "true", "false", "[]", "("):
            arg = self.parse_atom()
            left = ("app", left, arg)
        return left

    def parse_atom(self):
        kind, value = self.tokens[self.pos]
        if kind == "int":
            self.pos += 1
            return ("int",)
        if kind == "true" or kind == "false":
            self.pos += 1
            return ("bool",)
        if kind == "name":
            self.pos += 1
            return ("var", value)
        if kind == "[]":
            self.pos += 1
            return ("nil",)
        if kind == "(":
            self.pos += 1
            first = self.parse_expr()
            if self.peek() == ",":
                self.next()
                second = self.parse_expr()
                self.expect(")")
                return ("tuple", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token " + kind)


class _Var:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _Con:
    __slots__ = ("name", "args")

    def __init__(self, name, args=()):
        self.name = name
        self.args = args


def _prune(ty):
    while isinstance(ty, _Var) and ty.ref is not None:
        ty = ty.ref
    return ty


_INT = _Con("int")
_BOOL = _Con("bool")


def _fn(a, b):
    return _Con("->", (a, b))


def _list(a):
    return _Con("list", (a,))


def _pair(a, b):
    return _Con("*", (a, b))


def _unify(t1, t2):
    t1 = _prune(t1)
    t2 = _prune(t2)
    if t1 is t2:
        return
    if isinstance(t1, _Var):
        _bind(t1, t2)
        return
    if isinstance(t2, _Var):
        _bind(t2, t1)
        return
    if t1.name != t2.name or len(t1.args) != len(t2.args):
        raise TypeError("mismatch")
    for left, right in zip(t1.args, t2.args):
        _unify(left, right)


def _bind(var, ty):
    _occurs_adjust(var, ty)
    var.ref = ty


def _occurs_adjust(var, ty):
    ty = _prune(ty)
    if isinstance(ty, _Var):
        if ty is var:
            raise TypeError("occurs check")
        if ty.level > var.level:
            ty.level = var.level
        return
    for arg in ty.args:
        _occurs_adjust(var, arg)


def _instantiate(ty, mapping):
    ty = _prune(ty)
    if isinstance(ty, _Var):
        if ty.level == _GENERIC:
            if ty not in mapping:
                mapping[ty] = _Var(_State.level)
            return mapping[ty]
        return ty
    if not ty.args:
        return ty
    new_args = tuple(_instantiate(arg, mapping) for arg in ty.args)
    return _Con(ty.name, new_args)


def _generalize(ty):
    ty = _prune(ty)
    if isinstance(ty, _Var):
        if ty.level > _State.level:
            ty.level = _GENERIC
        return
    for arg in ty.args:
        _generalize(arg)


class _State:
    level = 0


def _builtins():
    def gen():
        return _Var(_GENERIC)

    env = {}
    a, b = gen(), gen()
    env["fst"] = _fn(_pair(a, b), a)
    a, b = gen(), gen()
    env["snd"] = _fn(_pair(a, b), b)
    a = gen()
    env["hd"] = _fn(_list(a), a)
    a = gen()
    env["tl"] = _fn(_list(a), _list(a))
    a = gen()
    env["null"] = _fn(_list(a), _BOOL)
    return env


def _fresh():
    return _Var(_State.level)


def _infer(node, env):
    kind = node[0]
    if kind == "int":
        return _INT
    if kind == "bool":
        return _BOOL
    if kind == "var":
        name = node[1]
        if name not in env:
            raise NameError(name)
        return _instantiate(env[name], {})
    if kind == "nil":
        return _list(_fresh())
    if kind == "tuple":
        first = _infer(node[1], env)
        second = _infer(node[2], env)
        return _pair(first, second)
    if kind == "app":
        fn_type = _infer(node[1], env)
        arg_type = _infer(node[2], env)
        result = _fresh()
        _unify(fn_type, _fn(arg_type, result))
        return result
    if kind == "bin":
        op = node[1]
        left = _infer(node[2], env)
        right = _infer(node[3], env)
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
        _unify(right, _list(left))
        return right
    if kind == "if":
        cond = _infer(node[1], env)
        _unify(cond, _BOOL)
        then_type = _infer(node[2], env)
        else_type = _infer(node[3], env)
        _unify(then_type, else_type)
        return then_type
    if kind == "fun":
        return _infer_fun(node[1], node[2], env)
    if kind == "let":
        name = node[1]
        _State.level += 1
        try:
            bound = _infer(node[2], env)
        finally:
            _State.level -= 1
        _generalize(bound)
        return _with_binding(env, name, bound, node[3])
    if kind == "letrec":
        name = node[1]
        _State.level += 1
        try:
            self_type = _fresh()
            old_found, old = name in env, env.get(name)
            env[name] = self_type
            try:
                body_type = _infer_fun(node[2], node[3], env)
            finally:
                if old_found:
                    env[name] = old
                else:
                    del env[name]
            _unify(self_type, body_type)
        finally:
            _State.level -= 1
        _generalize(self_type)
        return _with_binding(env, name, self_type, node[4])
    raise SyntaxError("unknown node")


def _with_binding(env, name, ty, body):
    old_found, old = name in env, env.get(name)
    env[name] = ty
    try:
        return _infer(body, env)
    finally:
        if old_found:
            env[name] = old
        else:
            del env[name]


def _infer_fun(params, body, env):
    saved = []
    param_types = []
    try:
        for name in params:
            saved.append((name, name in env, env.get(name)))
            param_type = _fresh()
            param_types.append(param_type)
            env[name] = param_type
        result = _infer(body, env)
    finally:
        for name, found, old in reversed(saved):
            if found:
                env[name] = old
            else:
                del env[name]
    for param_type in reversed(param_types):
        result = _fn(param_type, result)
    return result


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    if index >= 26:
        return "'" + letter + str(index // 26)
    return "'" + letter


def _show(ty, ctx, names):
    ty = _prune(ty)
    if isinstance(ty, _Var):
        if ty not in names:
            names[ty] = _var_name(len(names))
        return names[ty]
    if ty.name == "->":
        text = _show(ty.args[0], 1, names) + " -> " + _show(ty.args[1], 0, names)
        return "(" + text + ")" if ctx >= 1 else text
    if ty.name == "*":
        text = _show(ty.args[0], 2, names) + " * " + _show(ty.args[1], 2, names)
        return "(" + text + ")" if ctx >= 2 else text
    if ty.name == "list":
        return _show(ty.args[0], 3, names) + " list"
    return ty.name


def _run(src):
    tree = _Parser(_tokenize(src)).parse_all()
    _State.level = 0
    env = _builtins()
    ty = _infer(tree, env)
    return _show(ty, 0, {})


def infer(src: str) -> str:
    outcome = {}

    def worker():
        try:
            outcome["value"] = _run(src)
        except BaseException as error:
            outcome["error"] = error

    old_limit = sys.getrecursionlimit()
    old_stack = None
    try:
        sys.setrecursionlimit(1000000)
        try:
            old_stack = threading.stack_size(512 * 1024 * 1024)
        except (ValueError, RuntimeError):
            old_stack = None
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    finally:
        sys.setrecursionlimit(old_limit)
        if old_stack is not None:
            try:
                threading.stack_size(old_stack)
            except (ValueError, RuntimeError):
                pass
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
