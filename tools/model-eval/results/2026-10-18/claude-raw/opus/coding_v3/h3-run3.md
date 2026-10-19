```python
import sys

_GENERIC = 1 << 62
_RECURSION_LIMIT = 200000


class _TVar:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _TCon("int", ())
_BOOL = _TCon("bool", ())


def _arrow(param, result):
    return _TCon("->", (param, result))


def _list_of(elem):
    return _TCon("list", (elem,))


def _pair_of(left, right):
    return _TCon("*", (left, right))


def _prune(typ):
    root = typ
    while type(root) is _TVar and root.ref is not None:
        root = root.ref
    while type(typ) is _TVar and typ.ref is not None:
        nxt = typ.ref
        typ.ref = root
        typ = nxt
    return root


def _bind(var, typ):
    limit = var.level
    stack = [typ]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _TVar:
            if cur is var:
                raise TypeError("recursive type (occurs check failed)")
            if cur.level > limit:
                cur.level = limit
        elif cur.args:
            key = id(cur)
            if key not in seen:
                seen.add(key)
                stack.extend(cur.args)
    var.ref = typ


def _unify(first, second):
    stack = [(first, second)]
    while stack:
        left, right = stack.pop()
        left = _prune(left)
        right = _prune(right)
        if left is right:
            continue
        if type(left) is _TVar:
            _bind(left, right)
        elif type(right) is _TVar:
            _bind(right, left)
        else:
            if left.name != right.name or len(left.args) != len(right.args):
                raise TypeError("type mismatch: %s vs %s" % (left.name, right.name))
            stack.extend(zip(left.args, right.args))


def _generalize(typ, level):
    found = False
    stack = [typ]
    seen = set()
    while stack:
        cur = _prune(stack.pop())
        if type(cur) is _TVar:
            if cur.level > level:
                cur.level = _GENERIC
                found = True
        elif cur.args:
            key = id(cur)
            if key not in seen:
                seen.add(key)
                stack.extend(cur.args)
    return found


def _instantiate(typ, level):
    var_map = {}
    node_map = {}

    def copy(cur):
        cur = _prune(cur)
        if type(cur) is _TVar:
            if cur.level == _GENERIC:
                fresh = var_map.get(cur)
                if fresh is None:
                    fresh = _TVar(level)
                    var_map[cur] = fresh
                return fresh
            return cur
        args = cur.args
        if not args:
            return cur
        key = id(cur)
        done = node_map.get(key)
        if done is not None:
            return done
        new_args = []
        changed = False
        for arg in args:
            new_arg = copy(arg)
            if new_arg is not arg:
                changed = True
            new_args.append(new_arg)
        result = _TCon(cur.name, tuple(new_args)) if changed else cur
        node_map[key] = result
        return result

    return copy(typ)


def _type_to_str(typ):
    names = {}
    out = []

    def var_name(var):
        name = names.get(var)
        if name is None:
            index = len(names)
            name = "'" + chr(97 + index % 26) + (str(index // 26) if index >= 26 else "")
            names[var] = name
        return name

    def is_compound(cur):
        return type(cur) is _TCon and (cur.name == "->" or cur.name == "*")

    def emit(cur):
        cur = _prune(cur)
        while True:
            if type(cur) is _TVar:
                out.append(var_name(cur))
                return
            name = cur.name
            if name == "int" or name == "bool":
                out.append(name)
                return
            if name == "list":
                inner = _prune(cur.args[0])
                if is_compound(inner):
                    out.append("(")
                    emit(inner)
                    out.append(")")
                else:
                    emit(inner)
                out.append(" list")
                return
            if name == "*":
                left = _prune(cur.args[0])
                right = _prune(cur.args[1])
                if is_compound(left):
                    out.append("(")
                    emit(left)
                    out.append(")")
                else:
                    emit(left)
                out.append(" * ")
                if is_compound(right):
                    out.append("(")
                    emit(right)
                    out.append(")")
                else:
                    emit(right)
                return
            left = _prune(cur.args[0])
            if type(left) is _TCon and left.name == "->":
                out.append("(")
                emit(left)
                out.append(")")
            else:
                emit(left)
            out.append(" -> ")
            cur = _prune(cur.args[1])

    emit(typ)
    return "".join(out)


_KEYWORDS = frozenset(("fun", "let", "rec", "in", "if", "then", "else", "true", "false"))
_LOWER = frozenset("abcdefghijklmnopqrstuvwxyz")
_DIGITS = frozenset("0123456789")
_NAME_REST = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'"
)
_SPACES = frozenset(" \t\n\r")
_SINGLE_SYMBOLS = frozenset("(),+*=<[]")
_ATOM_START = frozenset(("int", "name", "true", "false", "[", "("))


def _tokenize(src):
    tokens = []
    pos = 0
    length = len(src)
    while pos < length:
        ch = src[pos]
        if ch in _SPACES:
            pos += 1
        elif ch in _DIGITS:
            end = pos + 1
            while end < length and src[end] in _DIGITS:
                end += 1
            tokens.append(("int", src[pos:end]))
            pos = end
        elif ch in _LOWER or ch == "_":
            end = pos + 1
            while end < length and src[end] in _NAME_REST:
                end += 1
            word = src[pos:end]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("name", word))
            pos = end
        elif ch == "-":
            if pos + 1 < length and src[pos + 1] == ">":
                tokens.append(("->", "->"))
                pos += 2
            else:
                tokens.append(("-", "-"))
                pos += 1
        elif ch == ":":
            if pos + 1 < length and src[pos + 1] == ":":
                tokens.append(("::", "::"))
                pos += 2
            else:
                raise SyntaxError("unexpected character ':' at %d" % pos)
        elif ch in _SINGLE_SYMBOLS:
            tokens.append((ch, ch))
            pos += 1
        else:
            raise SyntaxError("unexpected character %r at %d" % (ch, pos))
    tokens.append(("eof", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos][0]

    def _fail(self):
        tok = self.tokens[self.pos]
        shown = "end of input" if tok[0] == "eof" else repr(tok[1])
        raise SyntaxError("unexpected %s" % shown)

    def _expect(self, kind):
        tok = self.tokens[self.pos]
        if tok[0] != kind:
            self._fail()
        self.pos += 1
        return tok[1]

    def _names(self):
        names = []
        tokens = self.tokens
        while tokens[self.pos][0] == "name":
            names.append(tokens[self.pos][1])
            self.pos += 1
        return names

    def parse_program(self):
        tree = self.parse_expr()
        if self._peek() != "eof":
            self._fail()
        return tree

    def parse_expr(self):
        kind = self._peek()
        if kind == "fun":
            self.pos += 1
            params = self._names()
            if not params:
                self._fail()
            self._expect("->")
            body = self.parse_expr()
            return ("fun", params, body)
        if kind == "let":
            self.pos += 1
            is_rec = False
            if self._peek() == "rec":
                self.pos += 1
                is_rec = True
            name = self._expect("name")
            params = self._names()
            if is_rec and not params:
                self._fail()
            self._expect("=")
            rhs = self.parse_expr()
            self._expect("in")
            body = self.parse_expr()
            if params:
                rhs = ("fun", params, rhs)
            return ("letrec" if is_rec else "let", name, rhs, body)
        if kind == "if":
            self.pos += 1
            cond = self.parse_compare()
            self._expect("then")
            then_branch = self.parse_expr()
            self._expect("else")
            else_branch = self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return self.parse_compare()

    def parse_compare(self):
        left = self.parse_cons()
        while True:
            kind = self._peek()
            if kind == "=" or kind == "<":
                self.pos += 1
                right = self.parse_cons()
                left = ("binop", kind, left, right)
            else:
                return left

    def parse_cons(self):
        items = [self.parse_additive()]
        while self._peek() == "::":
            self.pos += 1
            items.append(self.parse_additive())
        result = items[-1]
        for index in range(len(items) - 2, -1, -1):
            result = ("binop", "::", items[index], result)
        return result

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            kind = self._peek()
            if kind == "+" or kind == "-":
                self.pos += 1
                right = self.parse_multiplicative()
                left = ("binop", kind, left, right)
            else:
                return left

    def parse_multiplicative(self):
        left = self.parse_application()
        while self._peek() == "*":
            self.pos += 1
            right = self.parse_application()
            left = ("binop", "*", left, right)
        return left

    def parse_application(self):
        func = self.parse_atom()
        tokens = self.tokens
        while tokens[self.pos][0] in _ATOM_START:
            arg = self.parse_atom()
            func = ("app", func, arg)
        return func

    def parse_atom(self):
        tok = self.tokens[self.pos]
        kind = tok[0]
        if kind == "int":
            self.pos += 1
            return ("int",)
        if kind == "true" or kind == "false":
            self.pos += 1
            return ("bool",)
        if kind == "name":
            self.pos += 1
            return ("var", tok[1])
        if kind == "[":
            self.pos += 1
            self._expect("]")
            return ("nil",)
        if kind == "(":
            self.pos += 1
            first = self.parse_expr()
            if self._peek() == ",":
                self.pos += 1
                second = self.parse_expr()
                self._expect(")")
                return ("pair", first, second)
            self._expect(")")
            return first
        self._fail()


class _Checker:
    def __init__(self):
        env = {}
        var_a = _TVar(_GENERIC)
        var_b = _TVar(_GENERIC)
        env["fst"] = (_arrow(_pair_of(var_a, var_b), var_a), True)
        var_a = _TVar(_GENERIC)
        var_b = _TVar(_GENERIC)
        env["snd"] = (_arrow(_pair_of(var_a, var_b), var_b), True)
        var_a = _TVar(_GENERIC)
        env["hd"] = (_arrow(_list_of(var_a), var_a), True)
        var_a = _TVar(_GENERIC)
        env["tl"] = (_arrow(_list_of(var_a), _list_of(var_a)), True)
        var_a = _TVar(_GENERIC)
        env["null"] = (_arrow(_list_of(var_a), _BOOL), True)
        self.env = env

    def _restore(self, name, old):
        if old is None:
            del self.env[name]
        else:
            self.env[name] = old

    def visit(self, node, level):
        kind = node[0]
        if kind == "int":
            return _INT
        if kind == "bool":
            return _BOOL
        if kind == "nil":
            return _list_of(_TVar(level))
        if kind == "var":
            entry = self.env.get(node[1])
            if entry is None:
                raise NameError("name %r is not defined" % (node[1],))
            typ, poly = entry
            if poly:
                return _instantiate(typ, level)
            return typ
        if kind == "app":
            func = self.visit(node[1], level)
            arg = self.visit(node[2], level)
            func = _prune(func)
            if type(func) is _TCon:
                if func.name != "->":
                    raise TypeError("applying a non-function")
                _unify(func.args[0], arg)
                return func.args[1]
            result = _TVar(level)
            _bind(func, _arrow(arg, result))
            return result
        if kind == "binop":
            op = node[1]
            left = self.visit(node[2], level)
            if op == "+" or op == "-" or op == "*" or op == "<":
                _unify(left, _INT)
                right = self.visit(node[3], level)
                _unify(right, _INT)
                return _BOOL if op == "<" else _INT
            right = self.visit(node[3], level)
            if op == "=":
                _unify(left, right)
                return _BOOL
            list_type = _list_of(left)
            _unify(list_type, right)
            return list_type
        if kind == "pair":
            left = self.visit(node[1], level)
            right = self.visit(node[2], level)
            return _pair_of(left, right)
        if kind == "if":
            cond = self.visit(node[1], level)
            _unify(cond, _BOOL)
            then_type = self.visit(node[2], level)
            else_type = self.visit(node[3], level)
            _unify(then_type, else_type)
            return then_type
        if kind == "fun":
            env = self.env
            saved = []
            param_types = []
            for name in node[1]:
                tvar = _TVar(level)
                saved.append((name, env.get(name)))
                env[name] = (tvar, False)
                param_types.append(tvar)
            result = self.visit(node[2], level)
            for name, old in reversed(saved):
                self._restore(name, old)
            for tvar in reversed(param_types):
                result = _arrow(tvar, result)
            return result
        if kind == "let":
            name = node[1]
            rhs_type = self.visit(node[2], level + 1)
            poly = _generalize(rhs_type, level)
            old = self.env.get(name)
            self.env[name] = (rhs_type, poly)
            body_type = self.visit(node[3], level)
            self._restore(name, old)
            return body_type
        if kind == "letrec":
            name = node[1]
            self_type = _TVar(level + 1)
            old = self.env.get(name)
            self.env[name] = (self_type, False)
            rhs_type = self.visit(node[2], level + 1)
            _unify(self_type, rhs_type)
            poly = _generalize(self_type, level)
            self.env[name] = (self_type, poly)
            body_type = self.visit(node[3], level)
            self._restore(name, old)
            return body_type
        raise SyntaxError("unknown node")


def infer(src: str) -> str:
    old_limit = sys.getrecursionlimit()
    raised = old_limit < _RECURSION_LIMIT
    if raised:
        sys.setrecursionlimit(_RECURSION_LIMIT)
    try:
        tokens = _tokenize(src)
        tree = _Parser(tokens).parse_program()
        checker = _Checker()
        typ = checker.visit(tree, 0)
        return _type_to_str(typ)
    finally:
        if raised:
            sys.setrecursionlimit(old_limit)
```
