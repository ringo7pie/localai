```python
_KEYWORDS = frozenset(("fun", "let", "rec", "in", "if", "then", "else", "true", "false"))
_DIGITS = "0123456789"
_NAME_START = "abcdefghijklmnopqrstuvwxyz_"
_NAME_CONT = _NAME_START + "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + _DIGITS + "'"
_SYMBOLS = "(),+-*=<[]"
_SPACES = " \t\n"
_GENERIC = 1 << 60

_BINOPS = {
    "=": (1, False),
    "<": (1, False),
    "::": (2, True),
    "+": (3, False),
    "-": (3, False),
    "*": (4, False),
}

_INT_NODE = ("int",)
_BOOL_NODE = ("bool",)
_NIL_NODE = ("nil",)


class _Var:
    __slots__ = ("ref", "level")

    def __init__(self, level):
        self.ref = None
        self.level = level


class _Con:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _Con("int", ())
_BOOL = _Con("bool", ())


def _run(generator):
    """ジェネレータを明示的なスタックで動かす（再帰しない）。"""
    stack = [generator]
    value = None
    while True:
        try:
            child = stack[-1].send(value)
        except StopIteration as stop:
            stack.pop()
            value = stop.value
            if not stack:
                return value
        else:
            stack.append(child)
            value = None


def _tokenize(src):
    tokens = []
    index = 0
    length = len(src)
    while index < length:
        ch = src[index]
        if ch in _SPACES:
            index += 1
        elif ch in _DIGITS:
            end = index + 1
            while end < length and src[end] in _DIGITS:
                end += 1
            tokens.append(src[index:end])
            index = end
        elif ch in _NAME_START:
            end = index + 1
            while end < length and src[end] in _NAME_CONT:
                end += 1
            tokens.append(src[index:end])
            index = end
        elif ch == "-" and index + 1 < length and src[index + 1] == ">":
            tokens.append("->")
            index += 2
        elif ch == ":" and index + 1 < length and src[index + 1] == ":":
            tokens.append("::")
            index += 2
        elif ch in _SYMBOLS:
            tokens.append(ch)
            index += 1
        else:
            raise SyntaxError("unexpected character: %r" % ch)
    tokens.append("")
    return tokens


def _is_name(tok):
    return tok != "" and tok[0] in _NAME_START and tok not in _KEYWORDS


def _wrap_funs(params, body):
    for param in reversed(params):
        body = ("fun", param, body)
    return body


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def expect(self, text):
        if self.tokens[self.pos] != text:
            raise SyntaxError("expected %r" % text)
        self.pos += 1

    def take_name(self):
        tok = self.tokens[self.pos]
        if not _is_name(tok):
            raise SyntaxError("name expected")
        self.pos += 1
        return tok

    def take_params(self):
        params = []
        tokens = self.tokens
        while _is_name(tokens[self.pos]):
            params.append(tokens[self.pos])
            self.pos += 1
        return params

    def simple_atom(self, tok):
        if tok == "":
            return None
        first = tok[0]
        if first in _DIGITS:
            self.pos += 1
            return _INT_NODE
        if tok == "true" or tok == "false":
            self.pos += 1
            return _BOOL_NODE
        if tok in _KEYWORDS:
            return None
        if first in _NAME_START:
            self.pos += 1
            return ("var", tok)
        if tok == "[":
            if self.tokens[self.pos + 1] != "]":
                raise SyntaxError("']' expected after '['")
            self.pos += 2
            return _NIL_NODE
        return None

    def parse_program(self):
        tree = yield self.parse_expr()
        if self.tokens[self.pos] != "":
            raise SyntaxError("unexpected token: %r" % self.tokens[self.pos])
        return tree

    def parse_expr(self):
        tokens = self.tokens
        tok = tokens[self.pos]
        if tok == "fun":
            self.pos += 1
            params = self.take_params()
            if not params:
                raise SyntaxError("parameter expected")
            self.expect("->")
            body = yield self.parse_expr()
            return _wrap_funs(params, body)
        if tok == "let":
            self.pos += 1
            is_rec = tokens[self.pos] == "rec"
            if is_rec:
                self.pos += 1
            name = self.take_name()
            params = self.take_params()
            if is_rec and not params:
                raise SyntaxError("let rec needs a parameter")
            self.expect("=")
            bound = yield self.parse_expr()
            self.expect("in")
            body = yield self.parse_expr()
            bound = _wrap_funs(params, bound)
            return ("rec" if is_rec else "let", name, bound, body)
        if tok == "if":
            self.pos += 1
            cond = yield self.parse_binary(1)
            self.expect("then")
            then_branch = yield self.parse_expr()
            self.expect("else")
            else_branch = yield self.parse_expr()
            return ("if", cond, then_branch, else_branch)
        return (yield self.parse_binary(1))

    def parse_binary(self, min_prec):
        tokens = self.tokens
        left = yield self.parse_app()
        while True:
            op = tokens[self.pos]
            info = _BINOPS.get(op)
            if info is None:
                return left
            prec, right_assoc = info
            if prec < min_prec:
                return left
            self.pos += 1
            right = yield self.parse_binary(prec if right_assoc else prec + 1)
            left = ("binop", op, left, right)

    def parse_app(self):
        tokens = self.tokens
        func = None
        while True:
            tok = tokens[self.pos]
            if tok == "(":
                self.pos += 1
                node = yield self.parse_paren()
            else:
                node = self.simple_atom(tok)
                if node is None:
                    break
            func = node if func is None else ("app", func, node)
        if func is None:
            raise SyntaxError("expression expected")
        return func

    def parse_paren(self):
        first = yield self.parse_expr()
        if self.tokens[self.pos] == ",":
            self.pos += 1
            second = yield self.parse_expr()
            self.expect(")")
            return ("tuple", first, second)
        self.expect(")")
        return first


def _prune(typ):
    path = []
    while typ.__class__ is _Var and typ.ref is not None:
        path.append(typ)
        typ = typ.ref
    for var in path:
        var.ref = typ
    return typ


def _bind(var, typ):
    level = var.level
    stack = [typ]
    while stack:
        node = _prune(stack.pop())
        if node is var:
            raise TypeError("infinite type")
        if node.__class__ is _Var:
            if node.level > level:
                node.level = level
        else:
            stack.extend(node.args)
    var.ref = typ


def _unify(left, right):
    stack = [(left, right)]
    while stack:
        first, second = stack.pop()
        first = _prune(first)
        second = _prune(second)
        if first is second:
            continue
        if first.__class__ is _Var:
            _bind(first, second)
        elif second.__class__ is _Var:
            _bind(second, first)
        else:
            if first.name != second.name:
                raise TypeError("type mismatch: %s vs %s" % (first.name, second.name))
            stack.extend(zip(first.args, second.args))


def _generalize(typ, level):
    found = False
    stack = [typ]
    while stack:
        node = _prune(stack.pop())
        if node.__class__ is _Var:
            if node.level > level:
                node.level = _GENERIC
                found = True
        else:
            stack.extend(node.args)
    return found


def _instantiate(typ, level):
    mapping = {}
    results = []
    work = [(typ, False)]
    while work:
        node, expanded = work.pop()
        node = _prune(node)
        if node.__class__ is _Var:
            if node.level == _GENERIC:
                fresh = mapping.get(node)
                if fresh is None:
                    fresh = mapping[node] = _Var(level)
                results.append(fresh)
            else:
                results.append(node)
        elif not node.args:
            results.append(node)
        elif expanded:
            count = len(node.args)
            children = results[-count:]
            del results[-count:]
            if all(child is original for child, original in zip(children, node.args)):
                results.append(node)
            else:
                results.append(_Con(node.name, tuple(children)))
        else:
            work.append((node, True))
            for child in reversed(node.args):
                work.append((child, False))
    return results[0]


class _Inferer:
    def __init__(self):
        self.level = 0
        self.env = {}
        var_a, var_b = _Var(_GENERIC), _Var(_GENERIC)
        self.push("fst", _Con("->", (_Con("*", (var_a, var_b)), var_a)), True)
        var_a, var_b = _Var(_GENERIC), _Var(_GENERIC)
        self.push("snd", _Con("->", (_Con("*", (var_a, var_b)), var_b)), True)
        var_a = _Var(_GENERIC)
        self.push("hd", _Con("->", (_Con("list", (var_a,)), var_a)), True)
        var_a = _Var(_GENERIC)
        list_a = _Con("list", (var_a,))
        self.push("tl", _Con("->", (list_a, list_a)), True)
        var_a = _Var(_GENERIC)
        self.push("null", _Con("->", (_Con("list", (var_a,)), _BOOL)), True)

    def push(self, name, typ, poly):
        stack = self.env.get(name)
        if stack is None:
            self.env[name] = [(typ, poly)]
        else:
            stack.append((typ, poly))

    def pop(self, name):
        self.env[name].pop()

    def visit(self, node):
        tag = node[0]
        if tag == "app":
            func_type = yield self.visit(node[1])
            arg_type = yield self.visit(node[2])
            func_type = _prune(func_type)
            if func_type.__class__ is _Con and func_type.name == "->":
                _unify(func_type.args[0], arg_type)
                return func_type.args[1]
            result = _Var(self.level)
            _unify(func_type, _Con("->", (arg_type, result)))
            return result
        if tag == "var":
            stack = self.env.get(node[1])
            if not stack:
                raise NameError(node[1])
            typ, poly = stack[-1]
            if poly:
                return _instantiate(typ, self.level)
            return typ
        if tag == "int":
            return _INT
        if tag == "bool":
            return _BOOL
        if tag == "nil":
            return _Con("list", (_Var(self.level),))
        if tag == "fun":
            param = node[1]
            param_type = _Var(self.level)
            self.push(param, param_type, False)
            body_type = yield self.visit(node[2])
            self.pop(param)
            return _Con("->", (param_type, body_type))
        if tag == "binop":
            op = node[1]
            left_type = yield self.visit(node[2])
            right_type = yield self.visit(node[3])
            if op == "+" or op == "-" or op == "*":
                _unify(left_type, _INT)
                _unify(right_type, _INT)
                return _INT
            if op == "<":
                _unify(left_type, _INT)
                _unify(right_type, _INT)
                return _BOOL
            if op == "=":
                _unify(left_type, right_type)
                return _BOOL
            _unify(right_type, _Con("list", (left_type,)))
            return right_type
        if tag == "if":
            cond_type = yield self.visit(node[1])
            then_type = yield self.visit(node[2])
            else_type = yield self.visit(node[3])
            _unify(cond_type, _BOOL)
            _unify(then_type, else_type)
            return then_type
        if tag == "tuple":
            first_type = yield self.visit(node[1])
            second_type = yield self.visit(node[2])
            return _Con("*", (first_type, second_type))
        if tag == "let":
            name = node[1]
            self.level += 1
            bound_type = yield self.visit(node[2])
            self.level -= 1
            poly = _generalize(bound_type, self.level)
            self.push(name, bound_type, poly)
            body_type = yield self.visit(node[3])
            self.pop(name)
            return body_type
        if tag == "rec":
            name = node[1]
            self.level += 1
            func_var = _Var(self.level)
            self.push(name, func_var, False)
            bound_type = yield self.visit(node[2])
            _unify(func_var, bound_type)
            self.pop(name)
            self.level -= 1
            poly = _generalize(func_var, self.level)
            self.push(name, func_var, poly)
            body_type = yield self.visit(node[3])
            self.pop(name)
            return body_type
        raise SyntaxError("unknown node")


def _var_name(index):
    letter = chr(ord("a") + index % 26)
    round_no = index // 26
    return "'" + letter + (str(round_no) if round_no else "")


def _show(typ):
    names = {}
    parts = []
    work = [(typ, 0)]
    while work:
        item = work.pop()
        if item.__class__ is str:
            parts.append(item)
            continue
        node, ctx = item
        node = _prune(node)
        if node.__class__ is _Var:
            name = names.get(node)
            if name is None:
                name = names[node] = _var_name(len(names))
            parts.append(name)
            continue
        kind = node.name
        if kind == "->":
            left, right = node.args
            if ctx >= 1:
                parts.append("(")
                work.append(")")
            work.append((right, 0))
            work.append(" -> ")
            work.append((left, 1))
        elif kind == "*":
            left, right = node.args
            if ctx >= 2:
                parts.append("(")
                work.append(")")
            work.append((right, 2))
            work.append(" * ")
            work.append((left, 2))
        elif kind == "list":
            work.append(" list")
            work.append((node.args[0], 2))
        else:
            parts.append(kind)
    return "".join(parts)


def infer(src: str) -> str:
    tokens = _tokenize(src)
    tree = _run(_Parser(tokens).parse_program())
    typ = _run(_Inferer().visit(tree))
    return _show(typ)
```
