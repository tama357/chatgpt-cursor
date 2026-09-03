#!/usr/bin/env python3
"""競輪予想の検証・記録・Chatwork。6:00は第一予想まで。最終転記はChatGPT最終予想だけ。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
import keirin_drive_state as drive_state  # noqa: E402
from keirin_submission_state import chatwork_sending_enabled  # noqa: E402


PICK_RE = re.compile(r"^([1-9])-([1-9])-([1-9]+)$")
TRIFECTA_RE = re.compile(r"^[1-9]-[1-9]-[1-9]$")


class ValidationError(ValueError):
    pass


KEIRIN_CURSOR_OPS_STOPPED = (
    "競輪予想のCursor連携運用は終了しています。"
    "収集・第一予想・ingest-final・結果記載・シート書き込み・Chatwork・Artifact・Drive同期は実行しません。"
)


def expand_pick(compact: str) -> tuple[str, ...]:
    match = PICK_RE.fullmatch(compact)
    if not match:
        raise ValidationError(f"買い目の形式が不正です: {compact}")
    first, second, candidates = match.groups()
    if first == second:
        raise ValidationError(f"1着と2着が重複しています: {compact}")
    if len(set(candidates)) != len(candidates):
        raise ValidationError(f"3着候補に重複があります: {compact}")
    if first in candidates or second in candidates:
        raise ValidationError(f"同じ選手が複数着に含まれています: {compact}")
    return tuple(f"{first}-{second}-{third}" for third in candidates)


def check_hit(trifecta: str, tickets: list[dict[str, Any]]) -> bool:
    combinations: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if isinstance(pick, str):
            combinations.update(expand_pick(pick))
    return trifecta in combinations


def extract_axis(tickets: list[dict[str, Any]]) -> str:
    if not isinstance(tickets, list) or not tickets:
        raise ValidationError("本線買い目からaxisを抽出できません")
    firsts: set[str] = set()
    for ticket in tickets:
        if not isinstance(ticket, dict) or ticket.get("type") != "本線":
            continue
        compact = ticket.get("pick")
        if not isinstance(compact, str):
            raise ValidationError("本線買い目の形式が不正です")
        match = PICK_RE.fullmatch(compact)
        if not match:
            raise ValidationError(f"買い目の形式が不正です: {compact}")
        firsts.add(match.group(1))
    if not firsts:
        raise ValidationError("本線買い目が無いためaxisを抽出できません")
    if len(firsts) > 1:
        raise ValidationError("本線の1着番号が複数あるためaxisを特定できません")
    return firsts.pop()


def second_candidates(tickets: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if not isinstance(pick, str):
            continue
        parts = pick.split("-")
        if len(parts) >= 2:
            result.add(parts[1])
    return result


def third_candidates(tickets: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for ticket in tickets:
        pick = ticket.get("pick")
        if not isinstance(pick, str):
            continue
        parts = pick.split("-")
        if len(parts) >= 3:
            result.update(parts[2])
    return result


def compute_close_miss(
    *,
    status: str,
    axis: str,
    tickets: list[dict[str, Any]],
    trifecta: str,
) -> bool:
    if status != "ハズレ":
        return False
    if not isinstance(trifecta, str) or not TRIFECTA_RE.fullmatch(trifecta):
        raise ValidationError("close_miss判定には正規の三連単が必要です")
    if not isinstance(axis, str) or not axis:
        raise ValidationError("close_miss判定にはaxisが必要です")
    first, second, third = trifecta.split("-")
    axis_ok = axis == first
    second_ok = second in second_candidates(tickets)
    third_ok = third in third_candidates(tickets)
    return bool(axis_ok and (second_ok or third_ok))


def chatwork_request(method: str, url: str, token: str, body: dict[str, str] | None = None) -> Any:
    encoded = urllib.parse.urlencode(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=encoded,
        method=method,
        headers={"X-ChatWorkToken": token, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = response.read().decode("utf-8")
            if response.status != 200:
                raise RuntimeError(f"Chatwork API HTTP {response.status}: {payload}")
            return json.loads(payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chatwork API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Chatwork APIへ接続できません: {exc.reason}") from exc


def send_chatwork(message: str, token: str, room_id: str) -> dict[str, Any]:
    if not chatwork_sending_enabled():
        raise ValidationError("Chatwork送信は個人運用のため停止しています。")
    base_url = f"https://api.chatwork.com/v2/rooms/{room_id}/messages"
    recent = chatwork_request("GET", f"{base_url}?force=1", token)
    if isinstance(recent, list) and any(item.get("body") == message for item in recent[-20:]):
        return {"skipped": True, "reason": "同一本文が直近メッセージに存在します"}
    response = chatwork_request("POST", base_url, token, {"body": message, "self_unread": "0"})
    if not isinstance(response, dict) or not response.get("message_id"):
        raise RuntimeError(f"Chatwork APIの成功応答にmessage_idがありません: {response}")
    return response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser(
        "prepare-today",
        help="当日データを集め、候補5〜10RとCursor第一予想をinput JSONにする。最終確定・送信はしない",
    )
    prepare.add_argument("--date", help="対象日 YYYY-MM-DD（省略時は今日・JST）")
    prepare.add_argument("--races-file", type=Path, help="ネット無し検証用のレースJSON")
    prepare.add_argument("--skip-drive", action="store_true")
    ingest = subparsers.add_parser(
        "ingest-final",
        help="ChatGPT最終予想を取り込む。無ければ停止し、Cursorは予想しない",
    )
    ingest.add_argument("json_file", nargs="?")
    ingest.add_argument("--date")
    ingest.add_argument("--skip-sheets", action="store_true")
    ingest.add_argument("--skip-drive", action="store_true")
    ingest.add_argument("--confirm-send", action="store_true")
    poll = subparsers.add_parser("poll-ingest-final")
    poll.add_argument("--date")
    poll.add_argument("--skip-sheets", action="store_true")
    poll.add_argument("--confirm-send", action="store_true")
    results_cmd = subparsers.add_parser("results-yesterday")
    results_cmd.add_argument("--date")
    results_cmd.add_argument("--results-file", type=Path)
    results_cmd.add_argument("--skip-sheets", action="store_true")
    today = subparsers.add_parser("predict-today")
    today.add_argument("--date")
    today.add_argument("--races-file", type=Path)
    today.add_argument("json_file", nargs="?")
    today.add_argument("--skip-sheets", action="store_true")
    today.add_argument("--confirm-send", action="store_true")
    today.add_argument("--skip-drive", action="store_true")
    send = subparsers.add_parser("send-predictions")
    send.add_argument("json_file")
    send.add_argument("--confirm-send", action="store_true")
    return parser


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_cursor_command(args: argparse.Namespace) -> str:
    raise ValidationError(KEIRIN_CURSOR_OPS_STOPPED)
    import keirin_cursor_flow as flow
    from keirin_jst import today_str, yesterday_str

    root = _root()
    confirm_send = bool(getattr(args, "confirm_send", False)) and chatwork_sending_enabled()
    if args.command == "prepare-today":
        return flow.prepare_today(
            root,
            args.date,
            races_file=getattr(args, "races_file", None),
            sync_drive=not getattr(args, "skip_drive", False),
        )
    if args.command == "ingest-final":
        final_file = Path(args.json_file) if getattr(args, "json_file", None) else None
        return flow.ingest_final(
            root,
            args.date,
            final_file=final_file,
            write_sheets=not args.skip_sheets,
            confirm_send=confirm_send,
            send_fn=None,
            sync_drive=not getattr(args, "skip_drive", False),
        )
    if args.command == "poll-ingest-final":
        return flow.poll_ingest_final(
            root,
            args.date,
            write_sheets=not args.skip_sheets,
            confirm_send=confirm_send,
            send_fn=None,
        )
    if args.command == "results-yesterday":
        return flow.process_results(
            root,
            args.date or yesterday_str(),
            results_file=getattr(args, "results_file", None),
            write_sheets=not args.skip_sheets,
        )
    if args.command == "predict-today":
        return flow.run_today_or_stop(
            root,
            args.date or today_str(),
            races_file=getattr(args, "races_file", None),
            final_file=Path(args.json_file) if getattr(args, "json_file", None) else None,
            write_sheets=not getattr(args, "skip_sheets", False),
            confirm_send=confirm_send,
            sync_drive=not getattr(args, "skip_drive", False),
        )
    raise ValidationError(f"未対応のコマンドです: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raise ValidationError(KEIRIN_CURSOR_OPS_STOPPED)
        if args.command == "send-predictions":
            raise ValidationError("Chatwork送信は個人運用のため停止しています。")
        print(_run_cursor_command(args))
        return 0
    except (
        ValidationError,
        RuntimeError,
        OSError,
        json.JSONDecodeError,
        drive_state.DriveStateError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
