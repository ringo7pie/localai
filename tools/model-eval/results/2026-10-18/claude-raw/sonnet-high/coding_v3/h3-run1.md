```python
import sys
import threading

_KEYWORDS = {"fun", "let", "rec", "in", "if", "then", "else", "true", "false"}
_DIGITS = "0123456789"
_NAME_START = "abcdefghijklmnopqrstuvwxyz_"
_NAME_REST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'"
_SINGLE_SYMBOLS = "(),+-*=<[]"


def _tokenize(src):
    tokens = []
    index = 0
    length = len(src)
    while index < length:
        char = src[index]
        if char in " \t\n":
            index += 1
        elif char in _DIGITS:
            end = index
            while end < length and src[end] in _DIGITS:
                end += 1
            tokens.append(("INT", src[index:end]))
            index = end
        elif char in _NAME_START:
            end = index + 1
            while end < length and src[end] in _NAME_REST:
                end += 1
            word = src[index:end]
            if word in _KEYWORDS:
                tokens.append((word, word))
            else:
                tokens.append(("NAME", word))
            index = end
        elif src.startswith("->", index):
            tokens.append(("->", "->"))
            index += 2
        elif src.startswith("::", index):
            tokens.append(("::", "::"))
            index += 2
        elif char in _SINGLE_SYMBOLS:
            tokens.append((char, char))
            index += 1
        else:
            raise SyntaxError("unexpected character %r" % char)
    merged = []
    position = 0
    while position < len(tokens):
        kind = tokens[position][0]
        if kind == "[":
            if position + 1 < len(tokens) and tokens[position + 1][0] == "]":
                merged.append(("NIL", "[]"))
                position += 2
            else:
                raise SyntaxError("'[' must be followed by ']'")
        elif kind == "]":
            raise SyntaxError("unexpected ']'")
        else:
            merged.append(tokens[position])
            position += 1
    merged.append(("EOF", ""))
    return merged


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def kind(self):
        return self.tokens[self.pos][0]

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind):
        if self.kind() != kind:
            raise SyntaxError("expected %s" % kind)
        return self.advance()

    def parse_params(self):
        params = []
        while self.kind() == "NAME":
            params.append(self.advance()[1])
        return params

    def parse_program(self):
        node = self.parse_expr()
        if self.kind() != "EOF":
            raise SyntaxError("unexpected token")
        return node

    def parse_expr(self):
        kind = self.kind()
        if kind == "fun":
            self.advance()
            params = self.parse_params()
            if not params:
                raise SyntaxError("fun needs a parameter")
            self.expect("->")
            body = self.parse_expr()
            return ("lam", params, body)
        if kind == "let":
            self.advance()
            if self.kind() == "rec":
                self.advance()
                name = self.expect("NAME")[1]
                params = self.parse_params()
                if not params:
                    raise SyntaxError("let rec needs a parameter")
                self.expect("=")
                bound = self.parse_expr()
                self.expect("in")
                rest = self.parse_expr()
                return ("letrec", name, params, bound, rest)
            name = self.expect("NAME")[1]
            params = self.parse_params()
            self.expect("=")
            bound = self.parse_expr()
            self.expect("in")
            rest = self.parse_expr()
            if params:
                bound = ("lam", params, bound)
            return ("let", name, bound, rest)
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
        while self.kind() in ("=", "<"):
            op = self.advance()[0]
            right = self.parse_cons()
            left = ("bin", op, left, right)
        return left

    def parse_cons(self):
        left = self.parse_add()
        if self.kind() == "::":
            self.advance()
            right = self.parse_cons()
            return ("bin", "::", left, right)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.kind() in ("+", "-"):
            op = self.advance()[0]
            right = self.parse_mul()
            left = ("bin", op, left, right)
        return left

    def parse_mul(self):
        left = self.parse_app()
        while self.kind() == "*":
            self.advance()
            right = self.parse_app()
            left = ("bin", "*", left, right)
        return left

    def parse_app(self):
        head = self.parse_atom()
        while self.kind() in ("INT", "true", "false", "NAME", "NIL", "("):
            argument = self.parse_atom()
            head = ("app", head, argument)
        return head

    def parse_atom(self):
        kind = self.kind()
        if kind == "INT":
            self.advance()
            return ("int",)
        if kind == "true" or kind == "false":
            self.advance()
            return ("bool",)
        if kind == "NAME":
            return ("var", self.advance()[1])
        if kind == "NIL":
            self.advance()
            return ("nil",)
        if kind == "(":
            self.advance()
            first = self.parse_expr()
            if self.kind() == ",":
                self.advance()
                second = self.parse_expr()
                self.expect(")")
                return ("pair", first, second)
            self.expect(")")
            return first
        raise SyntaxError("unexpected token")


class _TVar:
    __slots__ = ("level", "link")

    def __init__(self, level):
        self.level = level
        self.link = None


class _TCon:
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


_INT = _TCon("int", ())
_BOOL = _TCon("bool", ())


def _arrow(left, right):
    return _TCon("->", (left, right))


def _pair(left, right):
    return _TCon("*", (left, right))


def _list(element):
    return _TCon("list", (element,))


def _prune(node):
    root = node
    while isinstance(root, _TVar) and root.link is not None:
        root = root.link
    while isinstance(node, _TVar) and node.link is not None:
        following = node.link
        node.link = root
        node = following
    return root


def _bind(var, node):
    seen = set()
    stack = [node]
    while stack:
        current = _prune(stack.pop())
        if isinstance(current, _TVar):
            if current is var:
                raise TypeError("infinite type")
            if current.level > var.level:
                current.level = var.level
        else:
            if id(current) in seen:
                continue
            seen.add(id(current))
            stack.extend(current.args)
    var.link = node


def _unify(first, second):
    stack = [(first, second)]
    while stack:
        left, right = stack.pop()
        left = _prune(left)
        right = _prune(right)
        if left is right:
            continue
        if isinstance(left, _TVar):
            _bind(left, right)
        elif isinstance(right, _TVar):
            _bind(right, left)
        else:
            if left.name != right.name or len(left.args) != len(right.args):
                raise TypeError("type mismatch")
            stack.extend(zip(left.args, right.args))


def _generalize(node, level):
    variables = []
    seen_vars = set()
    seen_cons = set()
    stack = [node]
    while stack:
        current = _prune(stack.pop())
        if isinstance(current, _TVar):
            if current.level > level and id(current) not in seen_vars:
                seen_vars.add(id(current))
                variables.append(current)
        else:
            if id(current) in seen_cons:
                continue
            seen_cons.add(id(current))
            stack.extend(current.args)
    return (variables, node)


def _instantiate(scheme, level):
    variables, node = scheme
    if not variables:
        return node
    mapping = {}
    for var in variables:
        mapping[id(var)] = _TVar(level)
    memo = {}

    def copy(current):
        current = _prune(current)
        if isinstance(current, _TVar):
            return mapping.get(id(current), current)
        key = id(current)
        if key in memo:
            return memo[key]
        new_args = tuple(copy(arg) for arg in current.args)
        same = True
        for old, new in zip(current.args, new_args):
            if old is not new:
                same = False
                break
        result = current if same else _TCon(current.name, new_args)
        memo[key] = result
        return result

    return copy(node)


_MISSING = object()


def _builtins():
    env = {}

    def make(build):
        var_a = _TVar(0)
        var_b = _TVar(0)
        return ([var_a, var_b], build(var_a, var_b))

    env["fst"] = make(lambda a, b: _arrow(_pair(a, b), a))
    env["snd"] = make(lambda a, b: _arrow(_pair(a, b), b))
    env["hd"] = make(lambda a, b: _arrow(_list(a), a))
    env["tl"] = make(lambda a, b: _arrow(_list(a), _list(a)))
    env["null"] = make(lambda a, b: _arrow(_list(a), _BOOL))
    return env


def _infer_node(node, env, level):
    tag = node[0]
    if tag == "int":
        return _INT
    if tag == "bool":
        return _BOOL
    if tag == "nil":
        return _list(_TVar(level))
    if tag == "var":
        scheme = env.get(node[1], _MISSING)
        if scheme is _MISSING:
            raise NameError("name %r is not defined" % node[1])
        return _instantiate(scheme, level)
    if tag == "lam":
        params = node[1]
        saved = []
        param_types = []
        for name in params:
            var = _TVar(level)
            saved.append(env.get(name, _MISSING))
            param_types.append(var)
            env[name] = ([], var)
        body_type = _infer_node(node[2], env, level)
        for index in range(len(params) - 1, -1, -1):
            name = params[index]
            if saved[index] is _MISSING:
                del env[name]
            else:
                env[name] = saved[index]
        result = body_type
        for var in reversed(param_types):
            result = _arrow(var, result)
        return result
    if tag == "app":
        function_type = _infer_node(node[1], env, level)
        argument_type = _infer_node(node[2], env, level)
        result = _TVar(level)
        _unify(function_type, _arrow(argument_type, result))
        return result
    if tag == "bin":
        op = node[1]
        left_type = _infer_node(node[2], env, level)
        right_type = _infer_node(node[3], env, level)
        if op in ("+", "-", "*"):
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
        _unify(right_type, _list(left_type))
        return right_type
    if tag == "if":
        cond_type = _infer_node(node[1], env, level)
        then_type = _infer_node(node[2], env, level)
        else_type = _infer_node(node[3], env, level)
        _unify(cond_type, _BOOL)
        _unify(then_type, else_type)
        return then_type
    if tag == "pair":
        first_type = _infer_node(node[1], env, level)
        second_type = _infer_node(node[2], env, level)
        return _pair(first_type, second_type)
    if tag == "let":
        name = node[1]
        bound_type = _infer_node(node[2], env, level + 1)
        scheme = _generalize(bound_type, level)
        old = env.get(name, _MISSING)
        env[name] = scheme
        result = _infer_node(node[3], env, level)
        if old is _MISSING:
            del env[name]
        else:
            env[name] = old
        return result
    if tag == "letrec":
        name = node[1]
        params = node[2]
        function_type = _TVar(level + 1)
        old_function = env.get(name, _MISSING)
        env[name] = ([], function_type)
        saved = []
        param_types = []
        for param in params:
            var = _TVar(level + 1)
            saved.append(env.get(param, _MISSING))
            param_types.append(var)
            env[param] = ([], var)
        body_type = _infer_node(node[3], env, level + 1)
        for index in range(len(params) - 1, -1, -1):
            param = params[index]
            if saved[index] is _MISSING:
                del env[param]
            else:
                env[param] = saved[index]
        built = body_type
        for var in reversed(param_types):
            built = _arrow(var, built)
        _unify(function_type, built)
        env[name] = _generalize(function_type, level)
        result = _infer_node(node[4], env, level)
        if old_function is _MISSING:
            del env[name]
        else:
            env[name] = old_function
        return result
    raise SyntaxError("unknown node")


def _letter_name(index):
    suffix = index // 26
    return "'" + chr(97 + index % 26) + (str(suffix) if suffix else "")


def _format_type(node):
    names = {}

    def fmt(current, context):
        current = _prune(current)
        if isinstance(current, _TVar):
            key = id(current)
            if key not in names:
                names[key] = _letter_name(len(names))
            return names[key]
        name = current.name
        if name == "->":
            text = fmt(current.args[0], 1) + " -> " + fmt(current.args[1], 0)
            return "(" + text + ")" if context >= 1 else text
        if name == "*":
            text = fmt(current.args[0], 2) + " * " + fmt(current.args[1], 2)
            return "(" + text + ")" if context >= 2 else text
        if name == "list":
            return fmt(current.args[0], 2) + " list"
        return name

    return fmt(node, 0)


def _infer_source(src):
    tokens = _tokenize(src)
    ast = _Parser(tokens).parse_program()
    env = _builtins()
    node_type = _infer_node(ast, env, 0)
    return _format_type(node_type)


def infer(src: str) -> str:
    outcome = []

    def run():
        try:
            outcome.append((True, _infer_source(src)))
        except BaseException as error:
            outcome.append((False, error))

    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000000)
    started = False
    try:
        try:
            threading.stack_size(256 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        try:
            worker = threading.Thread(target=run)
            worker.start()
            started = True
        except RuntimeError:
            started = False
        finally:
            try:
                threading.stack_size(0)
            except (ValueError, RuntimeError):
                pass
        if started:
            worker.join()
        else:
            run()
    finally:
        sys.setrecursionlimit(old_limit)
    success, value = outcome[0]
    if success:
        return value
    raise value
```
