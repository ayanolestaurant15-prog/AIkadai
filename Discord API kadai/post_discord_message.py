#!/usr/bin/env python3
"""Discord Webhook を使ってチャンネルにメッセージを投稿・自動通知するスクリプト。"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
WEBHOOK_URL_PATTERN = re.compile(
    r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[\w-]+",
    re.IGNORECASE,
)


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


class DiscordWebhookError(Exception):
    """Discord Webhook API のエラーを表す。"""

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


def _safe_json(response: requests.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def normalize_webhook_url(url: str) -> str:
    """Webhook URL を検証して正規化する。"""
    url = url.strip()
    if not WEBHOOK_URL_PATTERN.match(url):
        raise ValueError(
            "Discord Webhook URL の形式が正しくありません。\n"
            "例: https://discord.com/api/webhooks/123456789/AbCdEf..."
        )
    return url.rstrip("/")


def webhook_post_url(webhook_url: str, *, wait: bool = True) -> str:
    """送信後にメッセージ情報を返すため wait=true を付与する。"""
    if not wait:
        return webhook_url
    parsed = urlparse(webhook_url)
    query = parse_qs(parsed.query)
    query["wait"] = ["true"]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def post_webhook(
    webhook_url: str,
    content: str,
    username: str | None = None,
) -> dict[str, Any]:
    """Webhook でチャンネルにメッセージを投稿する。"""
    url = normalize_webhook_url(webhook_url)
    payload: dict[str, str] = {"content": content}
    if username:
        payload["username"] = username

    response = requests.post(
        webhook_post_url(url),
        json=payload,
        timeout=30,
    )
    if not response.ok:
        raise DiscordWebhookError(
            response.status_code, _parse_error(response), _safe_json(response)
        )
    return response.json()


def send_notification(
    webhook_url: str,
    content: str,
    username: str | None = None,
) -> dict[str, Any]:
    """Webhook 経由で通知を送る。"""
    return post_webhook(webhook_url, content, username)


def prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def prompt_webhook_url() -> str:
    env_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if env_url:
        print("設定済みの DISCORD_WEBHOOK_URL を使います（.env または環境変数）。")
        if prompt_yes_no("この Webhook URL を使いますか？", default=True):
            return normalize_webhook_url(env_url)

    print(
        "\nWebhook URL の取得方法:\n"
        "  Discord → チャンネル設定 → 連携サービス → ウェブフック → 新規作成\n"
        "  → 「ウェブフック URL をコピー」\n"
        "  おすすめ: .env に DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...\n"
    )
    while True:
        url = input("Discord Webhook URL: ").strip()
        if not url:
            print("Webhook URL は必須です。もう一度入力してください。")
            continue
        try:
            return normalize_webhook_url(url)
        except ValueError as e:
            print(e)


def prompt_message() -> str:
    while True:
        message = input("通知メッセージ: ").strip()
        if message:
            return message
        print("メッセージは必須です。もう一度入力してください。")


def run_interactive() -> tuple[str, str]:
    print("=== Discord Webhook 通知 ===\n")
    webhook_url = prompt_webhook_url()
    print()
    message = prompt_message()
    print()
    print("--- 入力内容 ---")
    print(f"Webhook: {mask_webhook_url(webhook_url)}")
    print(f"メッセージ: {message}")
    print("----------------")
    if not prompt_yes_no("この内容で通知を送りますか？", default=True):
        print("送信をキャンセルしました。")
        raise SystemExit(0)
    return webhook_url, message


def mask_webhook_url(url: str) -> str:
    """ログ表示用に Webhook トークン部分をマスクする。"""
    parts = url.rstrip("/").rsplit("/", 1)
    if len(parts) == 2:
        return f"{parts[0]}/***"
    return "***"


def run_auto_notify(
    webhook_url: str,
    message: str,
    interval: float,
    count: int | None,
    username: str | None = None,
) -> None:
    """一定間隔で Webhook へ自動通知を送る。"""
    sent = 0
    print(
        f"自動通知を開始します（間隔: {interval} 秒"
        + (f", 回数: {count}" if count is not None else ", 無限")
        + "）。Ctrl+C で停止。"
    )
    try:
        while count is None or sent < count:
            result = send_notification(webhook_url, message, username)
            sent += 1
            print(
                f"[{sent}] 送信成功: message_id={result.get('id')}, "
                f"channel_id={result.get('channel_id')}"
            )
            if count is not None and sent >= count:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n自動通知を停止しました（送信回数: {sent}）。")


def resolve_config(args: argparse.Namespace) -> tuple[str, str]:
    if args.interactive or args.message is None:
        if args.message is not None:
            print(
                "エラー: メッセージをコマンドで指定する場合は "
                "Webhook URL も指定するか、対話形式 (-i) を使ってください。",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return run_interactive()

    webhook_url = args.webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")
    message = args.message

    if not webhook_url:
        print(
            "エラー: Webhook URL が未設定です。",
            file=sys.stderr,
        )
        print(
            "  - .env に DISCORD_WEBHOOK_URL=... を書く",
            file=sys.stderr,
        )
        print(
            "  - または --webhook-url を指定する",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        webhook_url = normalize_webhook_url(webhook_url)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        raise SystemExit(1)

    assert message is not None
    return webhook_url, message


def print_webhook_error_hint(e: DiscordWebhookError) -> None:
    if e.status_code in (401, 404):
        print(
            "ヒント: Webhook URL が無効か、Discord 上で削除されています。"
            "チャンネル設定から URL を再コピーしてください。",
            file=sys.stderr,
        )
    elif e.status_code == 429:
        print(
            "ヒント: 送信が速すぎます。--interval を長くするか、しばらく待ってください。",
            file=sys.stderr,
        )


def main() -> int:
    load_dotenv_file()
    parser = argparse.ArgumentParser(
        description="Discord Webhook でチャンネルに通知メッセージを送ります。"
    )
    parser.add_argument("message", nargs="?", help="送信する通知メッセージ")
    parser.add_argument(
        "--webhook-url",
        help="Discord Webhook URL（未指定時は DISCORD_WEBHOOK_URL）",
    )
    parser.add_argument(
        "--username",
        help="Webhook 投稿時の表示名（任意）",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="対話形式で入力する",
    )
    parser.add_argument(
        "--interval",
        type=float,
        metavar="SECONDS",
        help="自動通知の送信間隔（秒）。指定すると定期送信モードになる",
    )
    parser.add_argument(
        "--count",
        type=int,
        metavar="N",
        help="自動通知の送信回数（省略時は Ctrl+C まで継続）",
    )
    args = parser.parse_args()

    if args.interval is not None and args.interval <= 0:
        print("エラー: --interval は正の数を指定してください。", file=sys.stderr)
        return 1
    if args.count is not None and args.count <= 0:
        print("エラー: --count は正の整数を指定してください。", file=sys.stderr)
        return 1

    webhook_url, message = resolve_config(args)
    username = args.username or os.environ.get("DISCORD_WEBHOOK_USERNAME")

    try:
        if args.interval is not None:
            run_auto_notify(
                webhook_url, message, args.interval, args.count, username
            )
            return 0

        result = send_notification(webhook_url, message, username)
    except DiscordWebhookError as e:
        print(f"Discord Webhook エラー: {e.message}", file=sys.stderr)
        print_webhook_error_hint(e)
        return 1
    except requests.RequestException as e:
        print(f"通信エラー: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    print(
        f"通知送信成功: message_id={result.get('id')}, "
        f"channel_id={result.get('channel_id')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
