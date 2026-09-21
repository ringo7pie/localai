"""連携層が投げる例外。CLI と MCP で同じものを使う。"""


class BridgeError(Exception):
    """利用者の操作ミスや設定の誤りで、そのままメッセージを見せてよいもの。"""


class ConfigError(BridgeError):
    """設定ファイルが読めない・不足している・値が不正。"""


class NotFoundError(BridgeError):
    """task_id や workspace_id が登録簿に無い。"""


class DuplicateRequestError(BridgeError):
    """同じ request_id が既に受け付け済み。"""

    def __init__(self, message: str, task_id: str) -> None:
        super().__init__(message)
        self.task_id = task_id


class DirtyWorkspaceError(BridgeError):
    """元の作業ツリーに未コミット変更があり、勝手に触れない。"""
