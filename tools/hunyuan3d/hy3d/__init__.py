"""Hunyuan3D-2 をこの A30 サーバーで動かすための道具一式。

標準ライブラリのみに依存する。torch など重い依存は .venv 側にのみ入れ、
このパッケージ自体は素の python からも import できるようにしてある。
"""

from __future__ import annotations

__all__ = ["config", "ollama", "cli"]
