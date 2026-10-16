#!/usr/bin/env python3
"""GGUF の qwen4exp.attention.compress_ratios を、full_attention_interval と整合する値に直す（または元に戻す）。

Strata v0.1.44.1 の engine は起動時に GGUF のメタデータから形状を読み、compress_ratios が
「full attention の層（(層番号 + 1) が full_attention_interval で割り切れる層）だけ 0 でない」ことを検査する
（vendor/Strata/include/strata/artifact/gguf_reader.hpp の read_geometry）。RVN の汎用版 GGUF は 48 個すべてが 0 で、
この検査に落ちる（"compress_ratios[3] = 0, but full_attention_interval = 4 makes layer 3 full attention"）。
上流の Coder・公式版の GGUF は第 3, 7, ..., 47 番目（0 始まり）だけ 4 になっている。

このスクリプトは配列の 4 バイト要素だけを、その場で書き換える（ファイルの大きさは変わらない）。
  引数なし     : 現状を表示するだけ（何も書かない）
  --apply      : 全部 0 のときだけ、full attention の層の要素を 4 にする
  --revert     : 直した状態（期待どおりの配列）のときだけ、全部 0 に戻す
書く前に、ファイルの生のバイトが読み取った値と一致することと、書いた後にメタデータ領域で変わったバイトが
対象の要素だけであることを確かめる。HF に固定した sha256 とは一致しなくなる（fetch-models --verify が失敗する）。
"""
import argparse
import struct
import sys
from pathlib import Path

STRATA_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STRATA_DIR / "vendor" / "Strata" / "third_party" / "llama.cpp" / "gguf-py"))

from gguf import GGUFReader, GGUFValueType  # noqa: E402

KEY_PREFIX = "qwen4exp."
COMPRESS_RATIO_FULL_ATTENTION = 4
ELEMENT_BYTES = 4


def read_scalar(reader, key):
    field = reader.fields.get(key)
    if field is None:
        raise SystemExit(f"{key} がありません")
    return int(field.parts[field.data[0]][0])


def locate_elements(reader):
    """compress_ratios の各要素の (ファイル内オフセット, 値) を返す。"""
    key = KEY_PREFIX + "attention.compress_ratios"
    field = reader.fields.get(key)
    if field is None:
        raise SystemExit(f"{key} がありません")
    if field.types != [GGUFValueType.ARRAY, GGUFValueType.INT32]:
        raise SystemExit(f"{key} の型が int32 の配列ではありません: {field.types}")
    data_indexes = set(field.data)
    elements = []
    position = field.offset
    for index, part in enumerate(field.parts):
        if index in data_indexes:
            elements.append((position, int(part[0])))
        position += part.nbytes
    return elements


def expected_values(layer_count, interval):
    return [COMPRESS_RATIO_FULL_ATTENTION if (layer + 1) % interval == 0 else 0 for layer in range(layer_count)]


def verify_raw(path, elements):
    with open(path, "rb") as handle:
        for offset, value in elements:
            handle.seek(offset)
            raw = struct.unpack("<i", handle.read(ELEMENT_BYTES))[0]
            if raw != value:
                raise SystemExit(f"オフセット {offset} の生の値 {raw} が読み取った値 {value} と違います。何も書きません")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gguf", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--revert", action="store_true")
    args = parser.parse_args()

    reader = GGUFReader(str(args.gguf), "r")
    layer_count = read_scalar(reader, KEY_PREFIX + "block_count")
    interval = read_scalar(reader, KEY_PREFIX + "full_attention_interval")
    elements = locate_elements(reader)
    metadata_end = reader.data_offset
    del reader
    if len(elements) != layer_count:
        raise SystemExit(f"compress_ratios の要素数 {len(elements)} が block_count {layer_count} と違います")
    verify_raw(args.gguf, elements)

    current = [value for _, value in elements]
    fixed = expected_values(layer_count, interval)
    zeros = [0] * layer_count
    if current == zeros:
        state = "broken"
    elif current == fixed:
        state = "fixed"
    else:
        state = "other"
    print(f"{args.gguf.name}: block_count={layer_count} full_attention_interval={interval} 状態={state}")
    print(f"  現在: {current}")

    if not (args.apply or args.revert):
        return 0
    if args.apply and state != "broken":
        raise SystemExit(f"--apply は全部 0 のときだけ使えます（状態={state}）。何も書きません")
    if args.revert and state != "fixed":
        raise SystemExit(f"--revert は期待どおりの配列のときだけ使えます（状態={state}）。何も書きません")

    target = fixed if args.apply else zeros
    changes = [(offset, old, new) for (offset, old), new in zip(elements, target) if old != new]
    with open(args.gguf, "rb") as handle:
        before = handle.read(metadata_end)
    with open(args.gguf, "r+b") as handle:
        for offset, old, new in changes:
            handle.seek(offset)
            handle.write(struct.pack("<i", new))
        handle.flush()
    with open(args.gguf, "rb") as handle:
        after = handle.read(metadata_end)

    changed_bytes = {index for index in range(metadata_end) if before[index] != after[index]}
    allowed_bytes = {offset + delta for offset, _, _ in changes for delta in range(ELEMENT_BYTES)}
    if not changed_bytes <= allowed_bytes:
        raise SystemExit("対象の要素以外のバイトが変わっています。確認してください")
    verify = GGUFReader(str(args.gguf), "r")
    result = [value for _, value in locate_elements(verify)]
    if result != target:
        raise SystemExit(f"書いた後の値が期待と違います: {result}")
    for offset, old, new in changes:
        print(f"  offset {offset}: {old} -> {new}")
    print(f"  書き換えた要素: {len(changes)} 個、変わったバイト: {len(changed_bytes)}")
    print(f"  結果: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
