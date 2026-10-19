"""H3 infer の隠しテスト。モデルには見せない（形式は suites/coding/c1/tests.py と同じ）。

期待値は手で書き、reference.py（再帰下降 + レベル付きの単一化）と oracle.py（表による構文解析 + 置換の
Algorithm W）の両方と一致することを確かめた。乱数のプログラムは gen_programs.py で作り、両者の答えが
3,000 件で一致したもののうち 400 件を使う（tests/test_hard.py）。

2026-10-18 16:50 に直した（問題文は変えていない）: 乱数のプログラムに、名前の誤りと型の誤りが両方あるもの（どちらを先に
出すかは問題文で決めていない）と、if の直後に括弧なしの fun / let / if があるもの（問題文では構文の誤りなのに、
参照解が受け付けていた）が入っていた。構文が正しく名前の誤りの無いプログラムに作り直し、参照解とオラクルも問題文どおりに直した。
"""

FORBIDDEN_CALLS = ()

ERRORS = (SyntaxError, NameError, TypeError)


def _outcome(sol, src):
    try:
        return sol.infer(src)
    except ERRORS as exc:
        return type(exc).__name__


def _check(sol, t, pairs):
    for src, want in pairs:
        if isinstance(want, type):
            t.raises(want, sol.infer, src)
        else:
            t.eq(sol.infer(src), want)


def _checksum(texts):
    acc = 0
    for index, text in enumerate(texts):
        for ch in text:
            acc = (acc * 131 + ord(ch)) % ((1 << 61) - 1)
        acc = (acc * 1000003 + index) % ((1 << 61) - 1)
    return acc


def case_examples(sol, t):
    _check(sol, t, [
        ("fun x -> x", "'a -> 'a"),
        ("let id = fun x -> x in (id 1, id true)", "int * bool"),
        ("fun f -> (f 1, f true)", TypeError),
        ("fun f g x -> f (g x)", "('a -> 'b) -> ('c -> 'a) -> 'c -> 'b"),
        ("let rec len l = if null l then 0 else 1 + len (tl l) in len", "'a list -> int"),
        ("1 + y", NameError),
    ])


def case_literals_and_pairs(sol, t):
    _check(sol, t, [
        ("1", "int"), ("true", "bool"), ("[]", "'a list"), ("(1, true)", "int * bool"), ("(((1)))", "int"),
        ("((1, true), [])", "(int * bool) * 'a list"), ("([], [])", "'a list * 'b list"),
    ])


def case_operators(sol, t):
    _check(sol, t, [
        ("1 + 2 * 3 - 4", "int"), ("1 < 2", "bool"), ("true = false", "bool"), ("fun x -> x + 1", "int -> int"),
        ("fun x -> x < 1", "int -> bool"), ("1 < 2 = true", "bool"), ("1 = 1 = true", "bool"),
        ("fun x y -> x = y", "'a -> 'a -> bool"), ("true + 1", TypeError), ("1 < true", TypeError),
        ("1 = true", TypeError), ("(fun x -> x) = (fun y -> y + 1)", "bool"),
    ])


def case_lists(sol, t):
    _check(sol, t, [
        ("1 :: 2 :: []", "int list"), ("fun x -> x :: []", "'a -> 'a list"), ("[] :: []", "'a list list"),
        ("fun l -> hd l + 1", "int list -> int"), ("1 :: true :: []", TypeError), ("(1 :: []) :: []", "int list list"),
        ("1 :: 2", TypeError), ("1 + 2 :: []", "int list"), ("fun x l -> x :: x :: l", "'a -> 'a list -> 'a list"),
    ])


def case_builtins(sol, t):
    _check(sol, t, [
        ("fst", "'a * 'b -> 'a"), ("snd (1, true)", "bool"), ("null", "'a list -> bool"), ("tl", "'a list -> 'a list"),
        ("(hd, tl)", "('a list -> 'a) * ('b list -> 'b list)"), ("fst (snd (1, (true, 2)))", "bool"),
        ("fun p -> (snd p, fst p)", "'a * 'b -> 'b * 'a"),
    ])


def case_shadowing_builtins(sol, t):
    _check(sol, t, [
        ("let hd = 5 in hd + 1", "int"), ("fun fst -> fst + 1", "int -> int"),
        ("let null = fun x -> x in null 3", "int"), ("fun x -> let x = true in x", "'a -> bool"),
    ])


def case_curried_functions(sol, t):
    _check(sol, t, [
        ("fun f x y -> f y x", "('a -> 'b -> 'c) -> 'b -> 'a -> 'c"), ("fun x y -> x", "'a -> 'b -> 'a"),
        ("let k x y = x in k", "'a -> 'b -> 'a"), ("let k x y = x in k 1", "'a -> int"),
        ("fun f -> f 1", "(int -> 'a) -> 'a"), ("fun x -> fun f -> f x", "'a -> ('a -> 'b) -> 'b"),
    ])


def case_let_polymorphism(sol, t):
    _check(sol, t, [
        ("let pair x = (x, x) in (pair 1, pair true)", "(int * int) * (bool * bool)"),
        ("let f = fun x -> x in f f", "'a -> 'a"),
        ("let twice f x = f (f x) in twice twice", "('a -> 'a) -> 'a -> 'a"),
        ("let e = [] in (1 :: e, true :: e)", "int list * bool list"),
        ("let compose f g x = f (g x) in compose (fun b -> if b then 1 else 0) (fun n -> n < 3)", "int -> int"),
    ])


def case_lambda_bound_is_monomorphic(sol, t):
    _check(sol, t, [
        ("fun id -> (id 1, id true)", TypeError), ("(fun id -> (id 1, id 2)) (fun x -> x)", "int * int"),
        ("(fun id -> (id 1, id true)) (fun x -> x)", TypeError),
    ])


def case_no_generalization_of_environment_variables(sol, t):
    _check(sol, t, [
        ("fun x -> let y = x in (y 1, y true)", TypeError),
        ("fun x -> let f = fun y -> x in (f 1, f true)", "'a -> 'a * 'a"),
        ("fun x -> let y = x in y + 1", "int -> int"),
        ("fun x -> let f y = x y in (f 1, f 2)", "(int -> 'a) -> 'a * 'a"),
        ("fun x -> let f y = (x, y) in (f 1, f true)", "'a -> ('a * int) * ('a * bool)"),
    ])


def case_occurs_check(sol, t):
    _check(sol, t, [
        ("fun x -> x x", TypeError), ("let rec f x = f in f", TypeError), ("fun f -> f f", TypeError),
        ("let rec f x = f x x in f", TypeError), ("fun l -> l :: l", TypeError),
    ])


def case_let_rec(sol, t):
    _check(sol, t, [
        ("let rec fact n = if n = 0 then 1 else n * fact (n - 1) in fact", "int -> int"),
        ("let rec map f l = if null l then [] else f (hd l) :: map f (tl l) in map", "('a -> 'b) -> 'a list -> 'b list"),
        ("let rec f x = f x in f", "'a -> 'b"),
        ("let rec f x = (f 1, f true) in f", TypeError),
        ("let rec id x = x in (id 1, id true)", "int * bool"),
    ])


def case_let_rec_polymorphic_after_in(sol, t):
    src = ("let rec map f l = if null l then [] else f (hd l) :: map f (tl l) in "
           "(map (fun x -> x + 1) (1 :: []), map (fun b -> if b then 1 :: [] else []) (true :: []))")
    _check(sol, t, [(src, "int list * int list list")])


def case_if(sol, t):
    _check(sol, t, [
        ("if true then 1 else 2", "int"), ("if 1 then 2 else 3", TypeError), ("if true then 1 else false", TypeError),
        ("fun c -> if c then (fun x -> x) else (fun y -> y + 1)", "bool -> int -> int"),
        ("if true then 1 else 2 + 3", "int"),
        ("fun c x y -> if c then x else y", "bool -> 'a -> 'a -> 'a"),
    ])


def case_type_printing_parentheses(sol, t):
    _check(sol, t, [
        ("fun x -> (x, (x, x))", "'a -> 'a * ('a * 'a)"), ("fun x -> ((x, x), x)", "'a -> ('a * 'a) * 'a"),
        ("fun f -> (f, 1)", "'a -> 'a * int"), ("(fun x -> x) :: []", "('a -> 'a) list"),
        ("(1, true) :: []", "(int * bool) list"), ("fun l -> (hd l) 1", "(int -> 'a) list -> 'a"),
        ("fun p -> fst p + snd p", "int * int -> int"), ("fun f -> f (1, 2)", "(int * int -> 'a) -> 'a"),
        ("fun x -> (fun y -> x, x)", "'a -> ('b -> 'a) * 'a"),
        ("fun l -> hd (hd l) :: []", "'a list list -> 'a list"),
    ])


def case_type_variable_naming_order(sol, t):
    _check(sol, t, [
        ("fun x y z -> (z, (y, x))", "'a -> 'b -> 'c -> 'c * ('b * 'a)"), ("fun f x -> f", "'a -> 'b -> 'a"),
        ("fun x -> fun f -> (f, x)", "'a -> 'b -> 'b * 'a"), ("fun g -> fun f -> f g", "'a -> ('a -> 'b) -> 'b"),
    ])


def case_more_than_26_type_variables(sol, t):
    params = [f"v{i}" for i in range(30)]
    src = "fun " + " ".join(params) + " -> (v29, v0)"
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = ["'" + letters[i % 26] + (str(i // 26) if i >= 26 else "") for i in range(30)]
    t.eq(sol.infer(src), " -> ".join(names) + f" -> {names[29]} * {names[0]}")


def case_name_errors(sol, t):
    _check(sol, t, [
        ("y", NameError), ("fun x -> y", NameError), ("let x = 1 in z", NameError),
        ("let rec f x = g x in f", NameError), ("let f = f in f", NameError), ("fst2", NameError),
    ])


def case_syntax_errors(sol, t):
    _check(sol, t, [
        ("1 +", SyntaxError), ("(1, 2", SyntaxError), ("fun -> 1", SyntaxError), ("let x = 1", SyntaxError),
        ("let x 1 = 2 in x", SyntaxError), ("[ ]", SyntaxError), ("[1]", SyntaxError), ("1 > 2", SyntaxError),
        ("1 ; 2", SyntaxError), ("X", SyntaxError), ("let rec f = fun x -> x in f", SyntaxError),
        ("(1, 2, 3)", SyntaxError), ("()", SyntaxError), ("", SyntaxError), ("1 2 )", SyntaxError),
    ])


def case_keyword_expressions_need_parentheses(sol, t):
    _check(sol, t, [
        ("1 + let x = 1 in x", SyntaxError), ("hd fun x -> x", SyntaxError), ("1 + (let x = 1 in x)", "int"),
        ("if true then fun x -> x else fun y -> y", "'a -> 'a"), ("let x = if true then 1 else 2 in x", "int"),
        ("(if true then 1 else 2, fun x -> x)", "int * ('a -> 'a)"), ("1 :: if true then [] else []", SyntaxError),
        ("fun x -> x = if true then 1 else 2", SyntaxError), ("(fun f -> f (fun x -> x)) (fun g -> g 1)", "int"),
    ])


def case_syntax_errors_come_first(sol, t):
    _check(sol, t, [("true + 1 +", SyntaxError), ("zz )", SyntaxError), ("fun x -> x x )", SyntaxError)])


def case_names_and_reserved_words(sol, t):
    _check(sol, t, [
        ("fun in -> in", SyntaxError), ("let then = 1 in then", SyntaxError), ("fun x' -> x'", "'a -> 'a"),
        ("fun _x -> _x", "'a -> 'a"), ("fun rec1 -> rec1 + 1", "int -> int"), ("fun letx -> letx", "'a -> 'a"),
        ("fun iff -> if iff then iff else true", "bool -> bool"),
    ])


def case_whitespace_and_layout(sol, t):
    _check(sol, t, [
        ("fun\tx\n->\n  x", "'a -> 'a"), ("(1,true)", "int * bool"), ("1::[]", "int list"), ("fun x->x", "'a -> 'a"),
        ("1-1", "int"), ("  let  f  x  =  x  in  f  ", "'a -> 'a"),
    ])


def case_random_programs(sol, t):
    t.eq(_checksum([_outcome(sol, src) for src in PROGRAMS]), EXPECTED["random"])


def case_performance_deep_parentheses(sol, t):
    t.eq(sol.infer("(" * 300 + "1" + ")" * 300), "int")
    t.eq(sol.infer("(" * 150 + "fun x -> " + "(" * 140 + "x" + ")" * 290), "'a -> 'a")


def case_performance_deep_lets(sol, t):
    src = "let x = " * 300 + "1" + " in x" * 300
    t.eq(sol.infer(src), "int")
    chain = "let f0 = fun x -> x in " + "".join(f"let f{i} = fun x -> f{i - 1} (f{i - 1} x) in " for i in range(1, 299))
    t.eq(sol.infer(chain + "f298"), "'a -> 'a")


def case_performance_many_nested_functions(sol, t):
    src = "".join(f"fun x{i} -> " for i in range(300)) + "(x0, x299)"
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = ["'" + letters[i % 26] + (str(i // 26) if i >= 26 else "") for i in range(300)]
    t.eq(sol.infer(src), " -> ".join(names) + f" -> {names[0]} * {names[299]}")


def case_performance_long_program(sol, t):
    lines = ["let f0 = fun a b -> a < b in"]
    for i in range(1, 290):
        lines.append(f"let f{i} = fun x y -> if f{i - 1} y x then x < y + {i} else f{i - 1} x (y * 2) in")
    src = "\n".join(lines) + "\nf289"
    t.eq(len(src) > 15000, True)
    t.eq(sol.infer(src), "int -> int -> bool")


EXPECTED = {'random': 1034339442801930996}
PROGRAMS = [
    'let q x y = fun k x -> let x = fun y -> fun g -> 9 in (fun x -> snd) (let n = null in true) in snd',
    'null (if (let g = null in hd) :: (let rec k y = snd in true) then (fun p p -> null) = (fun h -> fst) else 9) ((fst :: (let rec f q = q in f)) (let rec f n h = if 6 then [] else f in 0) :: (let rec x q = snd 8 in 0 null) (0 + (let l = null in l)))',
    'fun l l -> fun y -> ((y, (fst, false)), fun n p -> if false then 9 else true)',
    '(let n p = fun l h -> ([] * []) (let y = hd in p) in 6 (let l = n in l) ((n, n), let k l p = p in n)) * ((let q = let x g = g in false in q < []) (snd fst (let k = true in k)), fun p -> (fun g -> p) (fst true))',
    'let l = (fun h -> let p = h in []) (fun l f -> let f q n = n in f) + hd in l * (fun g -> fun h -> let h = false in h)',
    '(fun h -> []) = []',
    '(let rec k x = let y = let g h = let h n = 4 in k in fun x -> 8 in (6 = 8) (k - []) in (let q x = fun h -> k in false, ((k) < k, k []))) (if (if (let g x y = x in g) :: (let rec h y = null in []) then [] else (if 7 then null else 0) ([], 8)) then null else fun y -> y)',
    '[]',
    'fun l -> fun g g -> ([] + (fun y -> hd)) (fst tl, l 4)',
    'fun x h -> ((let y y f = let rec p k = false in [] in let l q = x in []) :: (x :: true) :: (if true then [] else x)) (let rec h y q = [] (fun y x -> false) in let g q = let p x = false in [] in (x) g)',
    'hd',
    'let rec h g h = (let f = (if [] then h else snd) - h in if h 6 then (tl, h) else [] g) [] in (let rec x x = (fun n l -> []) - (fun f -> h) in (fst = h, fun f h -> tl)) (fun y -> (let rec g x = tl in y) (let l g n = n in 4))',
    '((let x n = snd in let g g = let rec y k f = [] in fst in let q = x in q) :: hd, fun p -> (let rec q p l = p in p, fun q -> q) (hd = (p < p)))',
    'fun g y -> if (if 5 (let rec x x = true in tl) then ([] < y) :: (let k = y in null) else g) then fun l -> if g then let rec k g = k in [] else let g = l in [] else (let rec h k h = h in g) (let f k = g in g) (let y l x = snd in if y then g else y)',
    '(fun g x -> let x = fun x -> x * g in tl) tl',
    '(let rec h x h = if (fun g q -> let x f = h in h) then let f = x in 5 else let f h = h in snd in fun p x -> (2, 3) (false h)) * []',
    'let x x p = null in let rec q k g = ((fun k -> []) (false - false)) (fun p -> fun n n -> 0) in fun n y -> tl',
    '1',
    '(let g = (let p h l = tl in let rec k p = p in p) (let rec p f h = hd in fst - p) in if (if (if g then g else 0) then g 0 else let rec k q n = g in g) then fun x -> g else (g) g g) :: ((hd) = (let rec x n = ([] - 3) x in (fun x -> 3) < x))',
    'let y g = fun h x -> ([]) g snd (let g = if h then g else x in false null) in fun g k -> let q k y = let f = g in let x = f in 0 in ([], let n y q = g in y)',
    'snd',
    'if (fun h h -> false) then (let rec k q = fst in (fst, let rec f x n = k in f)) 2 else (let h = let l = fst in null in h h) ([], hd) (((null < 5) * tl 5) hd)',
    'if (if snd then (let y = let h h q = h in 1 in y + [], let n h l = l in n) else ([] true < tl fst) (let q f h = h + snd in if false then true else q)) then true else fun n g -> false ((let f n = true in 9) * (fun h q -> n))',
    '[] < true',
    'let p q l = ((let h q h = q false in l null) :: (let h x = x in []) (let n k = q in q)) (let rec k k = k in let g n = [] in fun g l -> 8) in true',
    'snd',
    'let l = (false, (hd 0 :: hd) * (fun l f -> 2)) in ((let h p = p p in [] ([])) - (let l = if 2 then fst else true in [] fst)) (fun x -> (fun k f -> 9) - (fun x -> 7))',
    '(let rec f x p = null in fun k n -> k, 9 + ((fun g f -> 6) + 1) (fun y -> y))',
    '(let y n = (let rec x x = [] in x n) * (n - (let f = n in 6)) in (let rec x k x = false in snd) (y false) :: (if fst < y then y y else y + y), (let rec k q = fun y g -> [] [] in (let g = k in g) - [] k) * (fun l y -> hd))',
    'hd = (fun y y -> (fun f l -> false) (y, [])) + (fun x -> false x (fun h -> tl))',
    'snd',
    'fun g x -> true',
    'if (let l = (let l = 2 in l) :: [] - snd = (hd < (let h y = y in h)) in ((let rec y g p = g in []) (fun h q -> [])) 4) then 7 else if (if tl then null else snd) (let f = 1 in []) = (let rec f f = (3, snd) in 8) then ((if tl then tl else []) (snd hd), 9) else fun n l -> fun p -> if false then fst else n',
    'fun y -> (fun n g -> fun y f -> y, let rec y y = let n g g = tl in false in y false (if 9 then false else true))',
    '(if hd then (let f q = q * q in f 4) snd else let rec y p f = null in fun k n -> hd = []) * (let rec g n = (let q = if null then n else hd in g) - ((if g then n else hd) - (let h = true in null)) in g * (fun f -> g 4))',
    'fun n k -> n',
    'let rec k q = ((if hd q then let rec f f q = null in q else false q, fun x -> [] :: false), ((fun l x -> 8) + (null :: [])) q) in (fun p -> k) (k (8)) (k * (let q = k in k)) - (fun h -> k (k null))',
    '(if hd then fst else null (fun q -> fun x k -> q)) []',
    '(let rec l g = (let q q = true = l in let x q = fst in x) (g (hd < l)) in fun f g -> fun h -> let n l = true in g) :: (hd * tl - (if tl then 3 else fst)) (fun q x -> (q) q) + (let p = fun n -> true n in p)',
    'let q y = fun k g -> fun x k -> g in 8',
    '(5 * []) false ((fun y -> y) (if 1 then tl else [])) (let h y p = (tl, snd) + true snd in 8) (true (let x = (let rec f l = 3 in 0) = ([] < hd) in 9))',
    'let x = let rec g h = fun p -> (let n = h in []) (fun k h -> k) in (if [] then 4 1 else g) < (let rec p n = n false in false g) in if (let rec g x = false in let l l = let rec k f = 2 in k in g) then let p = 8 in let rec y n = if x then 2 else [] in p else (let l = null [] in 0 - 5) (let rec k p l = let h n = [] in k in (x, k))',
    'let rec y n = ((fun q -> 7) null (fun l -> y - fst), true) in fun x x -> let l y = (let k = [] in []) = 5 in (let rec y p = null in [], fun y p -> null)',
    '(fun y y -> let f h q = [] false (fun p -> []) in (fun f -> 9) = (7 < f)) (if (let h = fun f -> (null, hd) in if (if h then null else h) then let h h = h in h else fun g -> true) then let rec g y = if [] y then (y, []) else g (false) in g else (let k = 4 in (5) k) - (fun h -> [] :: 1))',
    'fun g -> let k = false in fun h -> fun x g -> (x, h)',
    '[]',
    'fun l k -> k = (5)',
    '(fun p q -> [] (let k l = false in 8) (hd p - (fun f g -> p))) (null (let h p f = (let n = p in f, if [] then p else p) in 1))',
    '(let x x = (let p h = [] < false in let rec f h y = h in []) < (if [] x then let p = false in x else let rec x f = [] in x) in 1) * (((if [] then snd else fst) snd :: (hd, tl)) * (let g n f = fst tl in fun g g -> 4) (fun h y -> let n = y in y))',
    'let q q = 4 (let g y y = fun q -> 5 in 7 - [], 7) in (((if 6 then [] else q, true)) < (let rec h p n = h p in h q)) 2',
    'fun p n -> n * ((let n = n in let k n = n in n) * p)',
    'let rec g l y = (if (l, l) then 4 * l else let k = [] in []) :: (fun p -> fun q q -> tl) = (fun k -> false * []) l in (fun g -> fun n p -> g = fst) g',
    'null (let n n = if n 4 ([] + n) then n else n n (fun q -> []) in fun g l -> (6 [], let x = l in g))',
    'let f g n = g in (let rec l f x = let x = let rec g n f = f in l in true in fun q f -> let n y g = snd in f) < true',
    '(fst ((let rec h g = h in let rec x x = h in 0) = tl)) (fun y n -> (let k l = y in fst, (n, y)), (if 7 then let rec y g = g in y else let f n x = hd in []) ((let g n n = n in g) (snd, snd)))',
    'fun k -> let k x g = k in 2',
    'if true then [] else null = (let p = let p y x = hd = [] in p false in 5)',
    '(fun k f -> fst f (let g = null in f) ((fun q p -> false) (let p k q = true in p)), tl)',
    'if hd - ((let y = fun f q -> f in let p q h = null in true) + (let q x x = fun l -> hd in q q)) then fun l h -> if (true - [], if 0 then l else tl) then (7, h) (fun f g -> null) else [] 3 < h 6 else (let rec p k = fun f g -> fun h -> 2 in fun q p -> let h l = p in [], ((null :: tl) :: (if hd then false else 6)) (let rec q q n = q true in (hd, 5)))',
    '((if (let f n q = let rec f p = 6 in n in f f) then (let f = 3 in hd) ([], []) else let rec f k h = 8 f in let rec y k y = f in y) + (fst - tl :: hd) * (let n = null in fst) (let x h q = q in 9), null)',
    '(let p g y = let rec g n = true in let n h x = (0, y) in 8 g in (if (fun p -> p) then p = p else fun p l -> []) (fun n q -> let rec x h = [] in []), (let q = null in fun y -> fun k -> fst, if (let x = hd in x) + [] then (7) true + (let q g l = 7 in 1) else (snd, null) (let x = snd in true)))',
    'tl',
    'fun f -> null',
    'fun x y -> (fun x -> (x * x) (x < 6)) (x (true) y (let l k p = fun y -> y in [] + []))',
    'fun k -> (let rec h x p = let l = 7 false in let x n = h in hd in if true then fun y -> h else if k then [] else k) :: (k k - k * 9) (let rec q p = k in k, [] 9)',
    'let rec l y = (let l y l = let x g = y in let rec k g = l in k in let rec h x = l in y l) + [] in []',
    'let rec p f n = let f q = fun g -> ([] :: q) :: (let h = tl in q) in ((let q x = p in f) + (if fst then tl else 9)) = (p = (let n g = f in f)) in let y p = p in 7',
    'fun x n -> ((if 2 then 0 else fst) :: (fun l f -> false)) ((fun x f -> f) (tl :: 3)) * (let g g = (if x then g else 9) :: (let g = n in 7) in (let rec g h = [] in n, let k x = x in k))',
    'let h q y = [] in h',
    'true',
    '(let rec n l = [] n (let rec k f h = 6 in k) (fun k -> let p = l in 2) in if (let q = let n q = [] in [] in (6, 5)) then n else fun n -> n) = (if (if tl :: 2 then fun n g -> 9 else let p h = h in 9) then [] else (fun x -> true) * (fun g -> g)) - fst',
    'snd',
    'fun h -> []',
    '(let k x f = (fun h -> x = h) + (tl (x) < (let y l g = false in hd)) in fun x -> let rec g k g = let h h f = x in hd in (4, g)) (fun y h -> snd)',
    '(if (fun y -> y + y) - [] * 1 * (fun f x -> []) then null 5 else fun q -> (fun h -> [], q q), tl)',
    'let k l = let f g l = false in fun n l -> ([], let p g q = l in []) in fun k x -> if (if (let rec p p k = p in k) then 9 else let x f f = false in hd) then let rec f n = false [] in k else (0 (false), true + 5)',
    'fst',
    '((if 4 then 5 else fst) (tl snd) (if 1 9 then tl else fst) + (let rec n y g = (let p q f = n in []) (let rec p l = null in y) in (let f = [] in fst) - (if n then n else []))) * (let n f = let f l x = 9 l in fst false in let g h g = let g f g = [] in 1 in (snd, g), fun x l -> fun f p -> f l)',
    '(let rec l l = let n = if (fun y p -> 5) then (true, null) else fun p n -> 6 in 0 [] l in (let p = (l) * l in hd + fst) ((if 7 then l else l) true)) ((let rec p l f = f = (let h = l in p) in (fun q -> true) (p, 2)) (let rec x x = x in fst (x x)))',
    'fst (if (fun l -> l) 8 then (fun q g -> tl, [] - 5) else let h = false null in h []) - (fun x f -> fun h k -> (fun y -> x, [] + true))',
    '((snd = false) * [] * (if 6 then [] else null, fst)) true - (null, let y f n = let f = snd in f in y 8) ([] < tl ([] []))',
    'let l h p = false (fun l p -> (p * p) (h, p)) in let n y g = (fun k -> fun x q -> g) (g snd l) in let y = let rec k q q = fun k -> false in 4 in (fun x -> []) :: n 8',
    'tl',
    'fun g -> let x = if (fun k q -> q = []) then [] else fun g -> g in if false :: (let f q = g in 6) then g (fun n x -> g) else (g 6, x = g)',
    'fun q q -> q',
    'let rec y n l = fun k l -> (snd < (fun k -> [])) (fun p -> n, (n, 5)) in let rec f l f = f in (f, y) f f',
    '(let rec n l = let p n = let k n = n in let x h h = h in 5 in let n q n = p * snd in if 7 then p else 3 in (let rec p h = if n then h else hd in let p l = l in 7) * n) hd',
    '(let p x = let p = fun q g -> true in p in let rec x q f = fun y p -> p p in (let rec y g = y in y) (([]) x)) hd',
    '(let p g q = (let rec h l l = fun l g -> snd in [] - g) (fun l g -> 1, q) in p) (if (let y n l = n in false :: y) then (fun n p -> n, [] = tl) else [], ((hd, true) :: hd) (snd (fun f -> f)))',
    '(if (if null then [] else true) then 9 else 4 true) true [] (let f = (fun p -> p) 0 in f, (let l h n = fun g h -> h in let q n l = n in true, (hd snd, hd)))',
    '(let q = (let g k = fun h p -> 7 in snd g) (let rec h n = 2 2 in fun l q -> false) in fun q -> []) < (null :: (let l n g = fst (n) in null l)) (fst (fun h -> h) fst)',
    'fun y l -> fun g -> if (y < 8) * g false then (fun l -> []) + (fst) l else 2 = ([] < g)',
    'let rec x h n = let y = fun x p -> 1 x (h + (h)) in (x tl + (let f q = false in f)) ((let y x q = x in n) < true * []) in x',
    '(let p = fun h k -> k in 9) + (let rec l f k = let rec l h n = (fun p g -> n) (k l) in [] [] (let rec k f = [] in 8) in l)',
    'let rec y l = (fun q -> (hd, q) < (y < [])) ((fun y -> let p l = hd in 2) (y (fun f -> 3))) in if (let rec h h = fun g q -> y * h in let x y l = 1 y in fun k x -> []) then true else (let q = [] in hd, let y k p = snd in false) null',
    'if (fun f -> let l p g = (f, 2) in fun l -> l, []) then ((fun g p -> g + p) < (if (fun x -> []) then hd * false else fun h q -> 1)) (((fun q n -> fst) = tl :: 4) (fun g p -> g = (g))) else null ([] 7) (fst 0) (let x f h = (null, true) < (fun l -> tl) in let l = let rec p n = p in x in false)',
    'fst',
    '[]',
    'let l n p = let f q = (let rec h f = if [] then n else 1 in let rec x p y = 7 in true) (fun q f -> n) in 1 in fst',
    '(fun p g -> ((let q = g in p) - (if p then [] else 7)) * (fun y k -> k) (let rec q g = snd in snd)) * ((if (fun q -> let rec q h = q in q) then [] (fun x h -> false) else let q = fst * snd in let q k = 7 in 5) + (let y n = 6 in (let g k n = tl in g) (y * snd)))',
    'let rec l n y = y in fun f n -> let rec p f = (fun y -> fst) (5 * f) in false < (let k q n = n in [])',
    'snd',
    'if tl then ((let h = if tl then tl else fst in fun p l -> l) < (let l = let p x = 4 in 2 in 3 * l), (let rec q x y = (q, y) in if true then [] else q, 8 fst :: (let p = false in []))) else false',
    'if hd then [] else if (null, ([] :: hd) (fun g -> [])) then 3 else 7',
    'let g n = let x p x = p in snd in 6 g',
    '(if tl then (fun g k -> if [] then k else g) ([] (hd + null)) else let l = [] in (fun n -> 0) < (fun l k -> 4)) < (fun k h -> let rec f g g = fun f l -> fun q x -> fst in ([], k) (f < k))',
    'fun n -> fun p -> let y = fun l -> 3 false in 7 true snd',
    '(let x h k = tl in let p q = q in let q p = p in x) (fun l l -> l) (fun x -> let rec l x g = let l l = fun f -> false in tl in fun g y -> null * x)',
    'fun l -> (fun k f -> ([], f) f) fst',
    '(tl * snd snd) (let q q = true < q in []) (let q f = [] in (let f = 8 in f) - (let rec y y = false in q)) (let rec p k = fun x -> x in 6)',
    '(fun k -> (let rec h g = [] in h) (let q h = k in [])) ((let k = fun p -> tl in []) ((fun y x -> 2) snd)) * fst',
    '(if tl then let h f = (if true then null else []) (fun k -> f) in h else snd) ((let h y p = false (fun h p -> 1) in fun n q -> if false then h else []) :: (let rec y q = false in snd [] y))',
    'snd',
    'let f k q = let rec x p = (fun q f -> (null) < f, []) in (let x l = fst :: 0 in x = x) - [] ([] null) in if (f snd = (let g = f in f), f) then let rec k l = let rec q y = y [] in l < 9 in k else (if (f, f) then fun n p -> [] else fun p -> p) - (if (fun n -> n) then tl else let rec x q x = [] in x)',
    'let rec n l h = (let y = false (false + n) in (let h k = [] in [], n)) (if (fun h g -> fun g y -> 3) then l else fun q p -> let q f = q in n) in fun n l -> 5',
    '((let rec n k = k n in (false, tl)) < (let g = hd in g) tl) ((fst [] = (let g q = q in g)) (let rec g g = ([], fst) in fun x -> false)) + (fun f k -> false) * (let rec n x h = if true then fun y l -> true else fun x q -> q in (n < 8) (null true))',
    'if (let l g h = h in (fun y -> fun x y -> 9) - l) then ((let p l f = f in p) < (let l k = 9 in null)) (fun y -> y) (let l = tl in l l = (if l then 7 else 3)) else snd',
    'fun f k -> let k q n = q in true',
    'fun k -> (let rec q q = true + [] in 2) :: (let l f g = let q = hd in 1 in fun x -> 9, (fun g k -> g) (k, snd))',
    'let rec g f = (fun q q -> (q, false)) < (g + 2) * (let rec h l = fst in []) < (if (let rec n q k = k in g) then if 0 + g then let q q = q in q else fun p -> 2 else (f, 4) (f snd)) in let rec f n y = (g, g) (let l = [] in hd) = (f < y g) in g',
    '(let rec x l y = let rec l h = fun g -> let l = l in l in let f q = 1 in l in fun g -> x) ((tl (hd :: 1), if null then if [] then tl else [] else snd = snd) (snd, let rec g y = let n x f = 9 in n in fun g -> g))',
    'let y l x = (let x p k = (p, k) in l * (x)) [] + ((let rec f p g = 0 f in 2 :: l) < (fun g -> fst) (tl tl)) in (fun x l -> if (let y x n = hd in []) then fun x p -> 9 else 0) fst',
    '(let k p x = [] in (fun f p -> p * true) (fun k -> if fst then k else true)) :: (if (let rec g k h = let rec n f = tl in g in (fun l -> l) 9) then (hd, fst) (false tl) (fst ([] 2)) else let h y = y y (y null) in h = h * true)',
    '((if (if null then 9 else fst) then (tl, []) else snd) null :: false) (let p g n = n (false, null) n in (if (if [] then tl else null) then 2 p else p = []) ((let rec n y l = l in n) snd))',
    '(if (fst + hd, let p = [] in p) - ((hd, fst) < false - (5)) then if tl then if [] snd then [] else if [] then [] else [] else fun g -> let rec k k p = p in null else let y q = let rec k x y = x k in true k in fun g -> fun n -> fst) + (if (fun k p -> k) * (false) [] * 8 then 2 else snd (tl (fun l x -> x)))',
    'snd',
    'fun k k -> (fun g -> fst) (let y = [] in k) (k [] (k k)) :: (if k then null else k) ([] < k) * (false :: k, 5 + [])',
    'let l g k = 0 in fun h n -> ((n) < true) (fun l n -> fst) (let rec y h l = 2 in true)',
    '[] (fun f -> let rec x g = fun f p -> fun n y -> f in (let f = f in 5) (if x then hd else x))',
    'let q k h = k in false',
    'if null then fun h -> (let f = h 4 in fun n -> [], let rec n y f = let h y = [] in [] in true) else snd',
    'if ((let rec l p = 1 in null) (tl tl) - (snd = false), let rec n p n = (fun y -> n) (fun n -> []) in let p y x = y y in n - p) then fst else let h f p = if null [] (let rec q y f = 9 in fst) then if (if 1 then p else tl) then let n l h = p in 8 else let f p x = [] in [] else let rec h y g = fun l k -> 2 in f h in true',
    '((let q k f = [] in (null hd) (let l = q in q)) < ((fun y h -> h) = snd :: 5) ((let h n = [] in false) (hd - tl))) ((let p = hd in (let q = p in p) (let h g = 2 in p)) (fun h -> (let k y g = 2 in h) true))',
    'fun p x -> snd',
    'let q g = (let f x k = let rec f g = f * g in f [] in (f = f) (fun h -> true), (let y g y = y + 1 in fun k -> y) < (g) null []) in (((fun x x -> []) :: (fun q y -> [])) fst, (let f = 8 < q in true (q)) [])',
    '(let rec x h q = ([] < q) (let rec q q = h in h) x in ([], fun k y -> y = 5)) null',
    '((let y h f = (7) - fst :: (let rec g q = 5 in g) in [] null (false :: 0)) + (let k x = [] in (k, let rec g g = 0 in null))) false',
    '(fun y l -> ((fun n k -> y) - (let rec l f f = false in l)) l) = (if 3 then fun q g -> fst q < ([] = []) else let rec g l k = let n = [] l in 2 in fun g k -> g :: [])',
    'hd + (if (hd * fst) (let rec g x = x in false) (fun f l -> 8 :: l) then true else [] = (let rec n g = tl = [] in fun n n -> n))',
    '(null [] = ((fun f n -> 6) :: (let rec h q k = 2 in h), ([], fst (snd))), hd :: (let f = let rec k p n = n in 7 in let rec q x g = q g in if q then 5 else q))',
    '(let rec k x = x in k) (fun f l -> fun f f -> [], [])',
    'fun p p -> 9',
    '((let q l l = (true, l :: true) in (q < q, q)) :: (fun x p -> fun k -> p - tl)) (((6 * fst) (if [] then [] else null), [] (if 0 then false else 3)) (let g l l = if [] + 2 then fun k k -> false else l fst in fun x n -> n))',
    '(let q g = fun f x -> (let x x p = 9 in 5, let q = g in null) in (hd - [] = q q) (let h = fun h -> q in fun y p -> h)) ((fun x -> if [] then let q x = [] in [] else fun k p -> tl) - (let rec q p p = [] < hd p in fun g g -> false g))',
    '(8 - (let rec l h k = (h, []) in fun k -> k, (fun g n -> []) + []), fun l n -> 0)',
    'null',
    '((fun p -> (let x = p in []) (if fst then [] else false), snd), let l = hd in fun l -> let k n y = snd = n in k)',
    'if (let y n = n in let q h k = [] in true) then (fun n y -> [] false) (let y y = fun q q -> q in fun q -> []) = (if (if [] then fun h -> h else null tl) then (hd, []) = [] [] else snd) else if tl then (fst, [] fst (if tl then 2 else hd)) else (snd snd, let n n = n in n) (snd)',
    'false',
    '((if hd then hd [] else fun l -> l) :: (let rec q n = let rec y p = p in 5 in let l f = q in l) = []) + (((2, 0) < (hd, 5)) - 5 (if tl then snd else null)) (let f x = null in 1 fst (true f))',
    'tl (fun x -> let rec g y = let x = y in [] in snd, let rec l f q = let h p l = let q n = f in l in false in if 2 then [] else null)',
    '(fun g y -> (if (if null then y else y) then ([], tl) else 5) (fun l f -> 7 []), fun f h -> (fun x -> [] :: true) + (fun f -> f) (h false))',
    'if (if null then ((fun h y -> h) + (1 + snd)) (fun q -> if q then q else q) else (null :: (if 2 then tl else hd)) (let k p = fun g -> null in k)) then let n p p = true (fun q k -> fun g p -> tl) in let x q = (let rec k q x = n in q) - (n :: (7)) in fun p l -> hd else (snd, (let rec l x = 0 in []) (fst true)) = (fst) tl + null',
    'snd',
    '((if (let f y = false in f) then 1 else null, let h q x = [] [] in h tl), false) = tl - (let rec h g g = ([], hd) (let p p h = h in 8) in [] 4 (let y q = false in []))',
    'fun n n -> 2',
    '((let f p = p in tl, 1 < null), fun n q -> let q p = hd in false) ((if 7 then [] else tl, 8 null) (let g h = true h in let h n = g in g)) :: (fun p k -> (let rec g f = k in []) - (let g g k = [] in g)) (let p y = (let n = y in y) 6 in (snd + p) * (let rec q q n = p in q))',
    'let f q l = hd in if f then fun q f -> false else let n f = [] in (if n then 3 else f) + n n',
    'fun q -> (fun p q -> (q, 6) - (let q = q in 7)) (fun k y -> fun q -> let n k = [] in y)',
    'fun k -> (let rec n q f = fun k n -> if k then null else snd in [] snd * true []) (((let g x p = hd in 9) (if k then k else k)) < (k))',
    'tl (fun l y -> fun k -> (if k then [] else k) * (let q k = k in k))',
    'let rec h y = let rec p n = false in let rec k n p = let rec h y p = let rec g p g = [] in [] in fun f -> fst in if tl true then y :: h else k in let p x = (null, let rec p f k = p 3 in (x, h)) in p',
    '(fun g -> g) null (let n h = (fun f q -> h) :: [] h in (let rec q g l = n in q) = n) = (fun h -> h (h h) (snd h (null hd)))',
    '[] (let g = null in [] false)',
    '9',
    'fun h g -> fun g h -> fun g -> (fun h q -> []) (fun n -> g)',
    'null',
    '(let h = (fun p -> let rec h f x = 3 in 1) - (([] :: null) - (6 - hd)) in let rec n f g = let y = let rec n n f = 7 in null in f in []) (let g k = let n = fun g -> (fst, tl) in (let rec k n = [] in k) (let rec q l = 3 in []) in [])',
    'fun p g -> let rec p q f = (let rec k l n = [] [] in 8) (let rec n q g = (f, []) in if q then f else fst) in ((let g = 9 in null) (let y y p = y in g), (let l = false in tl) * p p)',
    '((let l g = fun y f -> null in l l) < tl [] (8 (hd)), (fun q h -> fst) - (tl, null) + (let g = (hd, hd) in fun x h -> x)) * (let n n h = (if (fun q -> 0) then fun n g -> null else (n, hd)) :: (if (let rec g h q = 0 in true) then [] false else let x = n in fst) in if true [] then (n < n) (let rec f h l = 7 in n) else if [] < snd then let y = n in hd else let rec n p g = fst in [])',
    'let k h = fun h g -> fun y -> fun x x -> (y, 6) in fun k f -> k',
    'null',
    'fst',
    '(((fun q -> [] * (q)) = tl, fun l -> let h y = y in h), (let q = [] in let g f = if q then f else q in fun x -> q) - (let x p = (1, p) in 2 x) (true - tl < hd snd))',
    'fun k f -> ((let q f = hd hd in q) = (fun q k -> 1 k)) :: ([] 7 < (fun y p -> fun f -> []))',
    'let rec n f g = ((g, (n, g) hd), (let k = [] in let rec k y = n in k) (false < n = fst * n)) in n (let k h q = true in (n, 9)) < (let l = let rec l n k = let f n = [] in n in (n, false) in if n then let l g = 5 in l else let q = l in [])',
    'fun p -> (let h = let n f = let rec p l = 2 in [] in snd p in fun n h -> fun h l -> h) ((fun x -> (hd, [])) < 6 (fun y -> p))',
    'let g l = if (fun f h -> f) then fun f -> fst f (f, 5) else (let k k q = fun y -> true in let rec k p = l in null) :: (let rec k h h = true [] in hd) in let x x = if g (if g then hd else x) then 0 else 5 in (let rec y f f = false y in let rec h n l = hd in 8) :: (let n l = g in ([], tl))',
    '((fun h g -> if (h, []) then h else let g x p = true in snd) < (fun h f -> (let rec g h = h in h, []))) - ([] < (let h f = let rec h g l = tl in if [] then fst else 8 in let y l q = h - q in y))',
    'let x q n = let rec f q = (fun h l -> fun g q -> true, f) in ((if fst then f else []) = fst + 5) - (if tl * true then (f, n) else if [] then n else n) in x',
    'if tl (fun n -> let rec g q = let g g g = [] in 8 in let g f g = g in g) then let l q = let p = (let rec x l g = [] in 4) = q hd in q in (let g = (false, l) in let p h = l in g) = (fun g f -> let x l h = l in []) else ((null, let g q h = h false in g - 8), (snd hd, 7 * null) (let rec p q = hd in p, fun y f -> false))',
    'null (fst)',
    '((fun h -> ([] :: h) 3) < fst) - (tl null (true false) (fun y -> let h x = y in []) - (if (fun h -> h) then (if hd then tl else null) - (fun g f -> g) else ((fst, snd)) snd))',
    'snd',
    '((fun p -> fun k f -> fst) (let p x x = let g f = x in x in if p then fst else p) hd) * ((let x h = 4 in true) + snd * null < ([] :: null) - (false :: snd)) (tl (let f = fst * (true) in fun k -> f))',
    'fst (fun l -> fun h l -> let k q k = false in fst) (let l = let p l k = if false :: k then 4 else [] null in 0 in if [] then 8 else let rec k k x = let q p = k in x in if l then [] else 5)',
    '(let l = (fun k g -> 3 * true) :: (let p q h = let rec n x = snd in hd in tl) in let f y = (snd = l) - (l - []) in fun g -> [] null) (fun n -> if (let n f = snd + tl in fun g -> []) then (n, n) - (let p f = f in p) else (let rec n x p = n in 8) (let k h y = [] in n))',
    'fst',
    '(let rec x x = [] in [] 8) (if (let rec l k = null in l - l) then snd else snd) = (let h p y = (fun f -> y false) y in fun f h -> let n k l = f l in h)',
    '((fun k k -> (fun l x -> k) (fun h y -> h)) * (fun k -> (k, k 3)), ((if null then [] else []) = (let x k = k in x)) (let y p n = (6, 5) in fun g -> 5) = null)',
    'fun q -> let g = snd - (([], if q then [] else q)) in ([]) g 9 + q',
    '(true, fun f -> f (true fst)) (if (tl snd, let rec p x y = x in 0) (3 snd (fun x g -> [])) then 3 else let rec f n x = if f then let n f = [] in [] else hd fst in ((4, f)) + (false) * f)',
    'let f k f = k in (fun f y -> fun l l -> tl + f) ((let g = tl in 9, fun p n -> true) 1)',
    '((fun f q -> fst) < fst) (null fst + (let f l = l in f)) < (tl :: (if [] then hd else [])) (fun y -> fst, hd) = (if (let l = true in ((hd, l), true)) then ((fun g p -> hd) (let p = 9 in p), (fst * null) (let rec l q x = [] in l)) else fun y -> y)',
    'snd',
    'let rec h g f = (6 :: null) (let x h n = fun f h -> 7 in if [] - null then true * snd else []) in (fun y -> h) + false * (0 9, h - (fst))',
    'let g = fun f -> (fun f -> f fst) f in fun g f -> fun p -> 2',
    'let x y q = (fun n n -> (let x k = tl in n, let f x x = x in n)) + (fun g -> let q k g = [] in hd) (let f y q = null in [] []) in 7',
    'let l = (let h h y = (true) ([]) in true h) < null * (6 :: snd) < tl in if (let l q = let rec f f = if [] then [] else tl in let f g = g in tl in (let k n = l in true) < (fun l q -> l)) then ((let n x h = x in false) = (l)) (let rec l n = l l in fun h k -> 0) else (let q = null - [] in l) ((let rec x l = x in l) < (let k l = fst in true))',
    'let k y = ((fun g y -> false false) < 7 (false true)) ((let h q = [] y in y) ((if 2 then y else y) :: (if snd then y else y))) in ((9) null :: k) (let rec y k = k in k, if snd then k else k) * (fun p h -> (let h h = p in []) (fun x q -> p))',
    'snd',
    '(let h = (fun k h -> h, fun f -> f (f)) in (fun x -> let k = x in 8, true * h)) (fun l f -> let rec p y k = 9 l (8 5) in (let g l x = [] in g) (false 1))',
    'fun h q -> (h - (fun n -> []) q) ((let rec g p x = 7 in q) + q q, fun n -> let k y = false in q)',
    'hd',
    'let f = let k x f = 8 in (let f q = hd in if false then false else false) = k in fun y f -> let rec n g = fun k -> 2 y in fun f l -> let n h = h in f',
    'if (fun f -> fun k n -> (let rec y g k = tl in y, f)) then if (fun g f -> fun g g -> g) - 0 (fun f p -> f) then (let n = fun y -> tl in let rec f y = [] in f) - tl (if null then [] else fst) else null else fun x -> if (let h x x = x in let y p g = false in snd) then (x 2, x false) else if (let rec l n f = false in x) then x x else 0',
    '(tl + (false [] * tl, [] tl (let rec q k = q in q))) hd',
    '(let rec y y = let rec g k q = if (fun h k -> hd) then (4, y) else let rec q p n = 5 in g in null in y) ([])',
    '(fun k l -> ((let n y = l in l) - l) * (fun k h -> fun l -> tl)) (let rec f k g = true in (((f) :: f) :: tl f) (fun y -> fun g q -> y))',
    '(fun k p -> (fun x -> fun f -> snd, k)) - (let rec x k g = let rec p p = let l = let n y g = g in tl in 6 * x in (6, let q y = [] in []) in ([] x x, (x = x) (3 x)))',
    'let h q = let x n k = q in (fun q -> x = []) (let rec y n p = fun h n -> n in fun y -> []) in fun g -> let y = (let g q l = snd in h) (let rec k p = p in h) in fun g q -> let l h = tl in g',
    'let l x k = let y q = let k y = hd 6 + q [] in let h g = snd in x in if (let x k n = let k = 8 in [] in if [] then 6 else k) then 6 else fun x -> true in fun n -> l (6 null ([], hd))',
    'null (let k = let y = if null then let p = fst in 5 else fst in y in fun f h -> let l q = if f then [] else f in 8 k)',
    '(fun k n -> let rec f l = false snd in null - (f)) (fun q g -> let p = let rec h x l = hd in q in q - g) (fun q -> let q f = [] f (if 0 then f else null) in false)',
    '(let rec p h k = null (p * null, fun g f -> []) in fst - (if false then let p f = f in p else let rec y h = [] in [])) (fun q -> (let k h = h in false) (q + snd) (if q + q then false * true else (true, 2)))',
    'fun f q -> ((fun f -> f true) = 0 6 * fst, ((false + [], f []), (let rec q h = [] in f) (fun f -> false)))',
    '(let rec f y y = y (fun g -> y + y) in f f - (2 = f) - f) ((fun p -> let rec q h = snd in q) (let rec q y g = 6 < q in q 0) (fun q -> fst [] (q q)))',
    'fun q n -> let y q y = let q x = (let k f l = snd in []) [] in 1 in let rec q f k = let g n = fun k n -> false in fun h k -> 2 in let g p y = true [] in let x = 3 in snd',
    '(fun f g -> false) (if (if (fun n g -> n) then if 6 then true else 0 else tl) ((fun x -> x) * null hd) then fun y k -> let rec p f = let rec p h = k in 7 in [] else let rec f k f = fun n -> 8 false in let g = fun x n -> null in g = (f))',
    'if (let y = (let x p = let p g = g in hd in x, let rec k k = k :: fst in false) in if (y :: 8, 1 []) then fun x -> [] else fun k g -> []) then let y h l = if (if 5 - h then if 3 then 1 else [] else let y q = q in l) then l (let rec h g = h in h) else [] tl :: (l, h) in 9 else snd (if (fun y x -> 0, tl null) then let n = fun g f -> g in let k = n in n else (tl - tl) (snd < false))',
    'let x g q = if false then (fun p n -> let f n p = q in n) (fun y -> (snd) + g) else fun f x -> [] in let p x p = fun l -> false 1 = p snd in 8 (p + (true)) + true',
    'fun k -> (let k n f = k in k) * (8 + k) (fun l -> []) = (let rec k q y = let y = (k) + k in q k in ([] = 2) (false []))',
    'let q f = if [] (5, false) (fun f -> tl f) then ((fun h -> f) :: (tl, [])) * (let f x = x * false in if snd then 3 else null) else (let p = f fst in [] 8) - (if f 8 then hd null else []) in (fun l p -> fun l k -> if 8 then hd else q) (fun n -> let y n = n in if 7 then [] else fst)',
    '(if (snd, hd) (let f = false in null) then 6 :: false < (let rec h x h = 3 in tl) else fun h g -> (g, 4)) (let y x f = let rec n f l = let rec y y p = p in 6 in if [] then false else f in fun n -> (snd, y)) true',
    'let h l = fun f k -> tl in let n q = if ([] - h) h then h * 0 :: true else (fun x h -> x) true in (if h then fun q -> h else n snd) :: (fun f -> let x = hd in x)',
    '(let rec q k = (let rec g q = if [] then snd else 5 in g g) (let f = [] fst in 6) in let k n f = (if q then 3 else hd) (let x h = f in n) in (fun y -> 5) = q []) (fun l -> if (let rec h h = 7 h in let rec h x x = l in h) then l else let rec g l q = if false then snd else hd in [])',
    'let y = fun y f -> let rec k q = k in (let p n k = k in null) = (if y then [] else 8) in (fun g -> let h = snd in y) (let k l p = p in fun h -> fst) ((fun n -> 5 :: n) (let x n f = false 6 in 6 hd))',
    'let rec g h g = (let y = fun q -> [] in (fun f -> f) + [] [], let q k h = k in let q h = let q = q in 8 in tl tl) in let n q g = let y f = (let f y k = true in []) (true []) in g in let p f = n * hd = (fun x -> f) in snd',
    'let g = (let q n = (fun g x -> g) ((7) = n) in ((2, q), let h p = q in [])) false in let p k = hd in []',
    '(let f y = [] in f fst f - (f) f (let f p n = [] in f)) tl',
    'fun n y -> (if 9 false = 5 + n then let k g x = y tl in hd 5 else n, fst * (fst, y) (y y))',
    'fst',
    '([] hd) (let g n n = snd in [] 9 (let l = [] in [])) (let y n l = (n * tl - (let rec x h = l in x)) * (fun n k -> k) in let q p = let rec l k = true p in let rec n l = [] in snd in let f q l = [] y in fun l h -> y)',
    'fun x -> if x then let h = fun x -> [] x in (x, h) ([] < 8) else if (if [] then x else false) + (fun q -> []) then let rec y q = 2 [] in hd else (fun g k -> hd) (true [])',
    'fun h -> (fun k p -> let f = true :: 9 in false true) * 3',
    '[]',
    'let n = ([]) (if (fun h -> h) (false, 1) then let p h y = fun h -> [] in fun n g -> hd else tl) in fun f -> n ((fun q -> false) (fun y n -> true))',
    'snd',
    '(let x g g = (g snd * 5) ([] (let g p = p in [])) in [] ((let x = x in 1) (let y n p = [] in null))) = [] (let f k = let rec p y n = fun f x -> hd in k < p in if (fun l f -> l) then if 9 then true else 5 else let h = tl in fst)',
    'fun h -> let h n = [] in h',
    'fun n k -> (let n x k = (fun q g -> k) = k + (k) in 0) tl',
    'fun l f -> let rec p g f = fun l -> fun h -> let rec k h k = 7 in 1 in fun f -> (3, f) null',
    'fun l f -> hd',
    '(let rec g h y = fun n f -> let rec n n l = [] in [] in (false = false) false, (let x y = y y in 3 [], if (fun p q -> p) then [] [] else ([], []))) * 6 ((if [] then snd else tl, false 1) :: (fun y f -> false) (let rec y g q = fst in y))',
    'fun n h -> (let l p n = if false then (n, p) else [] hd in h) (let rec q n = h [] (fun f n -> true) in let x g = if q then [] else [] in if h then q else 6)',
    '(if ((true < hd) - (if fst then true else tl)) (fun l y -> null, if null then snd else hd) then (let rec f y k = k in hd) ([] :: snd) * [] else (fun g -> g) (let rec g x = 9 in g) * (snd 2, 5)) < snd',
    'fun x -> (let x = x [] in false (snd)) - (false < []) (let p = x in x) + (let l f = x f in x tl) (let rec x q = if x then fst else x in let n = null in 6)',
    'let h x g = let x = g in [] in []',
    'if (let f = (if [] then fst else false) = tl tl in fst [] (fst, [])) = (let rec x p x = x x in [] []) ((null, []) = tl) then ([] + fst) (fun l x -> fst) ((let g n f = f in fst) :: []) ([], snd) else let q = (let l f = let f q f = q in f in false) (let p g = let h = 0 in h in 3 tl) in (let x = fun h k -> h in x :: q) (fun k g -> let rec g g n = [] in g)',
    '(let h h h = (let g = h in h) (let rec y x q = y in false) * (fun k g -> let g = [] in h) in ([], h - h = (fun y -> []))) + ((let q l l = let y k = l [] in let q n = null in l in fst 2 (let x = q in [])) (if (let q y h = let f q h = true in f in q) then snd else (null, snd) (fun l q -> l)))',
    'fun q -> []',
    '(let rec x f x = [] in tl) (if fst then [] else []) (let rec n k = fun n l -> hd in 5 = n) true (null (let g h = 8 < (fun l l -> tl) in g))',
    'if (let p y = if y then let rec n y q = let f f g = 1 in [] in let rec x p n = p in x else (fun p -> y) (y < y) in let l g = let q h = let n q = 8 in h in q in fun n x -> if p then l else p) then fun f -> let rec h h = if (let rec g q = tl in g) then [] [] else false < false in fun k y -> f k else (fun x -> let x g = 2 < x in let k = [] in []) (fun p h -> p (fun l -> tl))',
    '4',
    'let rec l l h = (if (let rec h p = [] in h) then let g = l in hd else 3 l) = (let rec n y = let g x k = h in true in (n, n)) = (fun l -> true) (l null l) in (let rec g p = 5 < 1 in (g) * snd) (if [] [] then fun y -> y else let f g p = l in true) ((let p f = let k h = f in [] in false :: []) (let h p h = [] in l, 0))',
    '(let g p p = if fst 6 + p 8 then (null) (fun f -> 8) else p in snd) + (if (let rec f y k = y * f in f f, [] + (let q x p = 8 in false)) then ((if null then fst else tl) ([] = snd), (null fst, fun h -> 2)) else (if snd then snd else null) (fst + []) (fst [] (tl tl)))',
    'let k = ((true, 4) (let h = true in []), []) (8 - (fun y f -> false, fun y l -> l)) in let rec h h = let g x = x in let n = fun l -> 7 in null in k true',
    'fun l n -> ((fun n h -> snd (n)) = (let q k n = let q = [] in hd in (l, 3))) ((let p y = [] in p, if true then l else l) + n)',
    'fun l -> fun q -> (let f = let k p = l in k in 0) (5 - [], fun h g -> 4)',
    'snd',
    '7 (let y g l = 1 in fun p y -> (tl :: null) (y + []))',
    'let l x y = let k = let rec h f h = [] [] - (5, h) in true in ((8 x, x), fun q -> y []) in (if 4 then [] else l * 5) ((fun q y -> hd) (snd, l)) (l = (fun f y -> fun k q -> tl))',
    'fun y -> let l f = let rec x f = [] (fun g l -> 9) in let x = y in fst x in l (hd (let rec q k p = k in fst))',
    '((if (if tl null then [] else if [] then null else []) then tl [] * (let x k = 1 in x) else fst) ((tl + snd) (fun n -> n) :: (fun l y -> snd tl)), (snd null < (fun f -> true), (fun h h -> h) (hd :: tl)) (fun f -> f (true true)))',
    'fun g l -> (fun f -> (if tl then f else 9) < (let g h q = 6 in l)) ((let x g = if g then l else l in l null) - (l - false l))',
    'let h g h = tl in true < (let rec f q = fun y -> f in let k h = 9 in h, h)',
    '(let rec h k = (let rec l y = [] in fun h -> false) * (let h h = k in null) (let rec l n f = null in k) in (let h k l = hd in false) h) ((if hd then let rec x g = fun g -> 3 in fun q -> [] else (true, false) (let l = fst in true)) + (tl = (fun g -> g, fun p n -> 7)))',
    '(if [] then let l = 5 ((tl) :: null) in true else let rec l n x = fun l -> (l, null) in if (let rec n g = 6 in n) then l hd else fun f -> l) < (fun g -> g (let k l = fun p q -> 1 in ([], 2)))',
    'snd',
    '8',
    'fun l f -> fun p -> (fun h y -> f) (null (l)) (2 (fun g x -> []))',
    'if (fun q h -> let y y p = y in (fun g q -> []) ([], y)) then fun y -> (tl fst (if y then y else []), let rec f y h = h 2 in []) else (false 1 (if fst true then let y = null in y else tl), (fst, if [] [] then tl (null) else hd))',
    'fun k -> let rec g x p = (if true :: g then 1 else null :: 8, fun g f -> false []) in (g = ([]) 4) 3',
    'tl',
    '[]',
    'fun f -> if (let rec y k = [] null :: true y in 7) then (fun l n -> n) - ([] - f) = (fun l h -> [] f) else (let q = let rec y g y = f in y in if [] then q else true) ((3, f) (f f))',
    '(let y p n = [] in fun y q -> let k = q + q in false - k) (let k = fun x -> ([], 5) (x []) in fun g l -> fun q f -> 0)',
    '(let l n x = [] in let p n = [] n in p 4) (fun y q -> y) = fst',
    '(if (let rec k l l = l + tl k in (let f h = k in []) k) then (fun h -> let rec l g f = [] in 9) snd else (tl fst, tl) < (let y y = y in fst) (8 3)) (fun g n -> if fst then fun h k -> (tl, []) else let rec g k = let q = [] in k in g - [])',
    'snd fst + fst',
    'null',
    'fun l l -> fun h y -> ((2, h) :: (snd, 4)) + (let y = let p k f = l in h in l)',
    '(let f h y = let rec p p = (p) * 1 :: (fun f y -> 9) in h y (let rec g p y = p in []) in (let rec p y f = f + f in let y q h = 8 in []) (if (fun h q -> h) then let rec h l = 8 in h else let y g p = p in 7)) ([] (false hd true :: ((if tl then tl else null) = fst + fst)))',
    '(let n k = k ([] = k snd) in n) 7',
    '(if (if (fun k -> []) - (fun x f -> x) then (fun q l -> []) < (if [] then hd else 6) else hd < (tl = fst)) then let rec g k = ((hd) + 5, 1 k) in 9 g (fun p -> 3) else ((if [] then [] else snd) (null snd), fun y l -> y)) (let h x = (x x, false) < (if (let rec q n p = p in true) then 5 < 1 else let x p = x in fst) in fun f -> let y k = fun g -> [] in if y then 8 else null)',
    'let y = let k g x = ((x, []), let rec p k = 0 in g) ((true, []) (fun l -> [])) in fun l -> let rec h g = let k k = [] in g in fun q -> q in (y + (y - y)) 6 tl',
    'tl',
    'let h h = fun g x -> false = (fun f p -> fst - fst) in h ((fun y -> fun g q -> tl) :: ((let rec l p f = f in 8) < (let rec f f = true in h)))',
    'true',
    '(let q y g = let x g = let p l q = let k = fst in g in [] < tl in g ([], []) in fun k p -> k (q) ((k) q)) snd',
    '(let l g x = fun f -> (g, tl) * ([] = x) in let y g l = null (1 fst) in (l, y) ([] 2)) * (let rec q f = let l = (q, f) (let l = q in true) in (let rec x n = q in q) * false false in (tl, [] []) snd)',
    'let k p = p in k ((if k then [] else k) (fun g -> k)) (fun l -> fun g -> if snd then false else null)',
    '[]',
    '((let n f = f tl (let n = f in 1) in n) (let y l = l 5 (let k f f = 1 in []) in y), fun l -> (let h l = 6 in []) (hd []) + ((tl :: false) :: tl false))',
    'hd',
    'tl',
    'fun k -> k',
    'let x = (fun y l -> 4) + (tl fst (tl - hd), fun h p -> h null) in let h y n = let rec h g = n in if y :: fst then fun k g -> y else 5 in fun n -> let p x = false true in let rec p q y = false in x',
    '(fun l -> fun p -> l = (if l then [] else p), if (if [] snd + (fun g -> g) then (let rec h l q = false in 6) * ([], []) else fun p -> let rec l l = 1 in l) then fst else fun l -> (if l then 0 else true) (l 8))',
    '(let k y f = let x q = let p = fst in [] [] in (y, true) < (fun q -> y) in (let y = null in y, true (let rec p q l = 2 in 2))) ((hd fst, []) ((tl - hd) (hd, 5)) 0)',
    'let rec n l = n in (let q l g = n in 4 n) (n ([] * n)) (4 8 1 (let y l = (n, false) in 0))',
    'fun f -> []',
    '(let f = tl in fun h -> true, let n h = let rec f y = let h f l = 0 in hd in let rec h l = 0 in 3 in fun y l -> y < null) (let q x h = (let f q = let rec k x p = x in h in 1) null in [])',
    'hd',
    'if (null, fst) (snd tl) (let rec y x l = (x, 0) in y) - (let rec g n n = g n (null * hd) in let rec y l = (0, y) in let f h = h in g) then (let rec g l y = g < 1 = [] * false in let q n = let p q = 6 in snd in q) = hd else []',
    'fun y -> y',
    '(let x f h = f * h in 6 - true) ((let rec p x = fst in p) = hd * tl) fst (2 (let y y p = (null, y) in y) ((fun y f -> f) :: false 7, let f k h = k in f []))',
    '((let h = snd in fun k -> 6 k) = (let x l = (let rec q x = x in l) (if 6 then l else l) in (fun f l -> x) (let g = 7 in x))) (let n y g = let rec q y = [] g (let q y x = hd in 8) in (if true then snd else y) (let h p f = q in 2) in n (n n))',
    '((let rec l y p = (fun k -> p) (let l h = h in hd) in fun f p -> 9) = (fun q q -> hd 8 (fun p h -> h)), (let p f = fun q -> q = f in let p = let rec y x = [] in p in snd) (let rec y p = y in true 8 (y :: 7)))',
    'fun f p -> p',
    '1 - ((true tl :: (let h = fst in [])) [], let x f f = let y = let g x p = fst in f in let h l = l in tl in fun x f -> [])',
    'snd',
    'null',
    'false (let l l f = fun n g -> fun q p -> (p, null) in fun f x -> fun x x -> f + l)',
    'tl',
    '(fun g y -> 6) 4',
    'fst',
    'if fst then (hd null < tl 5) (let h = hd = [] in true) ((if false (hd) then fun h -> h else 9 tl) (if (let h n = n in h) then null - 5 else if 0 then [] else null)) else if false then ((true, hd) - (fst + (null))) ((fst, null) (fun y -> y)) else ((if 3 then false else null) < null fst) - (let rec x n q = n - x in fst)',
    '(tl * hd, if (let rec h f y = let rec k g = if null then false else 2 in k in if (h, h) then (h, h) else 9 h) then let p q = (let rec k g = g in q) :: q hd in 6 else let n n p = (let rec g n = 3 in n) (true 0) in if 4 then true else let rec l p h = tl in l)',
    'if (fun f -> snd (let rec x g = g in fun q n -> f)) then fun l -> fun h -> l else 2',
    'if false then if (fun k -> fun q g -> let k = q in 1) then 2 + hd (fst null) else (fun l y -> y l) (fst snd 2) else fun y -> (let x = (y, y) in x 6) y',
    'true',
    '(if [] then (let rec y g = g in fun q -> true) (fun g -> g) else tl, fun l n -> 1 l < (let x f = fst in 7) = (fun k n -> let x = n in l))',
    'fun y p -> p',
    'fst',
    'fst (tl, (if snd = 5 then (snd, fst) else let rec h h x = [] in h) (if tl then snd = 1 else if hd then snd else tl))',
    'null',
    '(let g = (true, []) (fun x h -> 0) in g) fst ((7 * null, let rec h l = l in h) (([] < tl) :: (let l k = k in null)) [])',
    'let rec l y = let f f = fst in (fun h f -> fun q x -> f, 7 - (let y = f in 7)) in let rec f h l = fun k -> let rec l f = (l, tl) in hd in let rec y q = (fun g l -> g) < null - null in (let x h p = true in y) = true - (false)',
    'fun x -> null',
    '(let rec f n y = (fun h -> 7, (y, []) (y < [])) in if (fun y p -> 5) (f, hd) then (7) 4 (f true) else let g g l = fun q l -> [] in let q = null in f) = (let k x = fun q -> null in if k then 9 else k) ((fun p -> 5) (false - hd)) true',
    'fun f q -> (fun k k -> let h f = null in []) (let h = if true then [] else [] in fun g n -> true) - (let rec p n q = (n + p) (fun p -> p) in q)',
    '((let rec l y y = fun k f -> [] y in snd snd ([] l)) :: (let q f = (false, f) f in let g h = fun n -> 3 in [] 8)) (7 = [] :: (if snd then fst snd else fst))',
    'fun n h -> ((let l = 3 (fst) in l = (tl)) - (let l f = fun q f -> [] in let x = fst in x)) ((fun y q -> let x q f = [] in 7) ((if 4 then 7 else h) (let f k = [] in 1)))',
    'let n g q = let x = (let rec h k g = (3, q) in let h g = q in g) (let rec f f = let p f l = l in 2 in let k p = g in g) in fun g -> 1 in let k y = let p = let n y = (tl, []) in let g k p = 4 in [] in true [] in (let rec y g l = ([], g) in if null then n else 9) ((let rec l n y = n in 6) * (fun y -> true))',
    'if ((let rec q h g = tl in 8) (if true then [] else true) < (hd)) ((fun q n -> let rec h n = q in true) * fst (if null then [] else hd)) then (let rec p l = let x h g = 7 < [] in x in fun x k -> tl + p) * (let rec x p n = 8 in let rec x x = let rec y y l = l in x in x * fst) else if tl = tl then fst else (let rec p y x = fun f n -> true in false * tl) tl',
    'fun h -> ([], [] - 0 - ((h) 3, let rec l k q = k in true))',
    'fst',
    'fun y f -> 6 < snd',
    '(if (if 2 (let h h g = 3 in 3) then fun f p -> let l q = [] in p else (let rec y f p = y in 5) (hd tl)) then fun p g -> let q g = p in fun x -> true else []) (fun k -> (let p y x = if y then [] else [] in (false, fst)) * (let h l = true in if [] then null else 0))',
    'let rec q y = (if (let p n p = n in q) then (q) y (let p = [] in 2) else q [] (let g q p = 7 in 6)) = (let rec l k = fun n l -> (l, n) in (q, y) (true false)) in ((fun x -> x :: [], q), (let rec n l = let l y = q in true in let rec x f f = 0 in q) ([] false, (q, q)))',
    '(if (fun f h -> h) then let q = let x = fst in true in [] else (tl, let x = 3 in [])) (if (let q y n = true in hd) = tl false then snd else (fun n -> n) (null = [])) ((hd) ((let x = fun k -> k in fun h -> h) = (let p n = [] in [] p)))',
    'fun l h -> let q k l = (let rec q x = l < 9 in fun g -> tl) (let y q = l false in snd []) in l',
    '(false * (let rec p h = fun f y -> p in null), null)',
    'tl',
    '(let rec p f l = let rec f x = 2 p in f in let p y g = p p in if hd then null else p, (let y y p = y in y) - false = null) - (let l x = fun h -> fun x -> [] in fun k -> k fst) (if (fun k h -> fun g f -> h) then [] snd (if null then [] else false) else fun p -> hd 7)',
    'let rec n p q = false (fun g -> let f n p = let l = [] in null in g) in let n x = (fst, fun k -> []) in n + 3 + n :: (let l x l = hd n in fun n -> snd)',
    'fun p g -> (if (let rec k q = let k p k = [] in [] in [] []) then let rec f f x = let rec g g h = f in g in if 9 then [] else [] else p, tl :: (let g k l = fun n -> p in let f q f = g in p))',
    '(let y = (fun k -> fun h -> 8, let f h q = h in f) in let l g y = if (fun l h -> y) then fun q -> [] else y in (let rec q q = q in false) (fun f x -> l)) = ((let rec n p = fst in 9) 3 (let p g x = [] x in p), (fun k -> if fst then [] else 1) (if (fun h -> h) then let l = snd in l else tl))',
    '(fun y x -> let p = (6, y) in if tl then y else tl, let rec h x h = let g y = ([], 9) in [] in let f = (h, h) in true) + ((let p x k = false :: 4 in []) + (let k = 9 in []) (let k n l = n in k) = (let rec f n = false in tl) (if null then hd else fst) - (tl))',
    '(fun f l -> (((false, false), f), let rec g l n = fun l -> g in g - snd)) tl',
    'null',
    'let n = let rec h g = (let rec x y = if h then true else x in 3 5) (let p q y = 6 :: h in g 6) in snd in fun g -> let f f q = tl in 3',
    'let p = (snd (let rec q p g = 5 [] in [] q), (let g l p = l in g []) tl) in fun n -> let g = ([] 3, p) in tl p + (if false then n else p)',
    'let x y = (if fst false then tl else if false then true else 4, []) (y y (if hd then 8 else y) (fun q -> y, y y)) in (let k = x in let f = 7 k in fst < true) (fun n p -> let rec k y = n tl in [] false)',
    'let k p = fun g -> (let l = fun k l -> p in p) (let y p y = g true in let h q = 0 in h) in true',
    'fun h l -> tl < (let x = let g = l in h 2 in let l x h = let g l = l in l in let l k = l in 6)',
    '(let k l = fun x g -> 4 * l in k 1 < k - snd) (hd) (false - ([] - (let q x h = x 6 in fun h -> 6)))',
    'let y h = fun q -> let rec k k = false in let n n q = fun p -> snd in n + false in (fun h -> y) ((if 1 then y else []) (fun x g -> 0)) * ((let y = y in y) * ([])) (let rec h q = (h, fst) in h)',
    'if (fun g f -> (tl) (fun k n -> fst)) then [] else true',
    '(fun x -> []) (let rec h q l = l (h, l) in fun k l -> if h then hd else h, (if (if tl then false else null) then let l h = 1 in 1 else [] fst) (fst fst, 9 + tl))',
    'fst',
    '(fun g p -> if (if p then g else p) < 7 0 then (let rec k y = p in 5) * (fun h y -> g) else (fun q k -> 3, ([], p)), let rec g q = [] (q [] - hd) in g)',
    'fun g -> (if g (if g then g else g) then (fun y x -> 7) (let n l k = 6 in n) else g (g + 1)) ((fun y x -> x) hd)',
    '[]',
    '(let p g = fun f -> [] in (fun x g -> g []) fst) - ([])',
    'fun x -> let k k = x in k',
    '((fun g n -> fun k -> 1) null, []) = (let p q = null in let rec p n = (snd, n) in hd) (((snd) - null, snd hd) ((let k q = q in false) (snd true)))',
    'let g = (let x = null in let k k = tl in 4) ((if snd then true else tl) < snd + 4) :: (let l = if null fst then [] hd else fun h k -> k in fun k q -> false) in (g, (fun p -> tl g) (fun p -> g < g))',
    'let rec h f = (fun k h -> [] false (f [])) (fun l -> let rec n g = snd in l) in true',
    '((fun q l -> fun n -> fun p x -> 6) = (if 1 then tl else (if [] then 5 else 4) + false)) (let rec x n = if (let y = n * 5 in x 9) then let p y f = x fst in fun q k -> k else fun x n -> if 6 then fst else 8 in let x f k = let y = 7 in ([], x) in (x - 6, fun x f -> f))',
    'let q = null in let p = let q = fun n x -> q 8 in (q - ([])) + (fun n x -> []) in (fun q f -> q, let n l f = 9 in n) ((fun l -> 4) (fst - (p)))',
    '0',
    'if ((tl :: null) (null (tl)) :: hd - (if snd then fst else hd)) ((fst, hd null) + (let rec l g = l in let p = [] in [])) then false else let l k = (fun f x -> f x) (fun q -> hd) in (let y l = l in fun k p -> []) false',
    'let g y f = if (let l = snd in (y, y), f) then f f (let rec h l f = false in 3) (fun f -> f f) else f in let rec k n k = (if (let f y = 8 in []) then n [] else ([], snd)) ((let n k = 2 in g) (let y = true in y)) in (let n = if false then g else 3 in hd) :: (if true then g else []) k',
    'let rec p h q = fun k -> ((fun l h -> q) :: (fun q -> 7)) + (2 :: (let k h p = false in h)) in let rec y x y = let l l f = (fun g n -> p) - (fun n k -> []) in y = (let k = p in false) in p ((3 < null) ([], p))',
    'fun l -> if (let q n g = [] in l) ((snd, l)) (let h p h = let rec l l = [] in p in h) then fun p q -> fun h -> (p, tl) else let rec h p = if 6 5 then null [] else p p in let k = null h in hd < l',
    'fun l -> (l - (fun l l -> snd :: l)) l',
    '(if (let f = let x n = 1 in 3 in 2 * fst) ((fun n f -> 3) = []) then (fun p n -> fun l -> p, fun q p -> p fst) else (let h n = [] [] in [] hd) (let y h = 2 h in let rec n n = y in n)) ((fun n -> let y = 8 in []) (fun n -> fun x -> true) (let q p = p tl in true, (let n f l = true in n) (if hd then tl else snd)))',
    'let k g n = fun g f -> f (let x = true n in [] + []) in (fun q -> true, fun g -> ([], true)) < (fun q k -> if (if k then 5 else k) then (k, true) else k [])',
    'let k x = let p n = x in let q = if x = 6 then p [] else 6 hd in let f x q = let g y = snd in p in let k k = k in x in []',
    'fun q x -> q (q * (q, x < 1))',
    'fun h l -> ([], (fun p g -> []) l (let f q f = f - f in h))',
    '([] * (tl = 1, null * (null)) ((hd) true (([], snd)))) (let rec k x h = let h = if 5 then fun l -> snd else let k n = snd in x in null in let rec q k = q 9 (q []) in fun l -> 1 = true)',
    '(if snd then let y q = q q (fst + q) in y else let rec n q h = let rec f l l = let rec k f p = hd in l in (q, q) in true) false',
    'let p q = let y = q in let f k h = 4 k (6 fst) in 1 in p',
    'null :: (fun g n -> let n = (fun g -> [], fun x l -> 7) in n)',
    'fun f -> let l y = (let rec n n h = n in 6, if f then f else f) (fun l q -> (q) hd) in let g f = f in fun l p -> (f, p)',
    '7 ((let x q = q in x :: (x)) :: (let q n q = null snd in q q) < (let y p = hd p + (1, true) in (let rec f x y = x in y) (let k h = y in y)))',
    '[]',
    'let p y l = (let rec g y q = let rec q k g = q false in fun f -> q in let x = 4 hd in if l then y else l) (fun y k -> true) in let n n = 0 tl (fun p q -> n) (if [] null then if snd then [] else false else null) in let f q = fun n l -> l in fun y -> fun f -> 4',
    'if fst then let y g x = (let rec p n f = let y k f = 4 in n in 8 :: [], (fun h -> hd) + ([], [])) in 9 (fun g -> []) (let rec x x = y = y in fun l -> 1) else ([] + (fun g h -> tl) (let p h = h in p), let rec x h h = (fun k n -> x) * ([] < []) in (x) x < (let y h = tl in x))',
    'snd',
    'tl',
    'true < null (snd, let x = hd in fun k n -> 5)',
    'let p = fst in (let g = [] 1 in let rec k x h = [] in true) - ((fun p n -> p) - [] null) :: (if p [] * (let rec y f = p in tl) then fun q y -> y hd else p)',
    '7 snd',
    'let y k = fun f -> let k k h = null in fun p -> 4 in y < (fun h -> fun y n -> y) (let n k h = false in 2, (7, y))',
    'let rec f n x = let rec k x x = (fun x p -> let q k x = 0 in []) - (n, let l p k = p in 2) in (let rec h l n = true snd in tl * x) (if x 2 then 7 n else fun y -> k) in 4',
    'false',
]

CASES = [
    case_examples, case_literals_and_pairs, case_operators, case_lists, case_builtins, case_shadowing_builtins,
    case_curried_functions, case_let_polymorphism, case_lambda_bound_is_monomorphic,
    case_no_generalization_of_environment_variables, case_occurs_check, case_let_rec, case_let_rec_polymorphic_after_in,
    case_if, case_type_printing_parentheses, case_type_variable_naming_order, case_more_than_26_type_variables,
    case_name_errors, case_syntax_errors, case_keyword_expressions_need_parentheses, case_syntax_errors_come_first,
    case_names_and_reserved_words, case_whitespace_and_layout, case_random_programs,
    case_performance_deep_parentheses, case_performance_deep_lets, case_performance_many_nested_functions,
    case_performance_long_program,
]
