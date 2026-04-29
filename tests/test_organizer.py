"""gmail_organizer の API 非依存ロジックのユニットテスト。

実行: python -m pytest tests/  (pytest)  または  python -m unittest tests.test_organizer
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmail_organizer import (  # noqa: E402
    Rule,
    classify,
    generate_rules_yaml,
    InboxStats,
    load_rules,
    match_rule,
    normalize_sender,
    parse_list_unsubscribe,
    sender_domain,
)
from collections import Counter  # noqa: E402


def make_msg(headers: dict, body: str = "") -> dict:
    """ヘッダ dict から Gmail API 風の message オブジェクトを作る。"""
    payload_headers = [{"name": k, "value": v} for k, v in headers.items()]
    return {"payload": {"headers": payload_headers, "mimeType": "text/plain"}}


class TestSenderHelpers(unittest.TestCase):
    def test_normalize_sender_with_name(self):
        self.assertEqual(normalize_sender("Foo Bar <Foo@Example.COM>"), "foo@example.com")

    def test_normalize_sender_bare(self):
        self.assertEqual(normalize_sender("foo@example.com"), "foo@example.com")

    def test_normalize_sender_empty(self):
        self.assertEqual(normalize_sender(""), "")
        self.assertEqual(normalize_sender(None), "")

    def test_sender_domain(self):
        self.assertEqual(sender_domain("foo@example.com"), "example.com")
        self.assertEqual(sender_domain("noatsign"), "noatsign")


class TestParseListUnsubscribe(unittest.TestCase):
    def test_url_and_mailto(self):
        urls, mailtos = parse_list_unsubscribe(
            "<https://example.com/unsub?x=1>, <mailto:unsub@example.com?subject=unsubscribe>"
        )
        self.assertEqual(urls, ["https://example.com/unsub?x=1"])
        self.assertEqual(mailtos, ["mailto:unsub@example.com?subject=unsubscribe"])

    def test_only_mailto(self):
        urls, mailtos = parse_list_unsubscribe("<mailto:u@x.com>")
        self.assertEqual(urls, [])
        self.assertEqual(mailtos, ["mailto:u@x.com"])

    def test_empty(self):
        self.assertEqual(parse_list_unsubscribe(""), ([], []))
        self.assertEqual(parse_list_unsubscribe(None), ([], []))


class TestMatchRule(unittest.TestCase):
    def _rule(self, **kw):
        defaults = dict(
            name="t", from_re=None, subject_re=None, body_re=None,
            has_list_unsubscribe=None, label=None,
            archive=False, mark_read=False, trash=False,
        )
        defaults.update(kw)
        return Rule(**defaults)

    def test_from_match(self):
        msg = make_msg({"From": "noreply@github.com", "Subject": "PR opened"})
        rule = self._rule(from_re=re.compile(r"@github\.com$", re.IGNORECASE))
        self.assertTrue(match_rule(msg, rule))

    def test_from_nomatch(self):
        msg = make_msg({"From": "noreply@gitlab.com", "Subject": "PR opened"})
        rule = self._rule(from_re=re.compile(r"@github\.com$", re.IGNORECASE))
        self.assertFalse(match_rule(msg, rule))

    def test_and_semantics(self):
        """from と subject 両方が AND で評価されること。"""
        msg = make_msg({"From": "boss@example.com", "Subject": "請求書 2026/04"})
        rule_match = self._rule(
            from_re=re.compile(r"@example\.com$", re.IGNORECASE),
            subject_re=re.compile(r"請求", re.IGNORECASE),
        )
        rule_partial = self._rule(
            from_re=re.compile(r"@example\.com$", re.IGNORECASE),
            subject_re=re.compile(r"領収", re.IGNORECASE),
        )
        self.assertTrue(match_rule(msg, rule_match))
        self.assertFalse(match_rule(msg, rule_partial))

    def test_list_unsubscribe_required(self):
        with_unsub = make_msg({"From": "x@y.com", "List-Unsubscribe": "<https://y.com/u>"})
        without = make_msg({"From": "x@y.com"})
        rule = self._rule(has_list_unsubscribe=True)
        self.assertTrue(match_rule(with_unsub, rule))
        self.assertFalse(match_rule(without, rule))

    def test_list_unsubscribe_excluded(self):
        with_unsub = make_msg({"From": "x@y.com", "List-Unsubscribe": "<https://y.com/u>"})
        rule = self._rule(has_list_unsubscribe=False)
        self.assertFalse(match_rule(with_unsub, rule))


class TestClassify(unittest.TestCase):
    def test_first_match_wins(self):
        rules = [
            Rule("bills", None, re.compile(r"請求"), None, None, "Org/Bills", True, False, False),
            Rule("any-unsub", None, None, None, True, "Org/Unwanted", True, True, False),
        ]
        msg = make_msg({"Subject": "請求書", "List-Unsubscribe": "<https://x/u>"})
        # 1 件目 (bills) にマッチするので 2 件目には行かない
        self.assertEqual(classify(msg, rules).name, "bills")

    def test_no_match_returns_none(self):
        rules = [Rule("bills", None, re.compile(r"請求"), None, None, "Org/Bills", True, False, False)]
        msg = make_msg({"Subject": "Hi"})
        self.assertIsNone(classify(msg, rules))


class TestLoadRules(unittest.TestCase):
    def test_roundtrip(self):
        yaml_text = """
default_label: "Org/Review"
rules:
  - name: "GitHub"
    match:
      from: "@github\\\\.com$"
    action:
      label: "Org/GitHub"
      archive: true
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_text)
            path = f.name
        try:
            rules, default_label = load_rules(path)
            self.assertEqual(default_label, "Org/Review")
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].name, "GitHub")
            self.assertTrue(rules[0].archive)
            self.assertIsNotNone(rules[0].from_re)
        finally:
            os.unlink(path)


class TestGenerateRulesYaml(unittest.TestCase):
    def test_includes_top_unwanted_senders(self):
        stats = InboxStats(
            sender_count=Counter({"a@x.com": 5, "b@y.com": 3}),
            domain_count=Counter({"x.com": 5, "y.com": 3}),
            unsub_sender_count=Counter({"news@shop.example": 12, "ad@store.example": 7}),
            promo_count=19,
        )
        out = generate_rules_yaml(stats)
        self.assertIn("news@shop.example", out)
        self.assertIn("ad@store.example", out)
        self.assertIn("Org/Unwanted", out)
        self.assertIn("has_list_unsubscribe: true", out)

    def test_no_unsub_still_generates(self):
        stats = InboxStats(Counter(), Counter(), Counter(), 0)
        out = generate_rules_yaml(stats)
        self.assertIn("default_label", out)
        self.assertIn("rules:", out)


if __name__ == "__main__":
    unittest.main()
