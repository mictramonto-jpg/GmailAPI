# Gmail Organizer — 仕様書

Gmail を自動仕分けする 3 通りの実装をまとめたプロジェクト。本書はこれまでの会話で決まった
仕様・設計判断を一箇所に集約したリファレンスです。

---

## 0. プロジェクト概要

**目的**: Gmail に届くメールをグループ分けし、必要/不要を判別、必要なものはラベル分け、
不要なものはアーカイブ + メルマガ解除リンクを集約。

**設計方針**:
- ルールベース (YAML/JSON) で 90% を捌く
- 残りのグレーゾーンを LLM (Gemini / Claude) で判別
- LLM 結果は送信者単位でキャッシュして API コスト削減
- ホワイトリストで重要送信者は絶対に仕分け対象外

---

## 1. 3 つの実装

| # | 実装 | エントリ | 場所 | 自動実行 | 推奨 |
|---|---|---|---|---|---|
| A | **CLI 版** | `gmail_organizer.py` | ローカル | cron / タスクスケジューラ | パイプライン組みたい人 |
| B | **ローカルサーバー版** | `local_server.py` | ローカル | PC 起動中のみ | プライバシー重視・**今のあなた** |
| C | **GAS Web アプリ版** | `gas/` | Google クラウド | 標準で毎時自動 | PC オフでも動かしたい人 |

3 つは独立していて、好きな組合せで使える (例: B でルール調整 → C でデプロイ)。

---

## 2. 機能一覧 (3 版すべて共通)

- 📊 **分析モード**: 送信者・ドメイン・メルマガ送信者の TOP20
- 📋 **ルール仕分け**: 正規表現マッチでラベル付与・アーカイブ・既読化
- ⭐ **ホワイトリスト**: 重要送信者を仕分け対象外に (B/C のみ)
- 🤖 **LLM 分類**: Gemini / Claude 切替可。「必要 / 通知 / 不要」を判定
- 💾 **LLM キャッシュ**: 同じ送信者を 30 日間再分類しない (B/C のみ)
- 🔕 **解除リンク集約**: 送信者ごとに URL/mailto/one-click 表示
- 🌐 **一括タブオープン**: 全解除 URL を順次オープン (B/C のみ)
- ⏰ **自動実行**: 毎時自動仕分け (C のみ標準対応、A/B は別途設定)

---

## 3. ファイル構成

```
GmailAPI/
├── README.md                  3 版の概観と開始方法
├── SPECIFICATION.md           本書
├── requirements.txt           Python 依存 (CLI + ローカルサーバー)
├── package.json               clasp 用 (GAS デプロイ自動化)
├── rules.example.yaml         ルールサンプル
├── credentials.json           ★ OAuth クライアント JSON (gitignore 済)
├── token.json                 ★ アクセストークン (gitignore 済)
├── rules.yaml                 ★ あなたのルール (gitignore 済)
│
├── gmail_organizer.py         A. CLI 本体
├── local_server.py            B. ローカル Flask サーバー
├── llm_providers.py           B で使う LLM クライアント
├── templates/
│   └── index.html             B のダッシュボード UI
├── tests/
│   └── test_organizer.py      A の単体テスト
│
└── gas/                       C. GAS 版
    ├── appsscript.json        マニフェスト
    ├── Code.gs                エントリ + トリガ管理
    ├── Rules.gs               設定永続化 + デフォルトルール
    ├── Classifier.gs          ヘッダ解析 + 分類 + ホワイトリスト
    ├── Cache.gs               LLM 結果キャッシュ
    ├── Gemini.gs              Gemini API クライアント
    ├── Claude.gs              Claude API クライアント
    ├── Web.gs                 doGet エントリ
    ├── ui/Index.html          ダッシュボード UI
    ├── README.md              GAS デプロイ手順
    └── .clasp.json.example    clasp 設定テンプレ
```

★ がついた 3 ファイルはマシン固有・秘密情報のため絶対にコミットしない。

---

## 4. Gmail API の取得 (A/B 共通・C は不要)

| ステップ | 内容 |
|---|---|
| 1 | <https://console.cloud.google.com/> で新規プロジェクト |
| 2 | 「API とサービス」→「ライブラリ」→ **Gmail API** を有効化 |
| 3 | 「OAuth 同意画面」→ 外部 → テストユーザーに自分のメール追加 |
| 4 | 「認証情報」→「OAuth クライアント ID」→ **デスクトップアプリ** |
| 5 | JSON をダウンロード → `credentials.json` にリネームしてリポジトリ直下へ |

要求するスコープは `https://www.googleapis.com/auth/gmail.modify` のみ
(読む・ラベル変更・アーカイブ可能、完全削除不可の安全な権限)。

---

## 5. セットアップ (Mac / Windows 共通)

### 共通: リポジトリ取得

```bash
git clone https://github.com/mictramonto-jpg/GmailAPI.git
cd GmailAPI
git checkout claude/gmail-email-organization-gTvkF
```

### Python 仮想環境

| 操作 | Mac / Linux | Windows (PowerShell) |
|---|---|---|
| 仮想環境作成 | `python3 -m venv .venv` | `py -m venv .venv` |
| 有効化 | `source .venv/bin/activate` | `.\.venv\Scripts\Activate.ps1` |
| 依存インストール | `pip install -r requirements.txt` | 同左 |

> Windows で実行ポリシーエラーなら 1 回だけ:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### `credentials.json` の配置

| 操作 | Mac / Linux | Windows |
|---|---|---|
| 移動 | `mv ~/Downloads/client_secret_*.json ./credentials.json` | `Move-Item $HOME\Downloads\client_secret_*.json .\credentials.json` |
| 確認 | `ls credentials.json` | 同左 |

### ルール初期化

| 操作 | Mac / Linux | Windows |
|---|---|---|
| サンプルから作成 | `cp rules.example.yaml rules.yaml` | `copy rules.example.yaml rules.yaml` |

---

## 6. 起動 (各実装ごと)

### A. CLI 版

```bash
# 受信トレイを分析 (まずこれ)
python gmail_organizer.py --analyze --query "in:inbox newer_than:30d" --max 500

# 分析結果から rules.yaml を自動生成
python gmail_organizer.py --init --query "in:inbox newer_than:30d"

# ドライラン
python gmail_organizer.py --rules rules.yaml --query "in:inbox newer_than:7d" --dry-run

# 本番適用
python gmail_organizer.py --rules rules.yaml --query "in:inbox newer_than:7d"

# メルマガ解除リンク収集
python gmail_organizer.py --rules rules.yaml --query "in:inbox newer_than:30d" \
  --dry-run --unsubscribe-out unsubscribe.md
```

### B. ローカルサーバー版 (推奨・現在進行中の道)

```bash
python local_server.py
```

→ ブラウザが自動で <http://localhost:5000> を開く
→ 初回は OAuth 認証画面 → 「許可」
→ ダッシュボード (実行 / ルール / ホワイトリスト / 解除 / 設定) が表示
→ Ctrl+C で停止

### C. GAS Web アプリ版

詳細は `gas/README.md` 参照。要約:

| 方式 | 必要なもの | 手順 |
|---|---|---|
| clasp (推奨) | Node.js | `npm install && npm run create && npm run push && npm run deploy` |
| コピペ | ブラウザのみ | <https://script.google.com> で 8 ファイルを順に貼り付け |

`credentials.json` は不要 (GAS が直接 Gmail にアクセス)。

---

## 7. LLM プロバイダ比較

| プロバイダ・モデル | 入力単価 | 出力単価 | 1 通 | 月額 (100通/日) | 月額 (1000通/日) |
|---|---|---|---|---|---|
| Gemini 2.5 Flash | 無料枠 | 無料枠 | 0 円 | **0 円** (※) | 約 130 円 |
| Claude Haiku 4.5 | $1.00/1M | $5.00/1M | $0.0004 | 約 180 円 | 約 1,800 円 |
| Claude Sonnet 4.6 | $3.00/1M | $15.00/1M | $0.0012 | 約 540 円 | 約 5,400 円 |
| Claude Opus 4.7 | $5.00/1M | $25.00/1M | $0.0020 | 約 900 円 | 約 9,000 円 |

(※) Gemini Flash は 1 日 1500 リクエストまで無料。

**1 通あたり**: 入力 ~250 トークン + 出力 ~30 トークン = 約 280 トークン。
**重要**: LLM が呼ばれるのは **ルールにマッチしなかったメールだけ**。ルールで処理されたメール
は 1 トークンも消費しない。さらに送信者キャッシュで 2 回目以降はゼロ。

### LLM プロバイダ取得手順

| プロバイダ | URL | 必要 |
|---|---|---|
| Gemini | <https://aistudio.google.com/app/apikey> | Google アカウントのみ・無料 |
| Claude | <https://console.anthropic.com/settings/keys> | クレカ + $5 チャージ |

---

## 8. ルール定義 (YAML)

```yaml
default_label: "Org/Review"  # どのルールにもマッチしない場合

rules:
  - name: "請求・支払い"
    match:
      subject: "(invoice|請求|支払|領収)"   # 正規表現
    action:
      label: "Org/Bills"   # "/" でネスト可、無ければ自動作成
      archive: true
      mark_read: false

  - name: "GitHub 通知"
    match:
      from: "@github\\.com$"
    action:
      label: "Org/GitHub"
      archive: true

  - name: "ニュースレター全般"
    match:
      has_list_unsubscribe: true   # メルマガに限定
    action:
      label: "Org/Unwanted"
      archive: true
      mark_read: true
```

| match キー | 意味 |
|---|---|
| `from` | 送信者の正規表現 (大小区別なし) |
| `subject` | 件名の正規表現 |
| `body` | 本文の正規表現 (CLI 版のみ) |
| `has_list_unsubscribe` | true でメルマガ限定、false で除外 |

| action キー | 意味 |
|---|---|
| `label` | 付与ラベル名 |
| `archive` | true で受信トレイから外す |
| `mark_read` | true で既読化 |
| `trash` | true でゴミ箱送り (※非推奨) |

**評価順**: 上から順、最初にマッチしたルールだけ適用。

---

## 9. ホワイトリスト書式

```
# 行頭に # でコメント
foo@bar.com               # 完全一致
@yourcompany.co.jp        # ドメイン全体
/^boss.*@company\.jp$/i   # 正規表現 (大小区別なしフラグ i)
```

ここに登録された送信者からのメールは仕分け対象外 → 受信トレイに残る。

---

## 10. データ保存場所

### ローカル (CLI / B)

| ファイル | 内容 |
|---|---|
| `credentials.json` | OAuth クライアント (秘密) |
| `token.json` | アクセストークン (秘密) |
| `rules.yaml` | ルール |
| `.state/settings.json` | B の設定 |
| `.state/cache.json` | B の LLM キャッシュ |

### Google (GAS)

すべて `PropertiesService.getUserProperties()` に保存。設定・ルール・キャッシュ・ホワイトリスト
すべてユーザー単位で永続化。

---

## 11. 自動化 (オプション)

### A. CLI 版

**Mac / Linux (cron)**:
```bash
crontab -e
# 毎時実行
0 * * * * cd ~/GmailAPI && .venv/bin/python gmail_organizer.py --rules rules.yaml --query "newer_than:1h"
```

**Windows (タスクスケジューラ)**:
1. タスクスケジューラを起動
2. 「タスクの作成」→ トリガ「毎日 / 1 時間ごと繰り返し」
3. 操作: プログラム = `C:\Users\IHARA\GmailAPI\.venv\Scripts\python.exe`
4. 引数 = `gmail_organizer.py --rules rules.yaml --query "newer_than:1h"`
5. 開始 = `C:\Users\IHARA\GmailAPI`

### B. ローカルサーバー版

サーバーを常時起動するか、定期スクリプトで `local_server.py` の `_run_classification()` を直接呼ぶ。

### C. GAS 版

設定タブで「⏰ 自動実行を有効化」ボタンを押すだけ (毎時自動)。

---

## 12. セキュリティ・プライバシー注意事項

| 項目 | 対応 |
|---|---|
| `credentials.json` の `client_secret` | パスワード相当。誰にも見せない・コミットしない |
| `token.json` | あなたのアクセストークン。同上 |
| Gemini 無料枠の利用データ | 既定で Google のモデル改善に利用される可能性。気になるなら「Pay-as-you-go」プラン (使った分だけ課金、学習対象外) |
| Claude API | デフォルトで学習データに利用されない |
| LLM 送信内容 | 送信者・件名・List-Unsubscribe 有無のみ。本文は送らない |

---

## 13. トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| `python` コマンドで `Python` だけ返る | Microsoft Store スタブ。`py` を使うか、PATH を通した本物の Python をインストール |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` を 1 回 |
| `Access blocked: This app's request is invalid` | OAuth 同意画面のテストユーザーに自分のメール追加 |
| `redirect_uri_mismatch` | OAuth クライアントが「ウェブアプリ」になっている。「デスクトップアプリ」で作り直す |
| `invalid_grant` | `token.json` を削除して再認証 |
| 7 日でログインしなおし | OAuth 同意画面の公開ステータスを「本番環境」に変更 |
| GAS で `Gmail is not defined` | `appsscript.json` で Gmail Advanced Service を有効化 |
| GAS で 7 日でトークン失効 | OAuth 同意画面を「本番環境」に切替 |

---

## 14. ブランチ運用

すべての開発は `claude/gmail-email-organization-gTvkF` ブランチで進行。
最新を取得するには:

```bash
git checkout claude/gmail-email-organization-gTvkF
git pull
```

---

## 15. これまでの主要な決定事項

1. **Python 3.10+** (3.14 確認済み) で動作保証
2. **GAS クロスプラットフォーム** デプロイは `clasp` (npm) と手動コピペの 2 道
3. **デフォルト LLM プロバイダは「none」** (ルールだけで十分なケースが多い)
4. **Claude のデフォルトモデルは `claude-opus-4-7`** (Anthropic の推奨に準拠)
   - コスト重視なら UI で `claude-haiku-4-5` に切替可能
5. **ルール → LLM → デフォルトラベル** の三段優先順位
6. **ホワイトリスト最優先** (LLM もルールも無視)
7. **本文は LLM に送らない** (件名・送信者・ヘッダフラグのみ)
8. **`gmail.modify` スコープのみ** (完全削除権限は持たない)
9. **trash は非推奨** (`label + archive` で受信トレイから外すのが安全)

---

## 16. 開発コマンド集

### テスト実行
```bash
python -m unittest tests.test_organizer -v
```

### 構文チェックのみ
```bash
python -c "import ast; ast.parse(open('local_server.py').read()); print('OK')"
```

### Flask 開発サーバー (B)
```bash
python local_server.py
# → http://localhost:5000
```

### Git
```bash
git add .
git commit -m "..."
git push -u origin claude/gmail-email-organization-gTvkF
```
