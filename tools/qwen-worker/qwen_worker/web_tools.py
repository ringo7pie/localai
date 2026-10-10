"""Qwen にインターネット検索とページ取得をさせるツール。

ローカルの知識だけでは古い・足りないとき用。検索は ddgs（DuckDuckGo。API キー不要）、
ページ取得は標準ライブラリの urllib.request で行う。

Qwen が渡す URL・検索語は信用しない。この機体では Ollama（11434）・Open WebUI（8080）・
入口ページ（8080）などが動いており、内部アドレスへの到達は必ず防ぐ。
判定は ipaddress モジュールに任せ、自前の正規表現でアドレス種別を判定しない。
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_USER_AGENT = "qwen-worker/1 (local research tool; A30 this-host)"
_CONNECT_TIMEOUT_SEC = 10.0
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 3
_READ_CHUNK_BYTES = 65536


def is_blocked_address(ip_text: str) -> bool:
    """IP アドレス文字列が内部・特殊用途で、モデルに触らせてはいけないものか。

    プライベート（10/8, 172.16/12, 192.168/16）、ループバック（127/8, ::1）、
    リンクローカル（169.254/16。クラウドのメタデータ 169.254.169.254 を含む）、
    その他の予約・特殊用途アドレスを拒否する。解析できない文字列も安全側で拒否する。
    """
    try:
        addr = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def validate_url(url: str) -> str | None:
    """url を取得してよいか検査する。拒否理由（日本語）を返す。問題なければ None。

    ホスト名は実際に解決し、得られた IP のどれか 1 つでも内部・特殊用途なら拒否する
    （DNS リバインディングで外部ドメインが内部 IP を指すケースへの対策）。
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return f"URL を解析できません: {exc}"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return f"許可されていないスキームです: {parsed.scheme or '(なし)'!r}。http と https だけ許可します。"

    host = parsed.hostname
    if not host:
        return "URL にホスト名がありません"

    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError) as exc:
        return f"ホスト名を解決できません: {host}（{exc}）"
    if not infos:
        return f"ホスト名の解決結果が空です: {host}"

    for info in infos:
        ip_text = info[4][0]
        if is_blocked_address(ip_text):
            return f"内部・特殊用途アドレスへのアクセスは拒否します: {host} -> {ip_text}"
    return None


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    """リダイレクトを自動追跡しない。1 段ずつ validate_url で検査してから追うため。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401, ANN001
        return None


def _open_request(
    opener: urllib.request.OpenerDirector, request: urllib.request.Request
):
    """実際に urlopen する薄いラッパー。試験ではここを monkeypatch する。"""
    return opener.open(request, timeout=_CONNECT_TIMEOUT_SEC)


def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = response.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)[:limit]


class _TextExtractor(HTMLParser):
    """HTML からタグを落として本文だけを残す。完璧な抽出は狙わない。

    <script> と <style> の中身は読み飛ばす。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def _decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    if match:
        charset = match.group(1)
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _html_to_text(body: bytes, content_type: str) -> str:
    raw = _decode_body(body, content_type)
    looks_like_html = "html" in content_type.lower() or "<html" in raw[:1000].lower()
    if not looks_like_html:
        return _collapse_whitespace(raw)

    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
    except Exception:
        # 壊れた HTML でも落とさない。素のテキストとして返す。
        return _collapse_whitespace(raw)
    return _collapse_whitespace(extractor.get_text())


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"[ \t\r\n\f\v]+", " ", text).strip()


def fetch_url(url: str, max_chars: int = 20000) -> dict[str, Any]:
    """URL を取得し、本文をテキストで返す。

    失敗しても例外を投げず {"error": "理由"} を返す。リダイレクトは自動追跡せず、
    1 段ずつ validate_url で検査してから追う（上限 _MAX_REDIRECTS 回）。
    """
    if not isinstance(url, str) or not url.strip():
        return {"error": "url は空でない文字列にしてください"}
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else 20000

    opener = urllib.request.build_opener(_NoAutoRedirect)
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        reason = validate_url(current)
        if reason:
            return {"error": reason}

        request = urllib.request.Request(current, headers={"User-Agent": _USER_AGENT})
        try:
            response = _open_request(opener, request)
        except urllib.error.HTTPError as exc:
            if exc.code in _REDIRECT_STATUSES:
                location = exc.headers.get("Location")
                if not location:
                    return {"error": f"リダイレクト応答（{exc.code}）に Location がありません"}
                current = urljoin(current, location)
                continue
            return {"error": f"HTTP エラー: {exc.code} {exc.reason}"}
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            return {"error": f"取得に失敗しました: {exc}"}
        except OSError as exc:
            return {"error": f"取得に失敗しました: {exc}"}

        try:
            body = _read_limited(response, _MAX_RESPONSE_BYTES)
            content_type = response.headers.get("Content-Type", "") or ""
        finally:
            response.close()

        text = _html_to_text(body, content_type)
        truncated = len(text) > limit
        if truncated:
            text = text[:limit] + f"\n…（{limit} 文字で切り詰め。全文ではない）"
        return {"url": current, "text": text, "truncated": truncated}

    return {"error": f"リダイレクトが上限（{_MAX_REDIRECTS} 回）を超えました: {current}"}


def _run_ddgs_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """ddgs を実際に呼ぶ薄いラッパー。試験ではここを monkeypatch する（ddgs 未導入でも試験できる）。"""
    from ddgs import DDGS  # 遅延 import。web.enabled=false の環境では ddgs が無くてもよい。

    with DDGS() as engine:
        return list(engine.text(query, max_results=max_results))


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """DuckDuckGo で検索する。失敗しても例外を投げず {"error": "理由"} を返す。"""
    if not isinstance(query, str) or not query.strip():
        return {"error": "query は空でない文字列にしてください"}
    limit = max_results if isinstance(max_results, int) and max_results > 0 else 5
    limit = min(limit, 20)

    try:
        raw_results = _run_ddgs_search(query, limit)
    except Exception as exc:  # ddgs 側の例外型は多岐（ネットワーク断・レート制限等）。まとめて拾う
        return {"error": f"検索に失敗しました: {exc}"}

    results = [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("href") or item.get("url") or ""),
            "snippet": str(item.get("body") or item.get("snippet") or ""),
        }
        for item in raw_results[:limit]
    ]
    return {"results": results}
