"""作成時の検算（numpy が要る。uvx --with numpy python suites/math/verify_numeric.py）。

各問の reference.answers() の値を、numpy の大きなモンテカルロ（標本 3,000 万〜6,000 万）で確かめる。
結果（推定値・標準誤差・相対差）を表で出す。answer.json の verified に写す。
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def load(item):
    spec = importlib.util.spec_from_file_location(item, HERE / item / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seg_dist(p, a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    ab = b - a
    t = np.clip(((p - a) @ ab) / (ab @ ab), 0.0, 1.0)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def tetra_dist(p, verts):
    verts = [np.asarray(v, float) for v in verts]
    best = np.min([np.linalg.norm(p - v, axis=1) for v in verts], axis=0)
    for i in range(4):
        for j in range(i + 1, 4):
            best = np.minimum(best, seg_dist(p, verts[i], verts[j]))
    inside = np.ones(len(p), bool)
    for skip in range(4):
        a, b, c = [verts[k] for k in range(4) if k != skip]
        n = np.cross(b - a, c - a)
        n = n / np.linalg.norm(n)
        if (verts[skip] - a) @ n > 0:
            n = -n
        signed = (p - a) @ n
        inside &= signed <= 0
        proj = p - signed[:, None] * n
        # 射影が三角形の中にあるか（重心座標）
        v0, v1, v2 = b - a, c - a, proj - a
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        v = (d11 * d20 - d01 * d21) / den
        w = (d00 * d21 - d01 * d20) / den
        inside_tri = (v >= 0) & (w >= 0) & (v + w <= 1)
        best = np.where(inside_tri, np.minimum(best, np.abs(signed)), best)
    return np.where(inside, 0.0, best)


def mc(fn, lo, hi, total, chunk=2_000_000, seed=0):
    rng = np.random.default_rng(seed)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    box = float(np.prod(hi - lo))
    acc = None
    n = 0
    while n < total:
        p = lo + (hi - lo) * rng.random((chunk, 3))
        part = fn(p)
        acc = part if acc is None else {k: acc[k] + part[k] for k in acc}
        n += chunk
    return acc, n, box


def main():
    out = {}
    m1 = load("m1")
    r, band = m1.R, 0.004
    lo = [min(v[k] for v in m1.VERTS) - r - band for k in range(3)]
    hi = [max(v[k] for v in m1.VERTS) + r + band for k in range(3)]

    def f1(p):
        d = tetra_dist(p, m1.VERTS)
        return {"in": float(np.sum(d <= r)), "shell": float(np.sum((d > r - band) & (d <= r + band)))}

    acc, n, box = mc(f1, lo, hi, 40_000_000, seed=1)
    vol = box * acc["in"] / n
    area = box * acc["shell"] / n / (2 * band)
    out["m1"] = {"a": (vol, box * math.sqrt(acc["in"]) / n), "b": (area, box * math.sqrt(acc["shell"]) / n / (2 * band))}

    m2 = load("m2")
    r = m2.R

    def f2(p):
        keep = (seg_dist(p, (0, 0, 0), (1, 0, 0)) <= r) & (seg_dist(p, (1, 0, 0), (1, 1, 0)) > r)
        return {"n": float(keep.sum()), "sx": float(p[keep, 0].sum()), "sy": float(p[keep, 1].sum()),
                "sxx": float((p[keep, 0] ** 2).sum()), "syy": float((p[keep, 1] ** 2).sum())}

    acc, n, box = mc(f2, (-r, -r, -r), (1 + r, r, r), 40_000_000, seed=2)
    cnt = acc["n"]
    mean_x, mean_y = acc["sx"] / cnt, acc["sy"] / cnt
    sd_x = math.sqrt(acc["sxx"] / cnt - mean_x ** 2) / math.sqrt(cnt)
    sd_y = math.sqrt(acc["syy"] / cnt - mean_y ** 2) / math.sqrt(cnt)
    out["m2"] = {"a": (box * cnt / n, box * math.sqrt(cnt) / n), "b": (mean_x, sd_x), "c": (mean_y, sd_y)}

    rng = np.random.default_rng(3)
    res = {}
    for key, d in (("a", 0.25), ("b", 0.1), ("c", 0.15)):
        hits = total = 0
        for _ in range(30):
            p = rng.random((2_000_000, 3))
            outside = ((p - 0.5) ** 2).sum(axis=1) > 0.25
            near = np.minimum(p, 1 - p).min(axis=1) <= d
            hits += int((outside & near).sum())
            total += len(p)
        prob = hits / total
        res[key] = (prob, math.sqrt(prob * (1 - prob) / total))
    out["m3"] = res

    report = {}
    for item, parts in out.items():
        ref = load(item).answers()
        report[item] = {}
        for key, (est, se) in parts.items():
            report[item][key] = {"reference": ref[key], "monte_carlo": est, "std_error": se,
                                 "z": (est - ref[key]) / se if se else None,
                                 "rel_diff": abs(est - ref[key]) / abs(ref[key])}
            print(f"{item}({key}) ref {ref[key]:.7f}  MC {est:.7f} ± {se:.1e}  z {report[item][key]['z']:+.2f}", flush=True)
    json.dump(report, sys.stdout if "--json" in sys.argv else open(HERE / "verify_numeric.json", "w"), indent=1)


if __name__ == "__main__":
    main()
