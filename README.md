# auto-blog — 承認つき自動投稿ブログ

記事を自動生成 → **あなたにメール** → ボタンを押す → 自動でサイトに公開。

```
[週1回 自動]                         [週2回 自動]              [あなた]           [自動]
Search Consoleを分析                 キーワードを1件取り出す                       
  ↓                                    ↓                                          
リライト候補 / 新規候補を抽出   →    Claude APIで本文生成   →  メールで読む   →  サイトに公開
候補を市場性スコアで評価             楽天APIで比較表生成       ボタンを押す      GitHub Pagesへ
  ↓                                    ↓                                          
週次レポートをメール                 承認メールを送信                              
```

サーバー代はかかりません。費用は記事生成のAPI代（1本あたり数十円程度）だけです。

---

## 設計上、知っておいてほしいこと

### 1. 承認ボタンは2段階です

メールのセキュリティスキャナやプレビュー機能が、リンクを**勝手に先読みすることがあります**。
GETリクエストで即公開する作りだと、あなたが読む前に公開される事故が起きます。

そのため、メールのボタンを押すと**確認画面が開くだけ**で、そこでもう一度押すまで公開されません。

### 2. 未記入欄があると公開できません

生成される記事には `{{実体験}}` と `{{注意点}}` という**あなたが書く欄**が必ず含まれます。
ここが空のまま承認しても、公開は中止されます。

これは意地悪ではなく、**あなたのサイトを守るための歯止め**です。
Googleは2024年3月にスパムポリシーへ「スケーラブルなコンテンツの不正利用」を明記しており、
中身のない記事を量産すると、サイト全体が検索結果から外される可能性があります。

AIが書けるのは一般論までです。**実際に使った人にしか書けない部分があなたの差別化要素**であり、
それがない記事を出し続けると、長期的には資産になりません。

どうしても外したい場合は `config.json` の `require_placeholders_filled` を `false` にできますが、
推奨しません。

### 3. 記事は自動生成されますが、事実は保証されません

Claude には「与えられた商品データ以外の事実を創作しない」よう指示していますが、
完全ではありません。**承認前に必ず内容を読んでください。** それが承認ステップの存在意義です。

---

## セットアップ

所要時間は1時間ほどです。順番どおりに進めてください。

### 手順1：GitHubリポジトリを作る

このフォルダの中身を、新しく作ったGitHubリポジトリにpushします。

```bash
git init
git add .
git commit -m "初期構築"
git branch -M main
git remote add origin https://github.com/<あなたのユーザー名>/<リポジトリ名>.git
git push -u origin main
```

> リポジトリは**Publicでも問題ありません**。APIキーはすべてGitHub Secretsに入れ、
> コードには一切書かないためです。

### 手順2：Claude APIキーを取得する

1. <https://console.anthropic.com/> にアクセスしてアカウントを作成
2. 支払い方法を登録（従量課金。最低でも数ドルのクレジット購入が必要）
3. 「API Keys」から新しいキーを発行し、`sk-ant-...` をコピー

発行時にしか表示されないので、その場でコピーしてください。

> **Claude Pro / Max のサブスクとは別会計です。** チャットの契約とAPIの料金は別物で、
> Proに入っていてもAPIにはクレジットの購入が必要です。

料金の目安（`claude-sonnet-5`）：1記事あたり約 $0.04。月40本書いても $2 弱です。

> 使うモデルIDは `config.json` の `model` で指定します。
> 現行のモデルIDは <https://platform.claude.com/docs/en/models/overview> で確認してください。
> 古いIDのままだとHTTP 404になります。

### 手順3：楽天のアプリIDを取得する

1. <https://webservice.rakuten.co.jp/> でアプリを新規登録（無料・審査なし・即日）
2. 発行された `applicationId` をコピー
3. 楽天アフィリエイトにも登録し、アフィリエイトIDを取得（あとからでも可）

### 手順4：メール送信の準備（Gmailの場合）

Gmailは通常のパスワードでは外部から送信できません。

1. Googleアカウントで**2段階認証を有効にする**
2. <https://myaccount.google.com/apppasswords> で「アプリパスワード」を発行
3. 表示された16桁をコピー（これを `SMTP_PASSWORD` に使います）

> Gmail以外を使う場合は `config.json` の `smtp.host` と `smtp.port` を変更してください。

### 手順5：承認用の秘密鍵を作る

承認リンクの署名に使うランダムな文字列です。手元で生成します。

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

出てきた文字列をコピーしてください。**GitHubとCloudflareの両方に同じ値を登録します。**

### 手順6：GitHubの個人アクセストークンを作る

Cloudflare WorkerからGitHubに公開を指示するために必要です。

1. <https://github.com/settings/tokens> →「Generate new token (classic)」
2. スコープは **`repo`** にチェック
3. 生成された `ghp_...` をコピー

### 手順7：Cloudflare Workerをデプロイする

承認ボタンの受け口です。無料枠で十分動きます。

```bash
cd worker
npx wrangler login          # ブラウザが開くので許可する
npx wrangler secret put APPROVAL_SECRET   # 手順5の文字列を貼る
npx wrangler secret put GITHUB_TOKEN      # 手順6のトークンを貼る
npx wrangler secret put GITHUB_REPO       # 例: yourname/auto-blog
npx wrangler deploy
```

デプロイに成功すると `https://auto-blog-approver.<サブドメイン>.workers.dev` というURLが表示されます。
**このURLをコピーしてください。**

### 手順8：GitHub Secretsを登録する

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** で、
以下を1つずつ登録します。

| 名前 | 中身 |
|---|---|
| `ANTHROPIC_API_KEY` | 手順2のAPIキー |
| `RAKUTEN_APP_ID` | 手順3のアプリID |
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリエイトID（未取得なら空でも可） |
| `APPROVAL_SECRET` | 手順5の文字列（**Workerと同じ値**） |
| `WORKER_BASE_URL` | 手順7のWorkerのURL |
| `SMTP_USER` | 送信元のGmailアドレス |
| `SMTP_PASSWORD` | 手順4のアプリパスワード |
| `SMTP_FROM` | 送信元アドレス（`SMTP_USER` と同じでよい） |
| `NOTIFY_TO` | 承認メールの受信先（あなたのアドレス） |
| `GSC_CREDENTIALS` | Search ConsoleのサービスアカウントJSON（記事公開後でよい。後述） |

### 手順9：GitHub Pagesを有効にする

**Settings → Pages → Source** を **「GitHub Actions」** に設定します。
（「Deploy from a branch」ではありません）

### 手順10：`config.json` を編集する

```json
{
  "site_title": "サイト名",
  "site_description": "サイトの説明",
  "author": "運営者名",
  "contact_email": "連絡先メールアドレス",
  "base_url": "https://ユーザー名.github.io/リポジトリ名",
  "path_prefix": "/リポジトリ名/"
}
```

> `path_prefix` に注意してください。
> `ユーザー名.github.io/リポジトリ名` で配信する場合は `/リポジトリ名/` です。
> 独自ドメインを使う場合のみ `/` にします。ここを間違えるとCSSが読み込まれません。

`author` と `contact_email` は運営者情報ページに表示されます。
アフィリエイト運営では運営者情報の掲載が各ASPの規約で求められるため、**必ず埋めてください**。

---

## 使い方

### 記事にしたいキーワードを登録する

`keywords.json` に追加します。上から順に1回の実行で1件ずつ消費されます。

```json
{
  "keyword": "モニターアーム おすすめ",
  "slug": "monitor-arm",
  "search_keyword": "モニターアーム",
  "intent": "デスクを広く使いたい人に、耐荷重と固定方式の選び方を示す",
  "min_price": 3000,
  "max_price": 30000,
  "hits": 3,
  "status": "pending"
}
```

`slug` が記事URLになります。英数字とハイフンで、内容が推測できる短い語にしてください。
`category` には `config.json` の `categories` で定義した slug を入れます。

### カテゴリ運用について

ジャンルを固定せず複数カテゴリで運用できます。ただし2点だけ注意してください。

**1. カテゴリの `slug` は後から変えない**

`/category/<slug>/` がURLになるため、変更すると積み上げた検索評価を失います。
記事が0本のカテゴリはページもナビも生成されない（404リンクを作らないため）ので、
最初から多めに定義しておいて構いません。

**2. トレンドを扱うなら「周期的なもの」を選ぶ**

話題の出来事のような瞬間的トレンドは数日で検索されなくなり、ストックになりません。
一方、花粉症対策・夏の暑さ対策・新生活家電などは**毎年同じ時期に需要が復活する**ため、
一度書けば何年も効きます。同じ「トレンド」でも性質が正反対なので、後者を狙ってください。

### 動かす

初回は手動で試します。
**Actions → 「記事ドラフトを生成して承認メールを送る」→ Run workflow**

1〜2分でメールが届きます。メールには記事の全文が入っています。

### 承認する流れ

1. メールを読む
2. `{{実体験}}` が未記入なら「GitHubで編集する」を押して埋める（スマホのブラウザでも編集できます）
3. 「内容を確認して公開する」を押す
4. 確認画面が出るので、もう一度押す
5. 1〜2分でサイトに反映される

### 自動実行

`.github/workflows/draft.yml` で**火曜と金曜の朝7時（日本時間）**に設定してあります。
変更する場合は cron を編集してください（**UTC指定**なので日本時間から9時間引きます）。

---

## 手元で動作確認する

APIキーなしで全工程を試せます。

```bash
pip install -r requirements.txt

python3 -m scripts.generate --mock                       # サンプル記事を生成
python3 -m scripts.notify --draft-id <ID> --dry-run      # メールのHTMLを書き出す
python3 -m scripts.publish --draft-id <ID> --action approve
python3 -m scripts.build_site                            # site/ を生成

cd site && python3 -m http.server 8000                   # ブラウザで確認
```

> `file://` で直接開くとCSSが読み込まれません（絶対パス参照のため）。
> 必ず上記のようにHTTPサーバー経由で確認してください。

---

## ファイル構成

```
auto-blog/
├── config.json              サイト設定
├── keywords.json            記事にするキーワードの一覧
├── requirements.txt
├── candidates.json          評価待ち・評価済みのキーワード候補
├── .github/workflows/
│   ├── draft.yml            定期実行：生成 → メール送信
│   ├── publish.yml          承認を受けて公開
│   └── research.yml         週次：Search Console分析 → レポート送信
├── scripts/
│   ├── common.py            設定・ドラフトの読み書き
│   ├── claude_api.py        Claude API（本文生成）
│   ├── generate.py          ドラフト生成
│   ├── notify.py            承認メール送信
│   ├── tokens.py            承認リンクの署名
│   ├── publish.py           公開 / 却下
│   ├── build_site.py        静的サイト生成
│   ├── research.py          キーワード選定CLI
│   ├── report.py            週次レポートのメール送信
│   ├── kw/
│   │   ├── market.py        市場性評価（楽天APIベース）
│   │   └── gsc.py           Search Console連携
│   └── hikaku/              比較表生成（楽天・Amazon APIクライアント含む）
├── worker/
│   ├── index.js             承認ボタンの受け口（Cloudflare Worker）
│   └── wrangler.toml
├── content/
│   ├── drafts/              未承認の記事
│   ├── posts/               公開済みの記事
│   └── rejected/            却下した記事
└── site/                    生成されたサイト（GitHub Pagesが配信）
```

---

## つまずきやすいところ

| 症状 | 原因 |
|---|---|
| メールが届かない | Gmailの通常パスワードを使っている。アプリパスワードが必要（手順4） |
| 承認ボタンで「トークンが一致しません」 | `APPROVAL_SECRET` がGitHubとWorkerで違う |
| 承認しても公開されない | Workerの `GITHUB_TOKEN` に `repo` スコープがない |
| サイトのCSSが効かない | `config.json` の `path_prefix` が違う（手順10） |
| 記事生成が HTTP 404 | `config.json` の `model` が古い。公式ドキュメントで現行IDを確認 |
| 公開が中止される | `{{実体験}}` が未記入。これは仕様です |
| Search Consoleが403 | サービスアカウントをSearch Consoleのユーザーに追加していない |
| Search Consoleが404 | `search_console_site` がプロパティ名と完全一致していない |
| promote で登録されない | 既存キーワードと内容が重複、またはslugが衝突。メッセージに理由が出ます |

---

## キーワード選定ツール

記事を何本書くかより、**何について書くか**のほうが成果を左右します。ここを外すと、
どれだけ良い記事を書いても検索流入はゼロになります。

### 最初に：このツールが測れないもの

**検索ボリューム（月に何人が検索したか）は取得していません。**
無料で正確に取る手段が存在しないためです。キーワードプランナーはGoogle広告アカウントと
審査が必要で、有料ツールは月数千円かかります。
そして**Googleの検索結果をスクレイピングする方法は規約違反なので採っていません。**

代わりに、確実に取れる2つの実データを使います。

| データ源 | わかること | 使える時期 |
|---|---|---|
| 楽天API | 商品数・総レビュー数・平均価格 | 今すぐ |
| Search Console API | 自サイトの実際の表示回数・順位 | 記事公開の数週間後 |

**本命は2つ目です。** 自分のサイトの実測値なので推定が入りません。
立ち上げ期は楽天ベースで候補を出し、データが溜まったらSearch Consoleに主軸を移してください。

### スコアの意味

```
市場の魅力（0〜100）= 需要 45点 + 報酬 30点 + 供給 25点
総合スコア          = 市場の魅力 × 購買意図の係数（0.45〜1.0）
```

| 項目 | 根拠 |
|---|---|
| **需要** | 上位商品の総レビュー数。**実際に売れている証拠**なので最も信頼できます |
| **報酬** | 平均価格。楽天の料率は数%なので、単価がそのまま1件あたりの報酬になります |
| **供給** | 商品数。少なすぎると比較記事が作れず、多すぎると差別化できません |
| **購買意図** | 「おすすめ」「比較」があれば1.0、「とは」「使い方」があれば0.45 |

購買意図を**加点ではなく係数**にしているのは、
「商品市場は大きいが誰も買う気がないキーワード」が中途半端に高得点になるのを防ぐためです。
`マウス 使い方 とは` は市場の魅力が70点でも、総合は31点に落ちます。

なお**競合サイトの強さは測っていません**。語数から「競合が弱い可能性がある（推定）」と
注記することはありますが、これは実測ではありません。

### 使い方

```bash
# 1件だけ試す
python3 -m scripts.research score --keyword "モニターアーム おすすめ"

# candidates.json の候補をまとめて評価（スコア順に並べ替わる）
python3 -m scripts.research scan

# Search Console の実データから候補を抽出（記事公開後）
python3 -m scripts.research gsc

# 上位候補を keywords.json に登録 → 記事生成の対象になる
python3 -m scripts.research promote --top 3
```

`--mock` を付ければ、APIキーなしで動作を確認できます。

### promote が登録を見送る2つのケース

**1. 内容が重複する場合**

`ゲーミングマウス 軽量` が既にあるとき、`ゲーミングマウス 軽量 おすすめ` は登録されません。
ほぼ同じ記事が2本できると、Googleがどちらを上位に出すか判断できず**両方の順位が下がります**
（キーワードカニバリゼーション）。1本にまとめるほうが強くなります。
承知のうえで登録するなら `--force` を付けます。

**2. URLが衝突する場合**

同じ `slug` が既に使われていると登録されません。同じURLに2記事を置くと上書きされるためです。
これは `--force` でも回避できません。`candidates.json` で別の slug を指定してください。

### 週次レポート

毎週月曜の朝、Search Consoleの分析結果がメールで届きます。

- **リライト候補** … 8〜30位で止まっている記事。**新しく書くよりここを直すほうが成果が出ます**
- **新規記事の候補** … 表示はされているのに専用記事がないクエリ

Search Consoleを毎週自分で開く習慣はまず続かないので、向こうから届くようにしてあります。

### Search Console の設定（記事公開後でよい）

1. Google Cloud でサービスアカウントを作成し、JSONキーをダウンロード
2. Search Console API を有効化
3. **Search Console の「設定 > ユーザーと権限」で、サービスアカウントのメールアドレス
   （`...iam.gserviceaccount.com`）を「制限付き」権限で追加する**
   ← これを忘れると403エラーになります
4. GitHub Secrets に `GSC_CREDENTIALS` として、JSONキーの中身を丸ごと貼り付ける
5. `config.json` に `search_console_site` を追加
   （Search Consoleのプロパティと完全に同じ文字列。
   ドメインプロパティなら `sc-domain:example.com` 形式）

---

## 現実的な見通し

このシステムは記事の生産と改善を自動化しますが、**成果が出るまでの時間は短縮しません**。

SEOで検索流入が立ち上がるまで、通常6〜12ヶ月かかります。最初の数ヶ月はほぼ無収入です。
ここで辞める人が大半で、逆に言えば続けるだけで競合が減ります。

このツールが減らせるのは「毎週の作業負荷」であって、「待つ期間」ではありません。
その前提で運用してください。
