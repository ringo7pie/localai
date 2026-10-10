"""C4 parse_json の隠しテスト。モデルには見せない（形式は c1/tests.py の説明と同じ）。

json モジュールの使用は、実行の前に静的な走査で見つけて 0 点にする（FORBIDDEN_CALLS。import と json.loads などの呼び出し）。
このテスト自身は、大きな入力を作るために json.dumps を使う（答えのコードの走査には関係しない）。
"""

import json
import random

FORBIDDEN_CALLS = ("json", "json.loads", "json.load", "json.JSONDecoder", "json.decoder", "json.scanner")


def _u(hex_digits: str) -> str:
    """JSON の \\uXXXX エスケープの文字列（バックスラッシュ、u、16 進 4 桁）を作る。"""
    return "\\u" + hex_digits


def _is_int(value) -> bool:
    return type(value) is int


def _is_float(value) -> bool:
    return type(value) is float


def case_literals(sol, t):
    t.eq(sol.parse_json("true"), True)
    t.eq(sol.parse_json("false"), False)
    t.eq(sol.parse_json("null"), None)
    t.eq(sol.parse_json(" \t\r\n null \n"), None)


def case_integers(sol, t):
    for text, expected in (("0", 0), ("7", 7), ("-12", -12), ("123456789012345678901234567890", 123456789012345678901234567890)):
        value = sol.parse_json(text)
        t.eq(value, expected)
        t.eq(_is_int(value), True)


def case_floats_and_types(sol, t):
    for text, expected in (("1.5", 1.5), ("-0.25", -0.25), ("1e2", 100.0), ("1E+2", 100.0), ("2.5e-3", 0.0025),
                           ("-1.5e3", -1500.0), ("1.0", 1.0), ("0.0", 0.0)):
        value = sol.parse_json(text)
        t.eq(value, expected)
        t.eq(_is_float(value), True)
    t.eq(_is_int(sol.parse_json("100")), True)
    t.eq(_is_float(sol.parse_json("1e2")), True)


def case_negative_zero_and_extreme_exponents(sol, t):
    zero = sol.parse_json("-0")
    t.eq(zero, 0)
    t.eq(_is_int(zero), True)
    t.eq(_is_float(sol.parse_json("-0.0")), True)
    t.eq(sol.parse_json("1e400"), float("inf"))
    t.eq(sol.parse_json("-1e400"), float("-inf"))
    t.eq(sol.parse_json("1e-400"), 0.0)
    t.eq(sol.parse_json("0.1"), 0.1)
    t.eq(sol.parse_json("123456789.123456789"), 123456789.123456789)


def case_simple_strings(sol, t):
    t.eq(sol.parse_json('"abc"'), "abc")
    t.eq(sol.parse_json('""'), "")
    t.eq(sol.parse_json('"日本語と絵文字😀"'), "日本語と絵文字😀")
    t.eq(sol.parse_json('"a b' + chr(0x7F) + '"'), "a b" + chr(0x7F))
    t.eq(sol.parse_json('"it\'s"'), "it's")


def case_string_escapes(sol, t):
    t.eq(sol.parse_json(r'"\" \\ \/ \b \f \n \r \t"'), '" \\ / \b \f \n \r \t')
    t.eq(sol.parse_json('"' + _u("0041") + _u("00e9") + _u("3042") + '"'), "A" + chr(0xE9) + chr(0x3042))
    t.eq(sol.parse_json('"' + _u("00E9") + _u("00e9") + _u("ABCD") + _u("abcd") + '"'), chr(0xE9) * 2 + chr(0xABCD) * 2)
    t.eq(sol.parse_json('"' + _u("0000") + '"'), chr(0))
    t.eq(sol.parse_json('"' + _u("0022") + _u("005c") + '"'), '"\\')
    t.eq(sol.parse_json('"' + _u("0041") + "B" + _u("0043") + '"'), "ABC")


def case_surrogate_pairs(sol, t):
    t.eq(sol.parse_json('"' + _u("D83D") + _u("DE00") + '"'), chr(0x1F600))
    t.eq(sol.parse_json('"' + _u("d83d") + _u("de00") + '"'), chr(0x1F600))
    t.eq(sol.parse_json('"' + _u("3042") + _u("D83D") + _u("DE00") + _u("3044") + '"'), chr(0x3042) + chr(0x1F600) + chr(0x3044))
    t.eq(sol.parse_json('"' + _u("D800") + _u("DC00") + '"'), chr(0x10000))
    t.eq(sol.parse_json('"' + _u("DBFF") + _u("DFFF") + '"'), chr(0x10FFFF))
    t.eq(sol.parse_json('["' + _u("D83D") + _u("DE00") + _u("D83D") + _u("DE01") + '"]'), [chr(0x1F600) + chr(0x1F601)])


def case_lone_surrogates_are_errors(sol, t):
    for text in ('"' + _u("D83D") + '"', '"' + _u("DE00") + '"', '"' + _u("D83D") + 'abc"', '"' + _u("D83D") + 'A"',
                 '"' + _u("D83D") + _u("0041") + '"', '"' + _u("D83D") + _u("D83D") + '"', '"' + _u("DE00") + _u("D83D") + '"',
                 '"' + _u("D83D") + '\\n"', '"' + _u("D83D") + '\\' + _u("DE00") + '"', '"' + _u("D83D"), '"' + _u("DBFF") + '"'):
        t.raises(ValueError, sol.parse_json, text)


def case_bad_escapes_and_control_characters(sol, t):
    for text in (r'"\a"', r'"\x41"', r'"\'"', r'"\U0001F600"', '"\\u12"', '"\\u12G4"', '"\\u 123"', '"\\u"', r'"\"',
                 '"\\u00g0"', '"\\U00e9"', '"a\tb"', '"a\nb"', '"\x01"', '"\x1f"', '"abc', '"abc\\', "'abc'"):
        t.raises(ValueError, sol.parse_json, text)


def case_empty_containers(sol, t):
    t.eq(sol.parse_json("[]"), [])
    t.eq(sol.parse_json("{}"), {})
    t.eq(sol.parse_json(" [ ] "), [])
    t.eq(sol.parse_json("{ \n }"), {})
    t.eq(sol.parse_json("[[], {}, [{}], {\"a\": []}]"), [[], {}, [{}], {"a": []}])


def case_nested_document(sol, t):
    text = ' {"a": [1, 2.5, "x\\ny"], "b": {"c": null, "d": true, "e": [false, {"f": -0.5e1}]}, "": 0} '
    t.eq(sol.parse_json(text), {"a": [1, 2.5, "x\ny"], "b": {"c": None, "d": True, "e": [False, {"f": -5.0}]}, "": 0})
    t.eq(sol.parse_json('{"a\\"b": 1, "' + _u("3042") + '": [ ]}'), {'a"b': 1, chr(0x3042): []})


def case_whitespace_rules(sol, t):
    t.eq(sol.parse_json(" \t\r\n[\r\n1 ,\t2\n]\r\n "), [1, 2])
    t.eq(sol.parse_json('{ "a" : 1 , "b" : [ ] }'), {"a": 1, "b": []})
    for text in ("\f[1]", "[1]\f", "\v1", chr(0xA0) + "[1]", chr(0xFEFF) + "[1]", "[1]" + chr(0x2028), "[1" + chr(0xA0) + "]",
                 "[ 1 ," + chr(0x3000) + " 2 ]", chr(0x85) + "1"):
        t.raises(ValueError, sol.parse_json, text)


def case_empty_and_trailing_input(sol, t):
    for text in ("", " ", "\n\t", "[1] x", "{} {}", "1 2", "[1]]", "[[1]", '"a" "b"', "null null", "truefalse",
                 "nulls", "x", "[1] //", "/* */ 1"):
        t.raises(ValueError, sol.parse_json, text)


def case_bad_literals(sol, t):
    for text in ("True", "FALSE", "NULL", "nul", "tru", "fals", "None", "undefined", "NaN", "Infinity", "-Infinity",
                 "[True]", "[nul]", "-true"):
        t.raises(ValueError, sol.parse_json, text)


def case_bad_numbers(sol, t):
    for text in ("01", "-01", "+1", ".5", "1.", "1.e5", "1e", "1e+", "1E", "--1", "0x1F", "1_000", "١", "1.5.2",
                 "0.", "-", "- 1", "1 .5", "[01]", "[1.]", "00"):
        t.raises(ValueError, sol.parse_json, text)


def case_bad_container_syntax(sol, t):
    for text in ("[1,]", "[,1]", "[1,,2]", "[1 2]", "[", "]", "[1", '{"a":1,}', "{,}", '{"a"}', '{"a":}', '{"a" 1}',
                 '{"a":1 "b":2}', "{1:2}", "{a:1}", "{'a':1}", '{"a":1', '{"a":1]', '["a":1]', "[1}", '{"a",1}',
                 '{"a"::1}', "[1,2}", "{}}"):
        t.raises(ValueError, sol.parse_json, text)


def case_duplicate_keys_are_errors(sol, t):
    t.raises(ValueError, sol.parse_json, '{"a":1,"a":2}')
    t.raises(ValueError, sol.parse_json, '{"a":1,"b":2,"a":3}')
    t.raises(ValueError, sol.parse_json, '{"a":1,"' + _u("0061") + '":2}')
    t.raises(ValueError, sol.parse_json, '{"x":{"k":1,"k":1}}')
    t.raises(ValueError, sol.parse_json, '[{"k":1,"k":2}]')
    # 違うオブジェクトの同じキーや、大文字小文字の違うキーは重複ではない
    t.eq(sol.parse_json('{"a":{"a":1},"b":{"a":2}}'), {"a": {"a": 1}, "b": {"a": 2}})
    t.eq(sol.parse_json('{"a":1,"A":2," a":3}'), {"a": 1, "A": 2, " a": 3})


def case_values_adjacent_to_literals(sol, t):
    for text in ("[1true]", "[truefalse]", "[null1]", '["a"1]', "[1\"a\"]", '{"a":1"b":2}'):
        t.raises(ValueError, sol.parse_json, text)
    t.eq(sol.parse_json("[1,true,null,\"a\",-2.5]"), [1, True, None, "a", -2.5])


def case_top_level_scalars_with_whitespace(sol, t):
    t.eq(sol.parse_json(' "abc" '), "abc")
    t.eq(sol.parse_json("\n42\n"), 42)
    t.eq(sol.parse_json(" 3.5 "), 3.5)
    t.eq(sol.parse_json("\t-7\r"), -7)


def case_many_small_values(sol, t):
    text = "[" + ",".join(str(index) for index in range(100_000)) + "]"
    t.eq(sol.parse_json(text), list(range(100_000)))
    text = "{" + ",".join(f'"k{index}":{index}' for index in range(30_000)) + "}"
    t.eq(sol.parse_json(text), {f"k{index}": index for index in range(30_000)})


def case_long_string_with_escapes(sol, t):
    piece = "ab" + "\\n" + _u("00e9") + "\\\\" + '\\"' + _u("D83D") + _u("DE00")
    text = '"' + piece * 20_000 + '"'
    t.eq(sol.parse_json(text), ("ab\n" + chr(0xE9) + '\\"' + chr(0x1F600)) * 20_000)


def case_large_random_document(sol, t):
    rng = random.Random(2026)

    def make(depth):
        kind = rng.randrange(7 if depth < 4 else 5)
        if kind == 0:
            return rng.randrange(-10 ** 6, 10 ** 6)
        if kind == 1:
            return rng.random() * 10 ** rng.randrange(-5, 6)
        if kind == 2:
            return "".join(rng.choice("abc 日本\"\\\n\t😀é") for _ in range(rng.randrange(0, 12)))
        if kind == 3:
            return rng.choice([True, False, None])
        if kind == 4:
            return -rng.randrange(0, 50) / 8
        if kind == 5:
            return [make(depth + 1) for _ in range(rng.randrange(0, 6))]
        return {f"k{index}": make(depth + 1) for index in range(rng.randrange(0, 6))}

    data = [make(0) for _ in range(12_000)]
    text = json.dumps(data, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 1]))
    t.eq(len(text) > 300_000, True)
    t.eq(sol.parse_json(text), data)


def case_deep_nesting(sol, t):
    depth = 50_000
    result = sol.parse_json("[" * depth + "]" * depth)
    node, seen = result, 0
    while isinstance(node, list) and len(node) == 1:
        node = node[0]
        seen += 1
    t.eq(seen, depth - 1)
    t.eq(node, [])
    result = sol.parse_json('{"a":' * depth + "1" + "}" * depth)
    node, seen = result, 0
    while isinstance(node, dict):
        t.eq(list(node.keys()), ["a"])
        node = node["a"]
        seen += 1
    t.eq((seen, node), (depth, 1))
    t.raises(ValueError, sol.parse_json, "[" * depth + "]" * (depth - 1))
    t.raises(ValueError, sol.parse_json, "[" * depth + "]" * (depth + 1))


CASES = [
    case_literals, case_integers, case_floats_and_types, case_negative_zero_and_extreme_exponents,
    case_simple_strings, case_string_escapes, case_surrogate_pairs, case_lone_surrogates_are_errors,
    case_bad_escapes_and_control_characters, case_empty_containers, case_nested_document, case_whitespace_rules,
    case_empty_and_trailing_input, case_bad_literals, case_bad_numbers, case_bad_container_syntax,
    case_duplicate_keys_are_errors, case_values_adjacent_to_literals, case_top_level_scalars_with_whitespace,
    case_many_small_values, case_long_string_with_escapes, case_large_random_document, case_deep_nesting,
]
