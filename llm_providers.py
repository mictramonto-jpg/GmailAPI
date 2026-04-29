"""LLM プロバイダ抽象 (Gemini / Claude)。

ローカルサーバー版で使う。GAS 版の Gemini.gs / Claude.gs と同等の処理を Python で。
"""
from __future__ import annotations

import json
from typing import Optional

import requests

CATEGORY_MAP = {
    "Important":    {"label": "Org/Important",    "archive": False, "mark_read": False},
    "Notification": {"label": "Org/Notification", "archive": True,  "mark_read": False},
    "Unwanted":     {"label": "Org/Unwanted",     "archive": True,  "mark_read": True},
}


def _decision_from_category(category: str, reason: str) -> Optional[dict]:
    if category not in CATEGORY_MAP:
        return None
    return {**CATEGORY_MAP[category], "category": category, "reason": reason or ""}


def classify_with_gemini(ctx: dict, settings: dict) -> Optional[dict]:
    key = settings.get("gemini_api_key")
    if not key:
        return None
    model = settings.get("gemini_model", "gemini-2.5-flash")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    prompt = (
        "あなたは個人 Gmail の自動仕分けアシスタントです。\n"
        "以下の 1 通のメールを読み、必要 / 不要を判定し JSON で返答してください。\n\n"
        "判定基準:\n"
        "- 必要 (Important): 仕事の連絡、請求/支払、予約確認、配送通知、認証コード、個人的なやりとり\n"
        "- 通知 (Notification): SaaS の通知、GitHub/Jira などの自動配信\n"
        "- 不要 (Unwanted): セール/広告/メルマガ/プロモーション/リクルート営業\n\n"
        "メール:\n"
        f"From: {ctx.get('from', '')}\n"
        f"Subject: {ctx.get('subject', '')}\n"
        f"List-Unsubscribe: {'あり' if ctx.get('list_unsubscribe') else 'なし'}\n\n"
        "次の JSON スキーマで返答 (他の文字列を出さない):\n"
        '{"category": "Important|Notification|Unwanted", "reason": "短い理由"}'
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError):
        return None
    return _decision_from_category(parsed.get("category"), parsed.get("reason", ""))


def classify_with_claude(ctx: dict, settings: dict) -> Optional[dict]:
    key = settings.get("claude_api_key")
    if not key:
        return None
    model = settings.get("claude_model", "claude-opus-4-7")
    system = (
        "あなたは個人 Gmail の自動仕分けアシスタントです。判定基準:\n"
        "- 必要 (Important): 仕事の連絡、請求/支払、予約確認、配送通知、認証コード、個人的なやりとり\n"
        "- 通知 (Notification): SaaS の通知、GitHub/Jira などの自動配信\n"
        "- 不要 (Unwanted): セール/広告/メルマガ/プロモーション/リクルート営業"
    )
    user = (
        f"From: {ctx.get('from', '')}\n"
        f"Subject: {ctx.get('subject', '')}\n"
        f"List-Unsubscribe: {'あり' if ctx.get('list_unsubscribe') else 'なし'}"
    )
    payload = {
        "model": model,
        "max_tokens": 256,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["Important", "Notification", "Unwanted"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["category", "reason"],
                    "additionalProperties": False,
                },
            }
        },
    }
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=30,
        )
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    try:
        text = body["content"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError):
        return None
    return _decision_from_category(parsed.get("category"), parsed.get("reason", ""))


def classify(provider: str, ctx: dict, settings: dict) -> Optional[dict]:
    if provider == "gemini":
        return classify_with_gemini(ctx, settings)
    if provider == "claude":
        return classify_with_claude(ctx, settings)
    return None
