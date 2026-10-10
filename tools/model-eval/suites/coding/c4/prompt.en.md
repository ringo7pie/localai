## Problem C4: Strict JSON parser

Write a function `parse_json(text: str) -> object`. Following the grammar of RFC 8259 strictly, read `text` as a single JSON value and convert it to a Python value. Do not use the standard library's `json` module (such as `json.loads` or `json.JSONDecoder`); an answer that uses it scores 0.

### Grammar

- The whole of `text` must be "whitespace (zero or more), one value, whitespace (zero or more)". Anything else (an empty string, only whitespace, extra characters before or after the value, two values) is a `ValueError`.
- Whitespace is only these 4 kinds: the ASCII space, `\t`, `\n`, and `\r`. `\f`, `\v`, the no-break space, and a leading BOM (U+FEFF) are not whitespace and are a `ValueError`.
- A value is one of: an object, an array, a string, a number, `true`, `false`, or `null`. The top-level value need not be an object or an array (`"abc"` or `42` alone is also valid).
- The literals are only lowercase `true`, `false`, and `null`. `True`, `NULL`, and `nul` are a `ValueError`. `NaN`, `Infinity`, and `-Infinity` are also a `ValueError`.
- An object `{ ... }` becomes a Python `dict`. Keys must always be strings. Members are separated by `,`; a trailing extra `,` (`{"a":1,}`) or an empty member (`{,}`) is a `ValueError`. **If the same key appears twice, it is a `ValueError`** (keys are the same if they are the same string after escapes are decoded; `{"a":1,"\u0061":2}` is a `ValueError`).
- An array `[ ... ]` becomes a Python `list`. A trailing extra `,` or an empty element (`[1,,2]`, `[,1]`) is a `ValueError`.
- A string is enclosed in `"` (`'` is not allowed). The only escapes allowed inside are `\"` `\\` `\/` `\b` `\f` `\n` `\r` `\t` and `\uXXXX` (4 hexadecimal digits; upper case and lower case are both accepted). Any other escape (`\a`, `\x41`, `\'`, `\U0001F600`, `\u12` with too few digits) is a `ValueError`.
  - An unescaped control character (U+0000 to U+001F) inside a string is a `ValueError`. Characters from U+007F onward (such as Japanese text or emoji) may be written as they are.
  - When a high surrogate (U+D800 to U+DBFF) is immediately followed by a `\u` escape of a low surrogate (U+DC00 to U+DFFF), as in `\uD83D\uDE00`, combine them into a single character (U+1F600 in this example). A low surrogate on its own, or a high surrogate that is not immediately followed by a low-surrogate escape, is a `ValueError`. `\u0000` is allowed (the length-1 string `"\x00"`).
- A number must have exactly the form `-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?`. A leading `0` followed by digits (`01`), `+1`, `.5`, `1.`, `1e`, `0x10`, and `1_000` are a `ValueError`. If there is a fractional part or an exponent part, the value is the same as Python's `float(that string)` (`1e400` is `inf`); if there is neither, it is an `int` (there is no limit on the number of digits, and the value is exact; `-0` is the `int` `0`).
- The nesting depth is at most 50,000 (even a deeply nested input such as `[[[[...]]]]` must return the correct value). The length of `text` is at most 1,000,000 characters, and the code must run fast enough even at that length (for example, an implementation that slices the string at every step (`text = text[1:]`) will not be fast enough).

Examples:
- `parse_json(' {"a": [1, 2.5, "x\\ny"], "b": {"c": null, "d": true}} ')` → `{"a": [1, 2.5, "x\ny"], "b": {"c": None, "d": True}}`
- `parse_json('"\\u3042\\uD83D\\uDE00"')` → `"あ😀"`
- `parse_json('[1, 2,]')` → raises `ValueError`
