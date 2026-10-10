#!/usr/bin/env python3
"""PixelArtistry のワークフロー 4 本を、ComfyUI の利用者ワークフローへ写す（setup-server.sh の [11/12]）。

配布元 bat の [6/8] の置き換え。写すときに変えるのは Blender のパスのノード（PrimitiveString、
既定値 "blender"）の値だけで、/snap/blender/current/blender にする（/usr/bin/blender は apt の 4.0.2 なので
使わない。/snap/bin/blender は snap run が comfyui の cgroup の外へ子を移すので使わない）。
それ以外は変えない。書式は配布元と同じ indent=2・末尾改行なしで、ensure_ascii=False で書く。

--fallback を付けると、予備案の写しも書く（WTiVo を外し、直後の LODTailor の Voxel Remesh を
relative_voxel_size=1/1536 で使う）。WTiVo を含まない 03 は予備案を作らない。

既に置いてあるファイルが、これから書く内容と違うときは上書きしない（UI で手直しして保存したものを
守るため）。--force で上書きする。ただし、以前の既定の Blender のパス（config.LEGACY_BLENDER_PATHS）で
書いたままの内容と一致するファイルは、手直しされていないので今の既定値へ書き換える。
標準ライブラリだけで動く。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

# scripts/ の 1 つ上（tools/comfyui）を import 先に足す。cfui を editable で入れていない python でも動くように。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cfui import config  # noqa: E402
from cfui.workflows import (  # noqa: E402
    FALLBACK_RELATIVE_VOXEL_SIZE,
    WorkflowFormatError,
    dump_workflow,
    has_wtivo,
    make_fallback,
    set_blender_path,
)

FALLBACK_SUFFIX = "_noWTiVo"


def fallback_name(file_name: str) -> str:
    stem, dot, extension = file_name.rpartition(".")
    if not dot:
        return file_name + FALLBACK_SUFFIX
    return f"{stem}{FALLBACK_SUFFIX}.{extension}"


def write_if_safe(path: Path, text: str, force: bool, replaceable: Sequence[str] = ()) -> str:
    """書いた / 以前の既定値のまま書き換えた / 同じなので触らない / 違うので触らない、のどれかを返す。

    replaceable は「手直しされていない古い写し」の内容。既存の内容がこのどれかと一致するなら上書きしてよい。
    """

    status = "written"
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == text:
            return "unchanged"
        if current in replaceable:
            status = "migrated"
        elif not force:
            return "kept"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return status


_STATUS_LABELS = {
    "written": "書きました",
    "migrated": "以前の既定の Blender のパスのままだったので、今の既定値に書き換えました",
    "unchanged": "同じ内容なので触りません",
    "kept": "内容が違うので上書きしません（UI で手直しした可能性。--force で上書き）",
}


def adapt_all(
    source_dir: Path,
    dest_dir: Path,
    fallback_dir: Path | None,
    blender_path: str,
    relative_voxel_size: float,
    force: bool,
    file_names: tuple[str, ...] = config.WORKFLOW_FILES,
    legacy_blender_paths: Sequence[str] = config.LEGACY_BLENDER_PATHS,
) -> list[tuple[Path, str]]:
    """file_names を source_dir から読み、dest_dir（と fallback_dir）へ書く。結果の一覧を返す。

    legacy_blender_paths は以前の既定の Blender のパス。そのパスで書いたままの写しは、手直しされて
    いないものとして blender_path の内容に書き換える。
    """

    results = []
    for file_name in file_names:
        source_path = source_dir / file_name
        workflow = json.loads(source_path.read_text(encoding="utf-8"))
        adapted = set_blender_path(workflow, blender_path)
        legacy = [
            set_blender_path(workflow, legacy_path)
            for legacy_path in legacy_blender_paths
            if legacy_path != blender_path
        ]
        dest_path = dest_dir / file_name
        results.append(
            (
                dest_path,
                write_if_safe(dest_path, dump_workflow(adapted), force, [dump_workflow(item) for item in legacy]),
            )
        )

        if fallback_dir is not None and has_wtivo(adapted):
            fallback = make_fallback(adapted, relative_voxel_size)
            fallback_path = fallback_dir / fallback_name(file_name)
            legacy_fallbacks = [dump_workflow(make_fallback(item, relative_voxel_size)) for item in legacy]
            results.append(
                (fallback_path, write_if_safe(fallback_path, dump_workflow(fallback), force, legacy_fallbacks))
            )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PixelArtistry のワークフローを ComfyUI へ写す")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=config.PIXELARTISTRY_DIR / "workflows",
        help="配布元のワークフローの場所（既定: vendor/PixelArtistry-Watertight-Meshes/workflows）",
    )
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=config.WORKFLOWS_DIR,
        help="書き出し先（既定: vendor/ComfyUI/user/default/workflows/PixelArtistry）",
    )
    parser.add_argument("--blender-path", default=config.BLENDER_PATH, help="Blender の実行ファイル")
    parser.add_argument(
        "--fallback", action="store_true", help="予備案（WTiVo を外したもの）の写しも書く"
    )
    parser.add_argument(
        "--fallback-dir",
        type=Path,
        default=config.FALLBACK_WORKFLOWS_DIR,
        help="予備案の書き出し先（既定: vendor/ComfyUI/user/default/workflows/PixelArtistry_noWTiVo）",
    )
    parser.add_argument(
        "--fallback-voxel-size",
        type=float,
        default=FALLBACK_RELATIVE_VOXEL_SIZE,
        help="予備案の LODTailor の relative_voxel_size（既定: 1/1536）",
    )
    parser.add_argument("--force", action="store_true", help="内容が違っても上書きする")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        results = adapt_all(
            source_dir=args.source_dir,
            dest_dir=args.dest_dir,
            fallback_dir=args.fallback_dir if args.fallback else None,
            blender_path=args.blender_path,
            relative_voxel_size=args.fallback_voxel_size,
            force=args.force,
        )
    except (OSError, json.JSONDecodeError, WorkflowFormatError) as exc:
        print(f"ワークフローを写せませんでした: {exc}", file=sys.stderr)
        return 1
    for path, status in results:
        print(f"  {path.name}: {_STATUS_LABELS[status]}（{path.parent}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
