```python
import sys
import threading

_GENERIC = 1 << 60

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}


class _TVar:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


_INT = ("int",)
_BOOL = ("bool",)


def _prune(t):
    if not isinstance(t, _TVar) or t.ref is None:
        return t
    root = t
    while isinstance(root, _TVar) and root.ref is not None:
        root = root.ref
    cur = t
    while isinstance(cur, _TVar) and cur.ref is not None:
        nxt = cur.ref
        cur.ref = root
        cur = nxt
    return root


def _occurs_adjust(var, t):
    stack = [t]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if isinstance(node, _TVar):
            if node is var:
                raise TypeError("occurs check failed")
            if node.level > var.level:
                node.level = var.level
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            for child in node[1:]:
                stack.append(child)


def _unify(left, right):
    stack = [(left, right)]
    while stack:
        lhs, rhs = stack.pop()
        lhs = _prune(lhs)
        rhs = _prune(rhs)
        if lhs is rhs:
            continue
        if isinstance(lhs, _TVar):
            _occurs_adjust(lhs, rhs)
            lhs.ref = rhs
        elif isinstance(rhs, _TVar):
            _occurs_adjust(rhs, lhs)
            rhs.ref = lhs
        else:
            if lhs[0] != rhs[0] or len(lhs) != len(rhs):
                raise TypeError("type mismatch")
            for idx in range(1, len(lhs)):
                stack.append((lhs[idx], rhs[idx]))


def _generalize(t, level):
    found = False
    stack = [t]
    seen = set()
    while stack:
        node = _prune(stack.pop())
        if isinstance(node, _TVar):
            if node.level != _GENERIC and node.level > level:
                node.level = _GENERIC
                found = True
            elif node.level == _GENERIC:
                found = True
        else:
            key = id(node)
            if key in seen:
                continue
            seen.add(key)
            for child in node[1:]:
                stack.append(child)
    return found


def _instantiate(t, level):
    memo = {}

    def go(node):
        node = _prune(node)
        if isinstance(node, _TVar):
            if node.level == _GENERIC:
                fresh = memo.get(id(node))
                if fresh is None:
                    fresh = _TVar(level)
                    memo[id(node)] = fresh
                return fresh
            return node
        if len(node) == 1:
            return node
        key = id(node)
        cached = memo.get(key)
        if cached is not None:
            return cached
        if len(node) == 2:
            result = (node[0], go(node[1]))
        else:
            first = go(node[1])
            second = go(node[2])
            result = (node[0], first, second)
        memo[key] = result
        return result

    return go(t)


def _lex(src):
    toks = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch == " " or ch == "\t" or ch == "\n":
            pos += 1
        elif "0" <= ch <= "9":
            end = pos
            while end < length and "0" <= src[end] <= "9":
                end += 1
            toks.append(("INT", src[pos:end]))
            pos = end
        elif ("a" <= ch <= "z") or ch == "_":
            end = pos + 1
            while end < length:
                cc = src[end]
                if ("a" <= cc <= "z") or ("A" <= cc <= "Z") or ("0" <= cc <= "9") or cc == "_" or cc == "'":
                    end += 1
                else:
                    break
            word = src[pos:end]
            if word in _KEYWORDS:
                toks.append((word, None))
            else:
                toks.append(("NAME", word))
            pos = end
        elif src.startswith("->", pos):
            toks.append(("->", None))
            pos += 2
        elif src.startswith("::", pos):
            toks.append(("::", None))
            pos += 2
        elif ch == "[":
            if pos + 1 < length and src[pos + 1] == "]":
                toks.append(("[]", None))
                pos += 2
            else:
                raise SyntaxError("expected ] after [")
        elif ch in "(),+-*=<":
            toks.append((ch, None))
            pos += 1
        else:
            raise SyntaxError("unexpected character %r" % ch)
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
        if self.peek() != kind:
            raise SyntaxError("expected %s" % kind)
        return self.advance()

    def parse(self):
        expr = self.expr()
        if self.peek() != "EOF":
            raise SyntaxError("unexpected token")
        return expr

    def expr(self):
        kind = self.peek()
        if kind == "fun":
            self.advance()
            params = []
            while self.peek() == "NAME":
                params.append(self.advance()[1])
            if not params:
                raise SyntaxError("fun needs a parameter")
            self.expect("->")
            body = self.expr()
            for param in reversed(params):
                body = ("fun", param, body)
            return body
        if kind == "let":
            self.advance()
            is_rec = False
            if self.peek() == "rec":
                self.advance()
                is_rec = True
            name = self.expect("NAME")[1]
            params = []
            while self.peek() == "NAME":
                params.append(self.advance()[1])
            if is_rec and not params:
                raise SyntaxError("let rec needs a parameter")
            self.expect("=")
            bound = self.expr()
            self.expect("in")
            body = self.expr()
            for param in reversed(params):
                bound = ("fun", param, bound)
            return ("letrec" if is_rec else "let", name, bound, body)
        if kind == "if":
            self.advance()
            cond = self.cmp()
            self.expect("then")
            then_branch = self.expr()
            self.expect("else")
            else_branch = self.expr()
            return ("if", cond, then_branch, else_branch)
        return self.cmp()

    def cmp(self):
        expr = self.cons()
        while self.peek() in ("=", "<"):
            op = self.advance()[0]
            rhs = self.cons()
            expr = ("binop", op, expr, rhs)
        return expr

    def cons(self):
        items = [self.add()]
        while self.peek() == "::":
            self.advance()
            items.append(self.add())
        expr = items[-1]
        for idx in range(len(items) - 2, -1, -1):
            expr = ("binop", "::", items[idx], expr)
        return expr

    def add(self):
        expr = self.mul()
        while self.peek() in ("+", "-"):
            op = self.advance()[0]
            rhs = self.mul()
            expr = ("binop", op, expr, rhs)
        return expr

    def mul(self):
        expr = self.app()
        while self.peek() == "*":
            self.advance()
            rhs = self.app()
            expr = ("binop", "*", expr, rhs)
        return expr

    def app(self):
        expr = self.atom()
        while self.peek() in _ATOM_START:
            arg = self.atom()
            expr = ("app", expr, arg)
        return expr

    def atom(self):
        kind = self.peek()
        if kind == "INT":
            self.advance()
            return ("int",)
        if kind == "true" or kind == "false":
            self.advance()
            return ("bool",)
        if kind == "NAME":
            return ("var", self.advance()[1])
        if kind == "[]":
            self.advance()
            return ("nil",)
        if kind == "(":
            self.advance()
            first = self.expr()
            if self.peek() == ",":
                self.advance()
                second = self.expr()
                self.expect(")")
                return ("pair", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


def _bind(env, name, scheme):
    prev = env.get(name)
    env[name] = scheme
    return prev


def _restore(env, name, prev):
    if prev is None:
        del env[name]
    else:
        env[name] = prev


def _ti(expr, env, level):
    tag = expr[0]
    if tag == "int":
        return _INT
    if tag == "bool":
        return _BOOL
    if tag == "var":
        scheme = env.get(expr[1])
        if scheme is None:
            raise NameError(expr[1])
        typ, poly = scheme
        if poly:
            return _instantiate(typ, level)
        return typ
    if tag == "nil":
        return ("list", _TVar(level))
    if tag == "pair":
        first = _ti(expr[1], env, level)
        second = _ti(expr[2], env, level)
        return ("pair", first, second)
    if tag == "app":
        fun_type = _ti(expr[1], env, level)
        arg_type = _ti(expr[2], env, level)
        result = _TVar(level)
        _unify(fun_type, ("fn", arg_type, result))
        return result
    if tag == "fun":
        param_type = _TVar(level)
        name = expr[1]
        prev = _bind(env, name, (param_type, False))
        body_type = _ti(expr[2], env, level)
        _restore(env, name, prev)
        return ("fn", param_type, body_type)
    if tag == "let":
        name = expr[1]
        bound_type = _ti(expr[2], env, level + 1)
        poly = _generalize(bound_type, level)
        prev = _bind(env, name, (bound_type, poly))
        body_type = _ti(expr[3], env, level)
        _restore(env, name, prev)
        return body_type
    if tag == "letrec":
        name = expr[1]
        self_type = _TVar(level + 1)
        prev = _bind(env, name, (self_type, False))
        bound_type = _ti(expr[2], env, level + 1)
        _unify(self_type, bound_type)
        poly = _generalize(self_type, level)
        env[name] = (self_type, poly)
        body_type = _ti(expr[3], env, level)
        _restore(env, name, prev)
        return body_type
    if tag == "if":
        cond_type = _ti(expr[1], env, level)
        _unify(cond_type, _BOOL)
        then_type = _ti(expr[2], env, level)
        else_type = _ti(expr[3], env, level)
        _unify(then_type, else_type)
        return then_type
    if tag == "binop":
        op = expr[1]
        lhs = _ti(expr[2], env, level)
        rhs = _ti(expr[3], env, level)
        if op in ("+", "-", "*"):
            _unify(lhs, _INT)
            _unify(rhs, _INT)
            return _INT
        if op == "<":
            _unify(lhs, _INT)
            _unify(rhs, _INT)
            return _BOOL
        if op == "=":
            _unify(lhs, rhs)
            return _BOOL
        if op == "::":
            _unify(rhs, ("list", lhs))
            return rhs
    raise SyntaxError("bad expression")


def _builtins():
    env = {}
    var_a = _TVar(_GENERIC)
    var_b = _TVar(_GENERIC)
    env["fst"] = (("fn", ("pair", var_a, var_b), var_a), True)
    var_a = _TVar(_GENERIC)
    var_b = _TVar(_GENERIC)
    env["snd"] = (("fn", ("pair", var_a, var_b), var_b), True)
    var_a = _TVar(_GENERIC)
    env["hd"] = (("fn", ("list", var_a), var_a), True)
    var_a = _TVar(_GENERIC)
    env["tl"] = (("fn", ("list", var_a), ("list", var_a)), True)
    var_a = _TVar(_GENERIC)
    env["null"] = (("fn", ("list", var_a), _BOOL), True)
    return env


def _show(t):
    names = {}

    def name_of(var):
        key = id(var)
        found = names.get(key)
        if found is None:
            index = len(names)
            found = "'" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
            names[key] = found
        return found

    def go(node, prec):
        node = _prune(node)
        if isinstance(node, _TVar):
            return name_of(node)
        tag = node[0]
        if tag == "int" or tag == "bool":
            return tag
        if tag == "list":
            return go(node[1], 3) + " list"
        if tag == "pair":
            left = go(node[1], 2)
            right = go(node[2], 2)
            text = left + " * " + right
            return "(" + text + ")" if prec >= 2 else text
        left = go(node[1], 1)
        right = go(node[2], 0)
        text = left + " -> " + right
        return "(" + text + ")" if prec >= 1 else text

    return go(t, 0)


def _infer_main(src):
    toks = _lex(src)
    ast = _Parser(toks).parse()
    env = _builtins()
    typ = _ti(ast, env, 0)
    return _show(typ)


def infer(src: str) -> str:
    box = {}

    def run():
        try:
            box["result"] = _infer_main(src)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 200000))
    old_size = None
    try:
        old_size = threading.stack_size(256 * 1024 * 1024)
    except (ValueError, RuntimeError):
        old_size = None
    try:
        worker = threading.Thread(target=run)
        worker.start()
        worker.join()
    finally:
        if old_size is not None:
            try:
                threading.stack_size(old_size)
            except (ValueError, RuntimeError):
                pass
        sys.setrecursionlimit(old_limit)
    if "error" in box:
        raise box["error"]
    return box["result"]
```
