# Gmail Organizer

YAML ルールで Gmail を整理する Python スクリプト。

- 受信メールを **ラベル付与 + アーカイブ + 既読化** で自動仕分け
- メルマガなど **`List-Unsubscribe` ヘッダ付きメールの解除リンクを Markdown 一覧に出力**
- まずは `--dry-run` で結果確認 → 問題なければ実適用

---

## 1. Gmail API のセットアップ手順

Google Cloud で OAuth クライアントを作って `credentials.json` を取得します。

### Step 1: プロジェクト作成

1. <https://console.cloud.google.com/> にアクセス
2. 上部のプロジェクト選択ドロップダウン → **「新しいプロジェクト」**
3. プロジェクト名を入力 (例: `gmail-organizer`) → 作成

### Step 2: Gmail API を有効化

1. 左メニュー **「API とサービス」 → 「ライブラリ」**
2. 検索バーに `Gmail API` → 選択 → **「有効にする」**

### Step 3: OAuth 同意画面の設定

1. 左メニュー **「API とサービス」 → 「OAuth 同意画面」**
2. User Type: **外部 (External)** を選択 → 作成
3. 必須項目 (アプリ名・サポートメール・デベロッパー連絡先) を入力 → 保存
4. **「スコープ」** ステップは空のまま次へ (スクリプト側で要求するので不要)
5. **「テストユーザー」** に自分の Gmail アドレスを追加 → 保存
   - ※ 公開ステータスを「テスト」のままにすると 7 日でトークンが失効します。
     個人利用なら **「アプリを公開」→「公開ステータス: 本番環境 (Production)」** に変更すると失効しません
     (Google の検証は不要、自分だけが使うため)

### Step 4: OAuth クライアント ID を作成

1. 左メニュー **「API とサービス」 → 「認証情報」**
2. **「+ 認証情報を作成」 → 「OAuth クライアント ID」**
3. アプリケーションの種類: **「デスクトップ アプリ」**
4. 名前: `gmail-organizer-cli` など → 作成
5. 表示されるダイアログで **「JSON をダウンロード」**
6. ダウンロードしたファイルを **`credentials.json`** にリネームしてこのリポジトリ直下に置く

> ⚠️ `credentials.json` と後述の `token.json` は **絶対にコミットしない** こと
> (`.gitignore` で除外済み)

### Step 5: 必要なスコープ

スクリプトは `https://www.googleapis.com/auth/gmail.modify` を要求します。
これは **読む・ラベル変更・アーカイブ・ゴミ箱送り** ができるが、完全削除はできない権限です。

---

## 2. インストール & 初回認証

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ルールをコピーして編集
cp rules.example.yaml rules.yaml
$EDITOR rules.yaml   # 自分のドメインや好みに合わせて書き換え
```

初回実行時、ブラウザが立ち上がって Google ログイン → 同意画面 →
許可後にローカルの `token.json` が自動生成されます。以降は再ログイン不要。

---

## 3. 使い方

### まずはドライラン (実適用なし)

```bash
python gmail_organizer.py \
  --rules rules.yaml \
  --query "in:inbox newer_than:7d" \
  --dry-run
```

直近 7 日の受信トレイを対象に、どのルールにマッチするか表示されるだけ。

### 本番適用

```bash
python gmail_organizer.py --rules rules.yaml --query "in:inbox newer_than:7d"
```

### メルマガ解除リンク一覧を作る

```bash
python gmail_organizer.py \
  --rules rules.yaml \
  --query "in:inbox newer_than:30d" \
  --dry-run \
  --unsubscribe-out unsubscribe.md
```

→ `unsubscribe.md` に送信者ごとの解除 URL / 解除用 mailto アドレスがまとめて出力されます。
ブラウザで URL を順に開けば一括で解除できます。

`mailto:` 形式は **メールソフトでそのまま送信するだけで解除完了** することが多いです。

### 主なオプション

| オプション | 意味 | デフォルト |
|---|---|---|
| `--rules` | ルール YAML | `rules.yaml` |
| `--query` | Gmail 検索クエリ | `in:inbox newer_than:7d` |
| `--max` | 処理する最大メール数 | `200` |
| `--dry-run` | 適用せず判定のみ | off |
| `--unsubscribe-out` | 解除リンクを Markdown 出力 | なし |
| `--credentials` | OAuth JSON のパス | `credentials.json` |
| `--token` | トークン保存先 | `token.json` |

`--query` には Gmail 検索構文がそのまま使えます (`from:`, `has:attachment`,
`newer_than:30d`, `category:promotions` など)。

---

## 4. ルールの書き方

`rules.example.yaml` を参照。`match` の各条件は **AND**、ルールは **上から順に評価** され、
最初にマッチした 1 件だけが適用されます。

```yaml
rules:
  - name: "請求"
    match:
      subject: "(invoice|請求|領収)"
    action:
      label: "Org/Bills"   # "/" でネストラベル
      archive: true
      mark_read: false
      trash: false         # 通常 false 推奨
```

`has_list_unsubscribe: true` を使うと **ニュースレター類** だけを狙い撃ちで分類できます。

---

## 5. 運用のコツ

- 最初は `--dry-run` で **数日分→数週間分→全期間** と段階的に確認
- いきなり `trash: true` を使わない。`label: Org/Unwanted` + `archive: true` で受信トレイから外し、
  数週間運用して問題なければ手動でゴミ箱に流す
- cron で 1 時間おきに `newer_than:1h` で回せば常時自動仕分けになる

---

## 6. トラブルシュート

| 症状 | 対処 |
|---|---|
| `Access blocked: <your-app> has not completed verification` | OAuth 同意画面の「テストユーザー」に自分のメールを追加 / または「アプリを公開」 |
| 7 日でログインし直しになる | OAuth 同意画面の公開ステータスを「本番環境」に変更 |
| `invalid_grant` | `token.json` を削除して再認証 |
| `insufficientPermissions` | スコープ変更時は `token.json` を削除して再取得 |
