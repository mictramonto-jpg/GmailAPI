"""Gmail Organizer ローカルサーバー版

Flask で localhost:5000 にダッシュボードを立てる。GAS 版と同等の機能を
あなたの PC 上で完結させる。

使い方:
    python local_server.py
    → ブラウザで http://localhost:5000 を開く

設定/状態の保存先:
    .state/settings.json   設定 (LLM プロバイダ、ホワイトリストなど)
    .state/cache.json      LLM 結果キャッシュ (送信者単位、30 日 TTL)
    rules.yaml             ルール (gmail_organizer.py と共通)
    token.json             Gmail OAuth トークン (gmail_organizer.py と共通)
"""
from __future__ import annotations

import json
import os
import re
import time
import webbrowser
from collections import Counter
from typing import Optional

from flask import Flask, jsonify, render_template, request

from gmail_organizer import (
    SCOPES,
    Rule,
    _extract_body,
    _header,
    classify as classify_rule,
    get_service,
    list_message_ids,
    load_rules,
    normalize_sender,
    parse_list_unsubscribe,
    sender_domain,
)
from llm_providers import classify as llm_classify

STATE_DIR = ".state"
SETTINGS_PATH = os.path.join(STATE_DIR, "settings.json")
CACHE_PATH = os.path.join(STATE_DIR, "cache.json")
CACHE_TTL = 30 * 24 * 60 * 60  # 30 日

DEFAULT_SETTINGS = {
    "query": "in:inbox newer_than:7d",
    "max_messages": 200,
    "llm_provider": "none",       # none | gemini | claude
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "claude_api_key": "",
    "claude_model": "claude-opus-4-7",
    "review_label": "Org/Review",
    "unwanted_label": "Org/Unwanted",
    "whitelist": "",
    "credentials_path": "credentials.json",
    "token_path": "token.json",
    "rules_path": "rules.yaml",
}

app = Flask(__name__)


# ---------- 永続化 ----------

def _ensure_state_dir() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)


def load_settings() -> dict:
    _ensure_state_dir()
    if not os.path.exists(SETTINGS_PATH):
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT_SETTINGS, **data}
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    _ensure_state_dir()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    _ensure_state_dir()
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def cache_key(provider: str, model: str, sender: str) -> str:
    return f"{provider}:{model}:{(sender or '').lower()}"


def get_cached(provider: str, model: str, sender: str) -> Optional[dict]:
    if not sender:
        return None
    cache = load_cache()
    entry = cache.get(cache_key(provider, model, sender))
    if not entry:
        return None
    if entry.get("ts", 0) + CACHE_TTL < time.time():
        return None
    return entry


def put_cached(provider: str, model: str, sender: str, decision: dict) -> None:
    if not sender or not decision:
        return
    cache = load_cache()
    cache[cache_key(provider, model, sender)] = {**decision, "ts": time.time()}
    # 古いエントリ掃除 + 上限
    now = time.time()
    cache = {k: v for k, v in cache.items() if v.get("ts", 0) + CACHE_TTL >= now}
    if len(cache) > 1000:
        items = sorted(cache.items(), key=lambda x: x[1].get("ts", 0))
        cache = dict(items[-1000:])
    save_cache(cache)


# ---------- ホワイトリスト ----------

def is_whitelisted(sender_addr: str, settings: dict) -> bool:
    text = settings.get("whitelist") or ""
    if not text or not sender_addr:
        return False
    lower = sender_addr.lower()
    dom = sender_domain(lower)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("/") and line.rfind("/") > 0:
            last = line.rfind("/")
            pattern = line[1:last]
            flags = line[last + 1:] or "i"
            try:
                if re.search(pattern, lower, re.IGNORECASE if "i" in flags else 0):
                    return True
            except re.error:
                pass
            continue
        norm = line.lower().lstrip("@")
        if "@" in norm:
            if norm == lower:
                return True
        elif norm == dom:
            return True
    return False


# ---------- ラベル ----------

class LabelCache:
    def __init__(self, service):
        self.service = service
        self._by_name: dict[str, str] = {}
        for lbl in service.users().labels().list(userId="me").execute().get("labels", []):
            self._by_name[lbl["name"]] = lbl["id"]

    def ensure(self, name: str) -> str:
        if name in self._by_name:
            return self._by_name[name]
        body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        created = self.service.users().labels().create(userId="me", body=body).execute()
        self._by_name[name] = created["id"]
        return created["id"]


def apply_action(service, msg_id: str, action: dict, label_cache: LabelCache, dry_run: bool) -> str:
    parts: list[str] = []
    add_label_ids: list[str] = []
    remove_label_ids: list[str] = []
    label = action.get("label")
    if label:
        parts.append(f"+{label}")
        if not dry_run:
            add_label_ids.append(label_cache.ensure(label))
    if action.get("archive"):
        parts.append("archive")
        remove_label_ids.append("INBOX")
    if action.get("mark_read"):
        parts.append("read")
        remove_label_ids.append("UNREAD")
    if action.get("trash"):
        parts.append("TRASH")
    summary = ",".join(parts) or "(no-op)"
    if dry_run:
        return summary
    if action.get("trash"):
        service.users().messages().trash(userId="me", id=msg_id).execute()
        return summary
    if add_label_ids or remove_label_ids:
        service.users().messages().modify(
            userId="me", id=msg_id,
            body={"addLabelIds": add_label_ids, "removeLabelIds": remove_label_ids},
        ).execute()
    return summary


# ---------- 実行 ----------

def _gmail_service(settings: dict):
    return get_service(settings["credentials_path"], settings["token_path"])


def _run_classification(query: str, max_n: int, dry_run: bool) -> dict:
    settings = load_settings()
    rules, default_label = load_rules(settings["rules_path"])
    service = _gmail_service(settings)
    label_cache = LabelCache(service)
    provider = settings["llm_provider"]
    use_llm = (provider == "gemini" and settings.get("gemini_api_key")) \
           or (provider == "claude" and settings.get("claude_api_key"))
    model = settings.get(f"{provider}_model", "") if provider in ("gemini", "claude") else ""

    msg_ids = list_message_ids(service, query, max_n)
    counts: Counter = Counter()
    previews: list[dict] = []
    unsub_index: dict[str, dict] = {}

    for mid in msg_ids:
        msg = service.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post"],
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        from_ = _header(headers, "From")
        subject = _header(headers, "Subject")
        list_unsub = _header(headers, "List-Unsubscribe")
        sender_addr = normalize_sender(from_)

        # ホワイトリスト
        if is_whitelisted(sender_addr, settings):
            counts["Whitelist (skipped)"] += 1
            previews.append({"from": from_, "subject": subject, "rule": "Whitelist",
                             "action": "(no-op)", "llm": False})
            continue

        # ルール照合
        rule = classify_rule(msg, rules)
        rule_name = rule.name if rule else None
        action_dict = None
        llm_used = False
        cache_hit = False

        if rule:
            action_dict = {
                "label": rule.label, "archive": rule.archive,
                "mark_read": rule.mark_read, "trash": rule.trash,
            }
        elif use_llm:
            decision = get_cached(provider, model, sender_addr)
            if decision:
                cache_hit = True
            else:
                ctx = {"from": from_, "subject": subject, "list_unsubscribe": list_unsub}
                decision = llm_classify(provider, ctx, settings)
                if decision:
                    put_cached(provider, model, sender_addr, decision)
            if decision:
                action_dict = decision
                llm_used = True
                rule_name = f"{provider}: {decision['category']}" + (" (cached)" if cache_hit else "")

        if not action_dict and default_label:
            action_dict = {"label": default_label, "archive": False, "mark_read": False, "trash": False}
            rule_name = "(default)"

        if not action_dict:
            counts["__skip__"] += 1
            continue

        summary = apply_action(service, mid, action_dict, label_cache, dry_run)
        counts[rule_name or "(unknown)"] += 1
        if len(previews) < 100:
            previews.append({
                "from": from_, "subject": subject, "rule": rule_name or "(default)",
                "action": summary, "llm": llm_used,
                "provider": provider if llm_used else "",
            })

        # Unsubscribe 集約
        if list_unsub:
            urls, mailtos = parse_list_unsubscribe(list_unsub)
            entry = unsub_index.setdefault(sender_addr, {
                "subjects": set(), "urls": set(), "mailtos": set(), "one_click": False,
            })
            entry["subjects"].add(subject[:80])
            entry["urls"].update(urls)
            entry["mailtos"].update(mailtos)
            if "one-click" in (_header(headers, "List-Unsubscribe-Post") or "").lower():
                entry["one_click"] = True

    unsub_list = [
        {
            "sender": s, "one_click": e["one_click"],
            "urls": sorted(e["urls"]), "mailtos": sorted(e["mailtos"]),
            "subjects": sorted(e["subjects"]),
        }
        for s, e in sorted(unsub_index.items(), key=lambda x: -len(x[1]["subjects"]))
    ]
    return {
        "query": query, "total": len(msg_ids), "dry_run": dry_run,
        "counts": dict(counts), "previews": previews, "unsubscribe": unsub_list,
    }


def _collect_stats(query: str, max_n: int) -> dict:
    settings = load_settings()
    service = _gmail_service(settings)
    msg_ids = list_message_ids(service, query, max_n)
    sender_count: Counter = Counter()
    domain_count: Counter = Counter()
    unsub_count: Counter = Counter()
    for mid in msg_ids:
        msg = service.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "List-Unsubscribe"],
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        sender = normalize_sender(_header(headers, "From"))
        if not sender:
            continue
        sender_count[sender] += 1
        domain_count[sender_domain(sender)] += 1
        if _header(headers, "List-Unsubscribe"):
            unsub_count[sender] += 1
    top = lambda c, n: [{"key": k, "count": v} for k, v in c.most_common(n)]
    senders_top = top(sender_count, 20)
    for s in senders_top:
        s["isPromo"] = s["key"] in unsub_count
    return {
        "query": query, "total": len(msg_ids),
        "uniqueSenders": len(sender_count),
        "uniqueDomains": len(domain_count),
        "promoSenders": len(unsub_count),
        "topSenders": senders_top,
        "topDomains": top(domain_count, 20),
        "topPromo": top(unsub_count, 20),
    }


# ---------- ルート ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    if request.method == "POST":
        s = load_settings()
        s.update(request.json or {})
        save_settings(s)
    return jsonify(load_settings())


@app.route("/api/rules", methods=["GET", "POST"])
def api_rules():
    settings = load_settings()
    path = settings["rules_path"]
    if request.method == "POST":
        body = request.data.decode("utf-8")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return jsonify({"ok": True})
    if not os.path.exists(path):
        return ("", 404)
    with open(path, encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/run", methods=["POST"])
def api_run():
    body = request.json or {}
    settings = load_settings()
    query = body.get("query") or settings["query"]
    max_n = int(body.get("max") or settings["max_messages"])
    dry_run = bool(body.get("dry_run"))
    return jsonify(_run_classification(query, max_n, dry_run))


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    body = request.json or {}
    settings = load_settings()
    query = body.get("query") or settings["query"]
    max_n = int(body.get("max") or settings["max_messages"])
    return jsonify(_collect_stats(query, max_n))


@app.route("/api/cache", methods=["GET", "DELETE"])
def api_cache():
    if request.method == "DELETE":
        save_cache({})
        return jsonify({"cleared": True})
    cache = load_cache()
    by_provider: Counter = Counter()
    for k in cache.keys():
        by_provider[k.split(":")[0]] += 1
    return jsonify({"total": len(cache), "byProvider": dict(by_provider)})


@app.route("/api/test_llm", methods=["POST"])
def api_test_llm():
    body = request.json or {}
    settings = load_settings()
    provider = body.get("provider", "gemini")
    ctx = {
        "from": body.get("from", "newsletter@shop.example"),
        "subject": body.get("subject", "【春のセール】最大50%OFF"),
        "list_unsubscribe": "",
    }
    return jsonify(llm_classify(provider, ctx, settings) or {"error": "failed"})


def main():
    print("Gmail Organizer (ローカルサーバー版)")
    print("=" * 50)
    settings = load_settings()
    if not os.path.exists(settings["credentials_path"]):
        print(f"\n⚠ {settings['credentials_path']} が見つかりません。")
        print("  README の手順で OAuth credentials.json を取得して配置してください。")
    if not os.path.exists(settings["rules_path"]):
        print(f"\n⚠ {settings['rules_path']} が見つかりません。")
        print(f"  cp rules.example.yaml {settings['rules_path']} で雛形をコピーしてください。")
    print("\nブラウザを自動で開きます: http://localhost:5000")
    print("停止するには Ctrl+C\n")
    try:
        webbrowser.open("http://localhost:5000")
    except Exception:
        pass
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
