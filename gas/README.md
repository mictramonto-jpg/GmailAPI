# Gmail Organizer (Google Apps Script 版)

ブラウザだけで動く Gmail 自動仕分けシステム。**Python・PowerShell・credentials.json は不要**。

## 主な機能

- 📊 受信トレイ分析 (送信者・ドメイン・メルマガ送信者の TOP20)
- 📋 ルールベース仕分け (JSON でルール編集、ラベル付与・アーカイブ・既読化)
- 🤖 **Gemini API による LLM 分類** (ルールに当てはまらないメールを「必要・通知・不要」に判定)
- 🔕 メルマガ解除リンクを送信者ごとに集約 (one-click 表示・mailto 対応)
- ⏰ 1 時間ごとに自動実行 (PC を起動していなくても OK)
- 📱 Web UI でスマホからもルール編集・実行可能

---

## ファイル構成

| ファイル | 役割 |
|---|---|
| `appsscript.json` | マニフェスト (Gmail Advanced Service + スコープ) |
| `Code.gs` | UI ラッパー + 自動実行トリガ管理 |
| `Rules.gs` | デフォルトルール + 設定永続化 |
| `Classifier.gs` | ヘッダ解析 + ルール照合 + LLM フォールバック |
| `Gemini.gs` | Gemini API クライアント |
| `Claude.gs` | Claude API クライアント (Anthropic) |
| `Web.gs` | `doGet` Web エントリ |
| `ui/Index.html` | タブ式ダッシュボード |

## デプロイ手順 (約 5 分)

### Step 1: Apps Script プロジェクトを作る

1. <https://script.google.com/> にアクセス (Gmail と同じアカウントで)
2. 左上の **「+ 新しいプロジェクト」**
3. 「無題のプロジェクト」をクリックして名前を **`Gmail Organizer`** などに変更

### Step 2: ファイルを 5 つ追加する

GAS エディタは初期状態で `Code.gs` が 1 つあります。これを書き換え + ファイル追加で計 5 つにします。

#### 2-1. `Code.gs` を書き換え

このリポジトリの `gas/Code.gs` の中身を全コピペ → エディタの `Code.gs` を全置換。

#### 2-2. その他のファイルを追加

エディタ左の **`+` ボタン → 「スクリプト」** で以下を追加 (拡張子 `.gs` は自動付与なので名前のみ入力):

| ファイル名 | コピー元 |
|---|---|
| `Rules` | `gas/Rules.gs` |
| `Classifier` | `gas/Classifier.gs` |
| `Gemini` | `gas/Gemini.gs` |
| `Claude` | `gas/Claude.gs` |
| `Web` | `gas/Web.gs` |

#### 2-3. HTML ファイルを追加

エディタ左の **`+` ボタン → 「HTML」** で以下を追加:

| ファイル名 | コピー元 |
|---|---|
| `ui/Index` (フォルダ感覚で `/` 含めて入力) | `gas/ui/Index.html` |

> ⚠️ HTML ファイル名は **`ui/Index`** と入力してください (拡張子 `.html` は自動)。
> 通常の名前 `Index` だけだと `Web.gs` の `createTemplateFromFile('ui/Index')` とパスがズレます。
> どうしてもエラーが出る場合は `Web.gs` の `'ui/Index'` を `'Index'` に書き換え + ファイル名も `Index` に。

#### 2-4. マニフェストを編集 (重要)

エディタ左の **歯車 ⚙ アイコン (プロジェクトの設定)** → **「`appsscript.json` マニフェスト ファイルをエディタで表示する」** にチェック。

→ 左ペインに `appsscript.json` が現れるので、その中身を `gas/appsscript.json` の内容で全置換。

これで Gmail Advanced Service と必要なスコープが有効化されます。

### Step 3: 保存して権限を承認

1. **💾 保存** (Ctrl+S)
2. 関数選択ドロップダウンで **`uiGetSettings`** を選び **▶ 実行**
3. 「承認が必要です」ダイアログ → **「権限を確認」**
4. アカウント選択 → **「Google hasn't verified this app」** 警告
   → **「詳細」 → 「(プロジェクト名) に移動 (安全ではない)」**
5. 表示されるスコープ一覧 (Gmail 変更、外部 URL 取得、トリガ作成) → **「許可」**

承認は最初の 1 回だけ。

### Step 4: Web アプリとしてデプロイ

1. 右上の **「デプロイ」 → 「新しいデプロイ」**
2. 種類のアイコン (歯車) → **「ウェブアプリ」** を選択
3. 設定:
   - 説明: `v1` など任意
   - 次のユーザーとして実行: **自分**
   - アクセスできるユーザー: **自分のみ**
4. **「デプロイ」** → 「ウェブアプリ URL」をコピー & ブックマーク

→ そのURLを開けばダッシュボードが表示されます。

---

## 使い方

### 初回

1. 開いたら **「⚙️ 設定」タブ** で:
   - デフォルトクエリ・ラベル名を確認 (そのままで OK)
   - **Gemini を使う場合** は API キーを入れて「テスト」ボタンで確認
   - 「💾 設定を保存」
2. **「📋 ルール」タブ** で必要に応じてルールを編集 (デフォルトのままでも動く)
3. **「▶️ 実行」タブ** で:
   - 📊 **分析** → 送信者統計を表示
   - 👀 **ドライラン** → 適用せず仕分け結果プレビュー
   - ✅ **本番適用** → 実際にラベル付与・アーカイブ
4. **「🔕 解除リンク」タブ** に集約された URL から順次解除

### 自動化

「⚙️ 設定」 → **「⏰ 自動実行を有効化」** ボタンで毎時の自動仕分けが ON になります。
以降、PC を起動していなくてもクラウドで自動実行されます。

ヘッダ右の `⏰ 自動実行: ON` 表示で状態が分かります。

---

## LLM プロバイダの取得 (任意)

LLM 分類を使う場合のみ。設定タブのプロバイダで「Gemini」または「Claude」を選択。

### Gemini (Google・無料枠あり)

1. <https://aistudio.google.com/app/apikey> にアクセス
2. 「+ Create API key」 → API キーが発行される (`AIza...`)
3. 「⚙️ 設定」 → プロバイダ「Gemini」 → API Key に貼り付け
4. 「💾 設定を保存」 → 「🔍 テスト」で動作確認

**無料枠**: `gemini-2.5-flash` で 1 日 1500 リクエスト程度。個人 Gmail なら無料に収まる。

### Claude (Anthropic・高精度)

1. <https://console.anthropic.com/> にアクセス → アカウント作成
2. 課金設定で **$5 以上**チャージ (クレカ登録要)
3. <https://console.anthropic.com/settings/keys> で 「Create Key」 → `sk-ant-...` を発行
4. 「⚙️ 設定」 → プロバイダ「Claude」 → API Key に貼り付け
5. モデル選択:
   - **`claude-opus-4-7`** (最高精度・$5 / $25 per 1M tokens) — 既定
   - **`claude-sonnet-4-6`** (中間・$3 / $15)
   - **`claude-haiku-4-5`** (最安・$1 / $5・分類タスクには十分)
6. 「💾 設定を保存」 → 「🔍 テスト」で動作確認

> ⚠️ Claude API は無料枠なし。コスト試算は次セクション参照。

---

## トークン使用量とコスト目安

LLM 分類は **ルールにマッチしなかったメール** にだけ呼ばれます。
ルールで処理されたメールには 1 トークンも使いません。

### 1 通あたりの想定トークン

| 内訳 | トークン |
|---|---|
| 入力 (system + From + Subject + List-Unsubscribe フラグ) | ~250 |
| 出力 (JSON: `{category, reason}`) | ~30 |
| **合計** | **~280** |

### 月額シミュレーション

毎日 **100 通の未マッチメール** が LLM に流れる前提 (一般的な個人利用):

| プロバイダ・モデル | 入力単価 | 出力単価 | 1 通 | 1 日 | **1 ヶ月** |
|---|---|---|---|---|---|
| **Gemini 2.5 Flash** | 無料枠内 | 無料枠内 | 0 円 | 0 円 | **0 円** (※) |
| **Claude Haiku 4.5** | $1.00 / 1M | $5.00 / 1M | $0.0004 | $0.04 | **約 $1.20 (180円)** |
| **Claude Sonnet 4.6** | $3.00 / 1M | $15.00 / 1M | $0.0012 | $0.12 | **約 $3.60 (540円)** |
| **Claude Opus 4.7** | $5.00 / 1M | $25.00 / 1M | $0.0020 | $0.20 | **約 $6.00 (900円)** |

(※) Gemini Flash は 1 日 1500 リクエストまで無料。100 通なら大幅に余裕あり。

毎日 **1000 通** を LLM 分類する重い使い方の場合:

| プロバイダ・モデル | **1 ヶ月** |
|---|---|
| Gemini 2.5 Flash | 約 $0.84 (130円) ※無料枠 1500/日を超えた分の課金 |
| Claude Haiku 4.5 | 約 $12 (1,800円) |
| Claude Sonnet 4.6 | 約 $36 (5,400円) |
| Claude Opus 4.7 | 約 $60 (9,000円) |

### コスト最適化のヒント

1. **ルールを充実させる** — メルマガなど典型的なメールはルールで処理し、LLM は本当に判別困難なメールだけに使う
2. **クエリを絞る** — `newer_than:7d` より `newer_than:1h`、自動実行は短い間隔で少量ずつ
3. **モデル選択** — 件名+送信者だけの 2 値分類なら **Haiku 4.5 で十分**。Opus は判別が難しいメールが多い場合
4. **Gemini Flash 推奨** — まずは無料の Gemini で運用、限界を感じたら Claude へ

---

---

## ルール JSON の書き方

```json
{
  "defaultLabel": "Org/Review",
  "rules": [
    {
      "name": "請求・支払い",
      "match": { "subject": "(invoice|請求|支払|領収)" },
      "action": { "label": "Org/Bills", "archive": true }
    },
    {
      "name": "メルマガ全般",
      "match": { "hasListUnsubscribe": true },
      "action": { "label": "Org/Unwanted", "archive": true, "markRead": true }
    }
  ]
}
```

| match キー | 意味 |
|---|---|
| `from` | 送信者 (正規表現、例: `@github\\.com$`) |
| `subject` | 件名 (正規表現) |
| `hasListUnsubscribe` | true でメルマガ限定、false で除外 |

| action キー | 意味 |
|---|---|
| `label` | 付与するラベル名 (`/` でネスト可。なければ自動作成) |
| `archive` | true で受信トレイから外す |
| `markRead` | true で既読化 |
| `trash` | true でゴミ箱送り (※非推奨) |

---

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `TypeError: Cannot read properties of null (reading 'getBlob')` | HTML ファイル名が `ui/Index` になっているか確認 |
| `ReferenceError: Gmail is not defined` | `appsscript.json` で Gmail Advanced Service を有効化 (Step 2-4) |
| `403 ACCESS_TOKEN_SCOPE_INSUFFICIENT` | スクリプトを再保存 → 関数を 1 回手動実行して権限再承認 |
| Gemini テストで失敗 | API キーを確認、`AIza` で始まる文字列か |
| 自動実行が動かない | 設定タブで「⏰ 自動実行を有効化」を再度クリック |

---

## clasp でローカル開発する (任意)

Node.js が入っていれば、ブラウザ編集の代わりに CLI で push できます:

```bash
npm install -g @google/clasp
cd gas/
clasp login
clasp create --type webapp --title "Gmail Organizer"
clasp push
clasp deploy
```

詳細は <https://github.com/google/clasp> を参照。
