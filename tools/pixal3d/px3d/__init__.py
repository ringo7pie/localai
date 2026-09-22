"""Pixal3D をこの A30 サーバーで動かすための道具一式。

標準ライブラリのみに依存する。torch や gradio など重い依存は .venv 側にのみ入れ、
このパッケージ自体は素の python からも import できるようにしてある
（hy3d と同じ設計方針。tools/hunyuan3d/hy3d/__init__.py を参照）。
"""

from __future__ import annotations

__all__ = ["config", "ollama", "options", "cli", "rembg_override"]
