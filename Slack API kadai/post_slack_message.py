#!/usr/bin/env python3
"""Slack API を使って指定チャンネルにメッセージを投稿するスクリプト。"""

import argparse
import getpass
import os
import sys

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def normalize_channel(channel: str) -> str:
    """チャンネル指定を Slack API 向けの形式に整える。"""
    channel = channel.strip()
    if not channel.startswith(("#", "C", "G", "D")):
        return f"#{channel}"
    return channel


def post_message(token: str, channel: str, text: str) -> dict:
    """指定チャンネルにメッセージを投稿する。"""
    client = WebClient(token=token)
    response = client.chat_postMessage(channel=channel, text=text)
    return response.data


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Y/n 形式の確認入力を受け付ける。"""
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def prompt_token() -> str:
    """Bot Token を対話形式で取得する。"""
    env_token = os.environ.get("SLACK_BOT_TOKEN")
    if env_token:
        print("環境変数 SLACK_BOT_TOKEN が設定されています。")
        if prompt_yes_no("このトークンを使いますか？", default=True):
            return env_token

    while True:
        token = getpass.getpass("Slack Bot Token (xoxb-...): ").strip()
        if token:
            return token
        print("トークンは必須です。もう一度入力してください。")


def prompt_channel() -> str:
    """投稿先チャンネルを対話形式で取得する。"""
    while True:
        channel = input(
            "チャンネル名または ID (例: general / #general / C0123456789): "
        ).strip()
        if channel:
            return normalize_channel(channel)
        print("チャンネルは必須です。もう一度入力してください。")


def prompt_message() -> str:
    """投稿メッセージを対話形式で取得する。"""
    while True:
        message = input("メッセージ: ").strip()
        if message:
            return message
        print("メッセージは必須です。もう一度入力してください。")


def run_interactive() -> tuple[str, str, str]:
    """対話形式でトークン・チャンネル・メッセージを入力する。"""
    print("=== Slack メッセージ投稿 ===\n")
    token = prompt_token()
    print()
    channel = prompt_channel()
    message = prompt_message()
    print()
    print("--- 入力内容 ---")
    print(f"チャンネル: {channel}")
    print(f"メッセージ: {message}")
    print("----------------")
    if not prompt_yes_no("この内容で投稿しますか？", default=True):
        print("投稿をキャンセルしました。")
        raise SystemExit(0)
    return token, channel, message


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Slack の指定チャンネルにメッセージを投稿します。"
    )
    parser.add_argument(
        "channel",
        nargs="?",
        help="投稿先チャンネル（例: #general または C0123456789）",
    )
    parser.add_argument(
        "message",
        nargs="?",
        help="投稿するメッセージ本文",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Slack Bot Token（未指定時は環境変数 SLACK_BOT_TOKEN を使用）",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="対話形式で入力する",
    )
    args = parser.parse_args()

    if args.interactive or args.channel is None or args.message is None:
        if args.channel is not None or args.message is not None:
            print(
                "エラー: チャンネルとメッセージは両方指定するか、"
                "どちらも省略して対話形式で入力してください。",
                file=sys.stderr,
            )
            return 1
        token, channel, message = run_interactive()
    else:
        token = args.token or os.environ.get("SLACK_BOT_TOKEN")
        channel = normalize_channel(args.channel)
        message = args.message

        if not token:
            print(
                "エラー: Slack Bot Token が設定されていません。\n"
                "環境変数 SLACK_BOT_TOKEN を設定するか、"
                "--token オプションで指定してください。",
                file=sys.stderr,
            )
            return 1

    try:
        result = post_message(token, channel, message)
    except SlackApiError as e:
        error = e.response.get("error", str(e))
        print(f"Slack API エラー: {error}", file=sys.stderr)
        return 1

    print(f"投稿成功: ts={result.get('ts')}, channel={result.get('channel')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
