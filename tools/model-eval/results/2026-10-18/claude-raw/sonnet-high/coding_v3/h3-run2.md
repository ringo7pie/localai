```python
import sys
import threading

_KEYWORDS = frozenset(["fun", "let", "rec", "in", "if", "then", "else", "true", "false"])
_GENERIC = 10 ** 9


def _tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch in " \t\n\r":
            i += 1
        elif "0" <= ch <= "9":
            j = i
            while j < n and "0" <= src[j] <= "9":
                j += 1
            tokens.append(("int", int(src[i:j])))
            i = j
        elif ("a" <= ch <= "z") or ch == "_":
            j = i + 1
            while j < n:
                c2 = src[j]
                if ("a" <= c2 <= "z") or ("A" <= c2 <= "Z") or ("0" <= c2 <= "9") or c2 == "_" or c2 == "'":
                    j += 1
                else:
                    break
            word = src[i:j]
            if word in _KEYWORDS:
                tokens.append(("kw", word))
            else:
                tokens.append(("name", word))
            i = j
        elif ch == "-":
            if i + 1 < n and src[i + 1] == ">":
                tokens.append(("sym", "->"))
                i += 2
            else:
                tokens.append(("sym", "-"))
                i += 1
        elif ch == ":":
            if i + 1 < n and src[i + 1] == ":":
                tokens.append(("sym", "::"))
                i += 2
            else:
                raise SyntaxError("unexpected ':'")
        elif ch in "(),+*=<[]":
            tokens.append(("sym", ch))
            i += 1
        else:
            raise SyntaxError("unexpected character %r" % ch)
    tokens.append(("eof", None))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def is_sym(self, text):
        tok = self.tokens[self.pos]
        return tok[0] == "sym" and tok[1] == text

    def is_kw(self, text):
        tok = self.tokens[self.pos]
        return tok[0] == "kw" and tok[1] == text

    def expect_sym(self, text):
        if not self.is_sym(text):
            raise SyntaxError("expected %r" % text)
        self.pos += 1

    def expect_kw(self, text):
        if not self.is_kw(text):
            raise SyntaxError("expected %r" % text)
        self.pos += 1

    def expect_name(self):
        tok = self.tokens[self.pos]
        if tok[0] != "name":
            raise SyntaxError("expected a name")
        self.pos += 1
        return tok[1]

    def parse_params(self):
        params = []
        while self.tokens[self.pos][0] == "name":
            params.append(self.tokens[self.pos][1])
            self.pos += 1
        return params

    def parse_program(self):
        node = self.parse_expr()
        if self.peek()[0] != "eof":
            raise SyntaxError("unexpected token")
        return node

    def parse_expr(self):
        tok = self.peek()
        if tok[0] == "kw":
            word = tok[1]
            if word == "fun":
                self.pos += 1
                params = self.parse_params()
                if not params:
                    raise SyntaxError("fun needs a parameter")
                self.expect_sym("->")
                body = self.parse_expr()
                return ("fun", params, body)
            if word == "let":
                self.pos += 1
                is_rec = False
                if self.is_kw("rec"):
                    self.pos += 1
                    is_rec = True
                name = self.expect_name()
                params = self.parse_params()
                if is_rec and not params:
                    raise SyntaxError("let rec needs a parameter")
                self.expect_sym("=")
                bound = self.parse_expr()
                self.expect_kw("in")
                body = self.parse_expr()
                return ("letrec" if is_rec else "let", name, params, bound, body)
            if word == "if":
                self.pos += 1
                cond = self.parse_expr()
                self.expect_kw("then")
                then_branch = self.parse_expr()
                self.expect_kw("else")
                else_branch = self.parse_expr()
                return ("if", cond, then_branch, else_branch)
        return self.parse_cmp()

    def parse_cmp(self):
        left = self.parse_cons()
        while True:
            tok = self.peek()
            if tok[0] == "sym" and (tok[1] == "=" or tok[1] == "<"):
                self.pos += 1
                right = self.parse_cons()
                left = ("binop", tok[1], left, right)
            else:
                return left

    def parse_cons(self):
        items = [self.parse_add()]
        while self.is_sym("::"):
            self.pos += 1
            items.append(self.parse_add())
        node = items[-1]
        index = len(items) - 2
        while index >= 0:
            node = ("binop", "::", items[index], node)
            index -= 1
        return node

    def parse_add(self):
        left = self.parse_mul()
        while True:
            tok = self.peek()
            if tok[0] == "sym" and (tok[1] == "+" or tok[1] == "-"):
                self.pos += 1
                right = self.parse_mul()
                left = ("binop", tok[1], left, right)
            else:
                return left

    def parse_mul(self):
        left = self.parse_app()
        while self.is_sym("*"):
            self.pos += 1
            right = self.parse_app()
            left = ("binop", "*", left, right)
        return left

    def starts_atom(self):
        tok = self.peek()
        kind = tok[0]
        if kind == "int" or kind == "name":
            return True
        if kind == "kw":
            return tok[1] == "true" or tok[1] == "false"
        if kind == "sym":
            return tok[1] == "(" or tok[1] == "["
        return False

    def parse_app(self):
        node = self.parse_atom()
        while self.starts_atom():
            arg = self.parse_atom()
            node = ("app", node, arg)
        return node

    def parse_atom(self):
        tok = self.advance()
        kind = tok[0]
        if kind == "int":
            return ("int", tok[1])
        if kind == "name":
            return ("var", tok[1])
        if kind == "kw" and (tok[1] == "true" or tok[1] == "false"):
            return ("bool", tok[1] == "true")
        if kind == "sym":
            if tok[1] == "[":
                self.expect_sym("]")
                return ("nil",)
            if tok[1] == "(":
                first = self.parse_expr()
                if self.is_sym(","):
                    self.pos += 1
                    second = self.parse_expr()
                    self.expect_sym(")")
                    return ("pair", first, second)
                self.expect_sym(")")
                return first
        raise SyntaxError("unexpected token")


class _TVar:
    __slots__ = ("link", "level")

    def __init__(self, level):
        self.link = None
        self.level = level


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


def _prune(t):
    root = t
    while type(root) is _TVar and root.link is not None:
        root = root.link
    while type(t) is _TVar and t.link is not None:
        nxt = t.link
        t.link = root
        t = nxt
    return root


class _Inferer:
    def __init__(self):
        self.level = 0
        self.env = {}
        self.int_type = _TCon("int", [])
        self.bool_type = _TCon("bool", [])
        self.install_builtins()

    def fresh(self):
        return _TVar(self.level)

    def install_builtins(self):
        def gen():
            return _TVar(_GENERIC)

        def fn(a, b):
            return _TCon("->", [a, b])

        def tup(a, b):
            return _TCon("*", [a, b])

        def lst(a):
            return _TCon("list", [a])

        a = gen()
        b = gen()
        self.env["fst"] = (fn(tup(a, b), a), True)
        a = gen()
        b = gen()
        self.env["snd"] = (fn(tup(a, b), b), True)
        a = gen()
        self.env["hd"] = (fn(lst(a), a), True)
        a = gen()
        self.env["tl"] = (fn(lst(a), lst(a)), True)
        a = gen()
        self.env["null"] = (fn(lst(a), self.bool_type), True)

    def instantiate(self, t, memo):
        t = _prune(t)
        if type(t) is _TVar:
            if t.level == _GENERIC:
                key = id(t)
                found = memo.get(key)
                if found is None:
                    found = _TVar(self.level)
                    memo[key] = found
                return found
            return t
        key = id(t)
        found = memo.get(key)
        if found is not None:
            return found
        changed = False
        new_args = []
        for arg in t.args:
            new_arg = self.instantiate(arg, memo)
            if new_arg is not arg:
                changed = True
            new_args.append(new_arg)
        result = _TCon(t.name, new_args) if changed else t
        memo[key] = result
        return result

    def generalize(self, t):
        flag = [False]
        seen = set()
        limit = self.level

        def walk(node):
            node = _prune(node)
            if type(node) is _TVar:
                if node.level > limit and node.level != _GENERIC:
                    node.level = _GENERIC
                    flag[0] = True
                elif node.level == _GENERIC:
                    flag[0] = True
                return
            key = id(node)
            if key in seen:
                return
            seen.add(key)
            for arg in node.args:
                walk(arg)

        walk(t)
        return flag[0]

    def bind(self, var, t):
        seen = set()

        def walk(node):
            node = _prune(node)
            if type(node) is _TVar:
                if node is var:
                    raise TypeError("occurs check failed")
                if node.level > var.level:
                    node.level = var.level
                return
            key = id(node)
            if key in seen:
                return
            seen.add(key)
            for arg in node.args:
                walk(arg)

        walk(t)
        var.link = t

    def unify(self, left, right):
        left = _prune(left)
        right = _prune(right)
        if left is right:
            return
        if type(left) is _TVar:
            self.bind(left, right)
            return
        if type(right) is _TVar:
            self.bind(right, left)
            return
        if left.name != right.name or len(left.args) != len(right.args):
            raise TypeError("type mismatch")
        for index in range(len(left.args)):
            self.unify(left.args[index], right.args[index])

    def infer_fun(self, params, body):
        saved = []
        param_types = []
        for name in params:
            var = self.fresh()
            param_types.append(var)
            saved.append((name, self.env.get(name)))
            self.env[name] = (var, False)
        body_type = self.infer(body)
        index = len(saved) - 1
        while index >= 0:
            name, old = saved[index]
            if old is None:
                del self.env[name]
            else:
                self.env[name] = old
            index -= 1
        result = body_type
        index = len(param_types) - 1
        while index >= 0:
            result = _TCon("->", [param_types[index], result])
            index -= 1
        return result

    def infer(self, node):
        kind = node[0]
        if kind == "int":
            return self.int_type
        if kind == "bool":
            return self.bool_type
        if kind == "var":
            entry = self.env.get(node[1])
            if entry is None:
                raise NameError(node[1])
            t, poly = entry
            if poly:
                return self.instantiate(t, {})
            return t
        if kind == "nil":
            return _TCon("list", [self.fresh()])
        if kind == "pair":
            first = self.infer(node[1])
            second = self.infer(node[2])
            return _TCon("*", [first, second])
        if kind == "app":
            func_type = self.infer(node[1])
            arg_type = self.infer(node[2])
            result = self.fresh()
            self.unify(func_type, _TCon("->", [arg_type, result]))
            return result
        if kind == "binop":
            op = node[1]
            left = self.infer(node[2])
            right = self.infer(node[3])
            if op == "+" or op == "-" or op == "*":
                self.unify(left, self.int_type)
                self.unify(right, self.int_type)
                return self.int_type
            if op == "<":
                self.unify(left, self.int_type)
                self.unify(right, self.int_type)
                return self.bool_type
            if op == "=":
                self.unify(left, right)
                return self.bool_type
            self.unify(right, _TCon("list", [left]))
            return right
        if kind == "if":
            cond = self.infer(node[1])
            then_type = self.infer(node[2])
            else_type = self.infer(node[3])
            self.unify(cond, self.bool_type)
            self.unify(then_type, else_type)
            return then_type
        if kind == "fun":
            return self.infer_fun(node[1], node[2])
        if kind == "let":
            name = node[1]
            params = node[2]
            self.level += 1
            if params:
                bound_type = self.infer_fun(params, node[3])
            else:
                bound_type = self.infer(node[3])
            self.level -= 1
            poly = self.generalize(bound_type)
            old = self.env.get(name)
            self.env[name] = (bound_type, poly)
            body_type = self.infer(node[4])
            if old is None:
                del self.env[name]
            else:
                self.env[name] = old
            return body_type
        if kind == "letrec":
            name = node[1]
            params = node[2]
            old = self.env.get(name)
            self.level += 1
            func_var = self.fresh()
            self.env[name] = (func_var, False)
            bound_type = self.infer_fun(params, node[3])
            self.unify(func_var, bound_type)
            self.level -= 1
            poly = self.generalize(func_var)
            self.env[name] = (func_var, poly)
            body_type = self.infer(node[4])
            if old is None:
                del self.env[name]
            else:
                self.env[name] = old
            return body_type
        raise SyntaxError("unknown node")


def _var_name(index):
    letter = chr(97 + index % 26)
    suffix = index // 26
    return "'" + letter + (str(suffix) if suffix > 0 else "")


def _show(t):
    names = {}

    def go(node, ctx):
        node = _prune(node)
        if type(node) is _TVar:
            key = id(node)
            if key not in names:
                names[key] = _var_name(len(names))
            return names[key]
        name = node.name
        if name == "int" or name == "bool":
            return name
        if name == "list":
            return go(node.args[0], 2) + " list"
        if name == "*":
            text = go(node.args[0], 2) + " * " + go(node.args[1], 2)
            return "(" + text + ")" if ctx >= 2 else text
        text = go(node.args[0], 1) + " -> " + go(node.args[1], 0)
        return "(" + text + ")" if ctx >= 1 else text

    return go(t, 0)


def _infer_impl(src):
    tokens = _tokenize(src)
    tree = _Parser(tokens).parse_program()
    inferer = _Inferer()
    result = inferer.infer(tree)
    return _show(result)


def infer(src: str) -> str:
    outcome = {}

    def run():
        try:
            outcome["value"] = _infer_impl(src)
        except BaseException as error:
            outcome["error"] = error

    old_limit = sys.getrecursionlimit()
    old_stack = threading.stack_size()
    started = False
    try:
        sys.setrecursionlimit(1000000)
        for size in (256 * 1024 * 1024, 64 * 1024 * 1024, 16 * 1024 * 1024):
            try:
                threading.stack_size(size)
                worker = threading.Thread(target=run)
                worker.start()
                started = True
                break
            except (ValueError, RuntimeError, MemoryError):
                continue
        if started:
            worker.join()
        else:
            run()
    finally:
        try:
            threading.stack_size(old_stack)
        except (ValueError, RuntimeError):
            pass
        sys.setrecursionlimit(old_limit)
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]
```
