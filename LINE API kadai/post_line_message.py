#!/usr/bin/env python3
"""LINE Messaging API を使ってメッセージを送信するスクリプト。"""

import argparse
import getpass
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"
BROADCAST_ENDPOINT = "https://api.line.me/v2/bot/message/broadcast"

# 一時的なサーバー側エラー（5xx）はリトライで成功する可能性がある。
RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
MAX_RETRIES = 3


def load_dotenv_file() -> None:
    """スクリプト直下または親フォルダの .env を読み込む（未設定のキーのみ）。"""
    for env_path in (SCRIPT_DIR / ".env", SCRIPT_DIR.parent / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


class LineApiError(Exception):
    """LINE Messaging API のエラーを表す。"""

    def __init__(self, status_code: int, message: str, payload: dict | None = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}
        super().__init__(f"HTTP {status_code}: {message}")


def _parse_error(response: requests.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("message", response.text))
    except ValueError:
        pass
    return response.text or f"HTTP {response.status_code}"


def send_message(
    access_token: str,
    text: str,
    to: str | None = None,
    max_retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """LINE にテキストメッセージを送信する。

    to が指定されていればその宛先にプッシュ送信し、
    省略時は友だち全員へブロードキャスト送信する。

    一時的なサーバー側エラー（5xx）や通信失敗のときは、二重送信を防ぐ
    X-Line-Retry-Key を付けて自動で再送する。
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        # 同じキーで再送すれば、LINE 側で重複送信を防いでくれる。
        "X-Line-Retry-Key": str(uuid.uuid4()),
    }
    payload: dict[str, Any] = {"messages": [{"type": "text", "text": text}]}

    if to:
        endpoint = PUSH_ENDPOINT
        payload["to"] = to
    else:
        endpoint = BROADCAST_ENDPOINT

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                endpoint, headers=headers, json=payload, timeout=30
            )
        except requests.RequestException as e:
            last_error = e
            if attempt >= max_retries:
                raise
        else:
            if response.ok:
                try:
                    return response.json() if response.text else {}
                except ValueError:
                    return {}

            # 4xx などリトライしても結果が変わらないエラーは即座に中断する。
            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise LineApiError(response.status_code, _parse_error(response))

            last_error = LineApiError(response.status_code, _parse_error(response))
            if attempt >= max_retries:
                raise last_error

        wait = 2 ** (attempt - 1)  # 1秒 → 2秒 → 4秒 と待ち時間を伸ばす
        print(
            f"一時的なエラーのため {wait} 秒後に再送します"
            f"（{attempt}/{max_retries} 回目）...",
            file=sys.stderr,
        )
        time.sleep(wait)

    # ここには通常到達しないが、保険として最後のエラーを送出する。
    assert last_error is not None
    raise last_error


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """はい/いいえ形式の確認入力を受け付ける。"""
    suffix = "[はい/いいえ]"
    answer = input(f"{question} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "はい", "hai")


def prompt_access_token() -> str:
    """チャネルアクセストークンを対話形式で取得する。"""
    env_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if env_token:
        print("設定済みの LINE_CHANNEL_ACCESS_TOKEN を使います（.env または環境変数）。")
        if prompt_yes_no("このトークンを使いますか？", default=True):
            return env_token

    print(
        "\nチャネルアクセストークンの取得方法:\n"
        "  LINE Developers コンソール → 対象チャネル → Messaging API 設定\n"
        "  → 「チャネルアクセストークン（長期）」を発行してコピー\n"
        "  おすすめ: .env に LINE_CHANNEL_ACCESS_TOKEN=... を書く\n"
    )
    while True:
        token = getpass.getpass("LINE チャネルアクセストークン: ").strip()
        if token:
            return token
        print("トークンは必須です。もう一度入力してください。")


def prompt_to() -> str | None:
    """送信先ユーザー ID を対話形式で取得する（空欄ならブロードキャスト）。"""
    env_to = os.environ.get("LINE_TO")
    if env_to:
        print("設定済みの LINE_TO を送信先に使えます（.env または環境変数）。")
        if prompt_yes_no(f"送信先 {env_to} を使いますか？", default=True):
            return env_to

    to = input(
        "送信先ユーザー ID（空欄なら友だち全員へブロードキャスト）: "
    ).strip()
    return to or None


def prompt_message() -> str:
    """送信メッセージを対話形式で取得する。"""
    while True:
        message = input("メッセージ: ").strip()
        if message:
            return message
        print("メッセージは必須です。もう一度入力してください。")


def run_interactive() -> tuple[str, str | None, str]:
    """対話形式でトークン・宛先・メッセージを入力する。"""
    print("=== LINE メッセージ送信 ===\n")
    access_token = prompt_access_token()
    print()
    to = prompt_to()
    message = prompt_message()
    print()
    print("--- 入力内容 ---")
    print(f"送信先: {to if to else '友だち全員（ブロードキャスト）'}")
    print(f"メッセージ: {message}")
    print("----------------")
    if not prompt_yes_no("この内容で送信しますか？", default=True):
        print("送信をキャンセルしました。")
        raise SystemExit(0)
    return access_token, to, message


def print_error_hint(e: LineApiError) -> None:
    """ステータスコードに応じたヒントを表示する。"""
    if e.status_code == 401:
        print(
            "ヒント: チャネルアクセストークンが無効か期限切れです。"
            "LINE Developers コンソールで再発行してください。",
            file=sys.stderr,
        )
    elif e.status_code == 403:
        print(
            "ヒント: 権限がありません。Messaging API チャネルか、"
            "プランの送信上限を確認してください。",
            file=sys.stderr,
        )
    elif e.status_code == 400:
        print(
            "ヒント: 宛先ユーザー ID が正しいか確認してください。"
            "（Bot と友だちでないユーザーへはプッシュ送信できません）",
            file=sys.stderr,
        )
    elif e.status_code == 429:
        print(
            "ヒント: 送信上限に達しています。しばらく待ってから再試行してください。",
            file=sys.stderr,
        )
    elif e.status_code in RETRYABLE_STATUS_CODES:
        print(
            "ヒント: LINE 側の一時的なサーバーエラーです（あなたのコードや"
            "トークンの問題ではありません）。自動で再送しても解消しない場合は、"
            "数分おいてからもう一度実行してください。",
            file=sys.stderr,
        )


def main() -> int:
    load_dotenv_file()
    parser = argparse.ArgumentParser(
        description="LINE Messaging API でメッセージを送信します。"
    )
    parser.add_argument("message", nargs="?", help="送信するメッセージ本文")
    parser.add_argument(
        "--to",
        default=None,
        help="送信先ユーザー ID（未指定時は LINE_TO、それも無ければブロードキャスト）",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="チャネルアクセストークン（未指定時は LINE_CHANNEL_ACCESS_TOKEN）",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="対話形式で入力する",
    )
    args = parser.parse_args()

    if args.interactive or args.message is None:
        access_token, to, message = run_interactive()
    else:
        access_token = args.token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
        to = args.to or os.environ.get("LINE_TO") or None
        message = args.message

        if not access_token:
            print(
                "エラー: チャネルアクセストークンが未設定です。\n"
                "  - .env に LINE_CHANNEL_ACCESS_TOKEN=... を書く\n"
                "  - または --token オプションで指定する",
                file=sys.stderr,
            )
            return 1

    try:
        send_message(access_token, message, to)
    except LineApiError as e:
        print(f"LINE API エラー: {e.message}", file=sys.stderr)
        print_error_hint(e)
        return 1
    except requests.RequestException as e:
        print(f"通信エラー: {e}", file=sys.stderr)
        return 1

    destination = to if to else "友だち全員（ブロードキャスト）"
    print(f"送信成功: 宛先={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
