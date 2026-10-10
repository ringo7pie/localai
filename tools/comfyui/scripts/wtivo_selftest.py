#!/usr/bin/env python3
"""WTiVo の自己試験。配布元 bat の L457-484（#WTIVO_SELFTEST#）と同じ条件で、穴をあけた球を防水化する。

venv の python で実行する（run-comfyui doctor が呼ぶ）。引数はノードのフォルダ
（vendor/ComfyUI/custom_nodes/WTiVo-WatertightVoxel-ComfyuiNode）。
icosphere(subdivisions=4, radius=0.5) の faces[60:]（先頭 60 面を消して穴にする）を
process_arrays(..., input_res=256, final_res=256, proxy_points=200_000, threads=4) に渡す。
watertight が真かつ出力の面数 > 0 なら合格（bat と同じ判定）。

標準出力の最後の 1 行に結果の JSON を出す。終了コードは 0=合格、1=不合格、2=読み込めない。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import time

LOG_TAIL_LINES = 15


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "使い方: wtivo_selftest.py <WTiVo ノードのフォルダ>"}, ensure_ascii=False))
        return 2
    node_dir = sys.argv[1]
    sys.path.insert(0, node_dir)
    try:
        import numpy as np
        import trimesh
        from inprocess import process_arrays
    except Exception as exc:  # noqa: BLE001  読み込めない理由は何であれ JSON で doctor に返す
        print(json.dumps({"error": f"WTiVo を読み込めません: {exc!r}"}, ensure_ascii=False))
        return 2

    sphere = trimesh.creation.icosphere(subdivisions=4, radius=0.5)
    vertices = np.asarray(sphere.vertices, dtype=np.float64)
    # 先頭 60 面を消して穴にする（bat と同じ）。
    faces = np.asarray(sphere.faces[60:], dtype=np.int32)

    log = io.StringIO()
    started = time.time()
    try:
        # process_arrays は wtivo.py を子プロセスで走らせ、その出力を print する。
        # 合否には要らないので捕まえておき、失敗したときだけ末尾を返す。
        with contextlib.redirect_stdout(log):
            _vertices_out, faces_out, watertight, bad_edges, _total = process_arrays(
                vertices,
                faces,
                input_res=256,
                final_res=256,
                proxy_points=200_000,
                threads=4,
            )
    except Exception as exc:  # noqa: BLE001  子プロセスの失敗は RuntimeError だが、何であれ結果として返す
        result = {
            "error": f"{type(exc).__name__}: {exc}",
            "log_tail": log.getvalue().splitlines()[-LOG_TAIL_LINES:],
        }
        print(json.dumps(result, ensure_ascii=False))
        return 1

    result = {
        "faces_in": len(faces),
        "faces_out": len(faces_out),
        "watertight": bool(watertight),
        "bad_edge_groups": int(bad_edges),
        "seconds": time.time() - started,
    }
    backend_lines = [line for line in log.getvalue().splitlines() if "native backend" in line]
    if backend_lines:
        result["backend"] = backend_lines[-1].strip()
    if not watertight:
        result["log_tail"] = log.getvalue().splitlines()[-LOG_TAIL_LINES:]
    print(json.dumps(result, ensure_ascii=False))
    return 0 if watertight and len(faces_out) else 1


if __name__ == "__main__":
    raise SystemExit(main())
