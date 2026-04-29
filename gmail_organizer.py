"""Gmail Organizer

ルールベースで受信メールを分類し、ラベル付与・アーカイブ・既読化・ゴミ箱送りを行う。

使い方:
    python gmail_organizer.py --rules rules.yaml --query "newer_than:7d" --dry-run
    python gmail_organizer.py --rules rules.yaml --query "newer_than:7d"   # 実適用
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


# ---------- 認証 ----------

def get_service(credentials_path: str, token_path: str):
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ---------- ルール ----------

@dataclass
class Rule:
    name: str
    from_re: re.Pattern | None
    subject_re: re.Pattern | None
    body_re: re.Pattern | None
    has_list_unsubscribe: bool | None
    label: str | None
    archive: bool
    mark_read: bool
    trash: bool


def _compile(pattern: str | None) -> re.Pattern | None:
    return re.compile(pattern, re.IGNORECASE) if pattern else None


def load_rules(path: str) -> tuple[list[Rule], str | None]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules: list[Rule] = []
    for r in data.get("rules", []):
        m = r.get("match", {}) or {}
        a = r.get("action", {}) or {}
        rules.append(Rule(
            name=r.get("name", "(no name)"),
            from_re=_compile(m.get("from")),
            subject_re=_compile(m.get("subject")),
            body_re=_compile(m.get("body")),
            has_list_unsubscribe=m.get("has_list_unsubscribe"),
            label=a.get("label"),
            archive=bool(a.get("archive", False)),
            mark_read=bool(a.get("mark_read", False)),
            trash=bool(a.get("trash", False)),
        ))
    return rules, data.get("default_label")


# ---------- ラベル管理 ----------

class LabelCache:
    def __init__(self, service):
        self.service = service
        self._by_name: dict[str, str] = {}
        for lbl in service.users().labels().list(userId="me").execute().get("labels", []):
            self._by_name[lbl["name"]] = lbl["id"]

    def ensure(self, name: str) -> str:
        if name in self._by_name:
            return self._by_name[name]
        body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = self.service.users().labels().create(userId="me", body=body).execute()
        self._by_name[name] = created["id"]
        return created["id"]


# ---------- メール取得 & 評価 ----------

def list_message_ids(service, query: str, max_results: int) -> list[str]:
    ids: list[str] = []
    page_token = None
    while len(ids) < max_results:
        resp = service.users().messages().list(
            userId="me",
            q=query,
            pageToken=page_token,
            maxResults=min(500, max_results - len(ids)),
        ).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def parse_list_unsubscribe(value: str) -> tuple[list[str], list[str]]:
    """List-Unsubscribe ヘッダから URL と mailto を取り出す。

    RFC 2369: `<https://...>, <mailto:...?subject=unsubscribe>` のような形式。
    """
    urls: list[str] = []
    mailtos: list[str] = []
    for token in re.findall(r"<([^>]+)>", value or ""):
        token = token.strip()
        if token.lower().startswith("mailto:"):
            mailtos.append(token)
        elif token.lower().startswith(("http://", "https://")):
            urls.append(token)
    return urls, mailtos


def _extract_body(payload: dict) -> str:
    """text/plain を優先で本文を取り出す。なければ空文字。"""
    if payload.get("mimeType", "").startswith("text/") and payload.get("body", {}).get("data"):
        try:
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
        except Exception:
            return ""
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


def get_message(service, msg_id: str) -> dict:
    return service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()


def match_rule(msg: dict, rule: Rule) -> bool:
    headers = msg.get("payload", {}).get("headers", [])
    sender = _header(headers, "From")
    subject = _header(headers, "Subject")
    list_unsub = bool(_header(headers, "List-Unsubscribe"))

    if rule.from_re and not rule.from_re.search(sender):
        return False
    if rule.subject_re and not rule.subject_re.search(subject):
        return False
    if rule.has_list_unsubscribe is not None and list_unsub != rule.has_list_unsubscribe:
        return False
    if rule.body_re:
        body = _extract_body(msg.get("payload", {}))
        if not rule.body_re.search(body):
            return False
    return True


def classify(msg: dict, rules: Iterable[Rule]) -> Rule | None:
    for rule in rules:
        if match_rule(msg, rule):
            return rule
    return None


# ---------- 適用 ----------

def apply(service, msg_id: str, rule: Rule, labels: LabelCache, default_label: str | None, dry_run: bool) -> str:
    add_label = rule.label or default_label
    add_label_ids: list[str] = []
    remove_label_ids: list[str] = []

    if add_label:
        add_label_ids.append(labels.ensure(add_label))
    if rule.archive:
        remove_label_ids.append("INBOX")
    if rule.mark_read:
        remove_label_ids.append("UNREAD")

    summary_parts = []
    if add_label:
        summary_parts.append(f"+{add_label}")
    if rule.archive:
        summary_parts.append("archive")
    if rule.mark_read:
        summary_parts.append("read")
    if rule.trash:
        summary_parts.append("TRASH")
    summary = ",".join(summary_parts) or "(no-op)"

    if dry_run:
        return summary

    if rule.trash:
        service.users().messages().trash(userId="me", id=msg_id).execute()
        return summary

    if add_label_ids or remove_label_ids:
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"addLabelIds": add_label_ids, "removeLabelIds": remove_label_ids},
        ).execute()
    return summary


# ---------- メイン ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="Gmail を YAML ルールで整理する")
    parser.add_argument("--rules", default="rules.yaml", help="ルール YAML のパス")
    parser.add_argument("--credentials", default="credentials.json", help="OAuth クライアント JSON")
    parser.add_argument("--token", default="token.json", help="アクセストークン保存先")
    parser.add_argument("--query", default="in:inbox newer_than:7d",
                        help="Gmail 検索クエリ (例: 'in:inbox newer_than:30d')")
    parser.add_argument("--max", type=int, default=200, help="処理する最大メール数")
    parser.add_argument("--dry-run", action="store_true", help="実行せず判定結果のみ表示")
    parser.add_argument("--unsubscribe-out", default=None,
                        help="List-Unsubscribe を持つメールの解除リンク一覧を Markdown で出力するパス")
    args = parser.parse_args()

    if not os.path.exists(args.rules):
        print(f"ルールファイルが見つかりません: {args.rules}", file=sys.stderr)
        return 2
    if not os.path.exists(args.credentials):
        print(f"認証情報が見つかりません: {args.credentials}\n"
              "README の手順で credentials.json を取得してください。", file=sys.stderr)
        return 2

    rules, default_label = load_rules(args.rules)
    print(f"ルール {len(rules)} 件を読み込みました (default_label={default_label})")

    service = get_service(args.credentials, args.token)
    labels = LabelCache(service)

    msg_ids = list_message_ids(service, args.query, args.max)
    print(f"対象メール: {len(msg_ids)} 件 (query={args.query!r}, dry_run={args.dry_run})")

    counts: dict[str, int] = {}
    # 送信者ごとに 1 行に集約: sender -> {"subjects": set, "urls": set, "mailtos": set, "one_click": bool}
    unsub_index: dict[str, dict] = {}

    for i, mid in enumerate(msg_ids, 1):
        try:
            msg = get_message(service, mid)
            headers = msg.get("payload", {}).get("headers", [])
            sender = _header(headers, "From")
            subject = _header(headers, "Subject")

            lu = _header(headers, "List-Unsubscribe")
            if lu:
                urls, mailtos = parse_list_unsubscribe(lu)
                one_click = _header(headers, "List-Unsubscribe-Post").strip().lower() == "list-unsubscribe=one-click"
                entry = unsub_index.setdefault(sender, {
                    "subjects": set(), "urls": set(), "mailtos": set(), "one_click": False,
                })
                entry["subjects"].add(subject[:80])
                entry["urls"].update(urls)
                entry["mailtos"].update(mailtos)
                entry["one_click"] = entry["one_click"] or one_click

            rule = classify(msg, rules)
            if rule is None and default_label is None:
                print(f"[{i}/{len(msg_ids)}] {mid}: SKIP (no match)")
                counts["__skip__"] = counts.get("__skip__", 0) + 1
                continue
            pseudo_rule = rule or Rule(
                name="(default)", from_re=None, subject_re=None, body_re=None,
                has_list_unsubscribe=None, label=default_label,
                archive=False, mark_read=False, trash=False,
            )
            summary = apply(service, mid, pseudo_rule, labels, default_label, args.dry_run)
            print(f"[{i}/{len(msg_ids)}] {pseudo_rule.name}: {summary}  | {subject[:60]}")
            counts[pseudo_rule.name] = counts.get(pseudo_rule.name, 0) + 1
        except HttpError as e:
            print(f"[{i}/{len(msg_ids)}] {mid}: ERROR {e}", file=sys.stderr)

    print("\n=== 集計 ===")
    for name, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {n}")

    if args.unsubscribe_out:
        write_unsubscribe_report(args.unsubscribe_out, unsub_index)
        print(f"\n解除リンク一覧を出力しました: {args.unsubscribe_out} "
              f"({len(unsub_index)} 送信者)")
    elif unsub_index:
        print(f"\nList-Unsubscribe 付きメールが {len(unsub_index)} 送信者ぶん見つかりました。"
              "  --unsubscribe-out unsubscribe.md で一覧を保存できます。")
    return 0


def write_unsubscribe_report(path: str, index: dict[str, dict]) -> None:
    lines: list[str] = ["# メルマガ解除リンク一覧", ""]
    lines.append(f"対象送信者数: **{len(index)}**")
    lines.append("")
    lines.append("> ヒント: `mailto:` は送信するだけで解除完了することが多い (件名/本文はそのまま送信)。")
    lines.append("> `one-click=true` の表記がある場合は、URL を 1 回開くだけで解除されます。")
    lines.append("")
    for sender in sorted(index.keys(), key=str.lower):
        entry = index[sender]
        lines.append(f"## {sender}")
        if entry["one_click"]:
            lines.append("- one-click 対応 ✅")
        for url in sorted(entry["urls"]):
            lines.append(f"- 解除URL: <{url}>")
        for mt in sorted(entry["mailtos"]):
            lines.append(f"- 解除メール: `{mt}`")
        if entry["subjects"]:
            lines.append("- 直近の件名:")
            for s in sorted(entry["subjects"]):
                lines.append(f"  - {s}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
