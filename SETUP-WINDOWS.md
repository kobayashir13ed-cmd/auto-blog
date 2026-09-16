# セットアップ手順（Windows版・チェックリスト）

上から順に進めてください。各ステップで取得した値は、手順8でまとめて登録します。
**取得した値は手順8まで手元のメモ帳などに控えておいてください。**

コマンドは PowerShell で実行します（スタートメニューで「PowerShell」と検索）。

---

## 事前確認：必要なツールが入っているか

PowerShell で以下を実行してください。

```powershell
python --version
git --version
node --version
```

| 結果 | 対処 |
|---|---|
| `python` が動かない | Anaconda Prompt を使うか、Anaconda を PATH に追加 |
| `git` が動かない | <https://git-scm.com/download/win> からインストール |
| `node` が動かない | <https://nodejs.org/> からLTS版をインストール（手順7で必要） |

---

## □ 手順1：GitHubリポジトリを作る

1. <https://github.com/new> で新しいリポジトリを作成
   - 名前は任意（例: `auto-blog`）
   - **Public / Private どちらでも可**（APIキーはコードに含めないため）
   - README等は追加しない（空のまま作る）

2. このフォルダで PowerShell を開き、以下を実行

```powershell
git init
git add .
git commit -m "初期構築"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/<リポジトリ名>.git
git push -u origin main
```

**控える値：** `<ユーザー名>/<リポジトリ名>`（手順7で使います）

---

## □ 手順2：Claude APIキーを取得する

### これは何か

**記事の本文をAIに書かせるための鍵**です。GitHub Actionsが自動で記事を生成するとき、
プログラムからClaudeに文章を書かせる必要があり、そのときの認証に使います。

> **重要：Claude Pro / Max のサブスクとは別物です。**
> チャット画面で使っているClaudeの契約と、APIの料金は完全に別会計です。
> Proに入っていてもAPIは使えないので、別途クレジットの購入が必要です。

### 料金の目安

`claude-sonnet-5` を使う場合（入力 $2/100万トークン、出力 $10/100万トークン）:

| ペース | 月のAPI代 |
|---|---|
| 1記事あたり | 約 $0.04 |
| 週2本（月8本） | 約 $0.35 |
| 週10本（月40本） | 約 $1.7 |

**量産してもほぼ無視できる金額です。** 初回のクレジット購入額（通常$5程度）で
100本以上生成できます。

### 取得手順

1. <https://console.anthropic.com/> でアカウント作成
2. **Billing** → 支払い方法を登録し、クレジットを購入
   （ここを飛ばすとキーを作っても401エラーになります）
3. **API Keys** → 「Create Key」→ 名前は任意

**控える値：** `sk-ant-...` で始まる文字列

> **この画面を閉じると二度と表示されません。** 必ずその場でコピーしてください。
> 紛失したら作り直せます（古いキーは削除してよい）。

---

## □ 手順3：楽天アプリIDを取得する

1. <https://webservice.rakuten.co.jp/> でアプリを新規登録（無料・審査なし・即日）
2. 発行された `applicationId` をコピー

**控える値：** アプリID

楽天アフィリエイトIDは後からでも構いません（未設定でも動作しますが報酬は発生しません）。

---

## □ 手順4：Gmailのアプリパスワードを発行する

Gmailは通常のパスワードでは外部から送信できません。

1. Googleアカウントで**2段階認証を有効にする**
   <https://myaccount.google.com/security>
2. <https://myaccount.google.com/apppasswords> でアプリパスワードを発行
3. 表示された16桁をコピー（スペースは入れても入れなくても可）

**控える値：** Gmailアドレス と 16桁のアプリパスワード

---

## □ 手順5：承認用の秘密鍵

以下の値を使ってください（このセッションで生成済み）。

```
vA475dpEdJ6zj9EclRvkC1u96swUSdszkliKnYZ9r5k
```

自分で作り直したい場合は PowerShell で：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**この値は手順7と手順8の両方で使います。必ず同じ値にしてください。**
ここが食い違うと、承認ボタンを押したときに「トークンが一致しません」と出ます。

---

## □ 手順6：GitHubの個人アクセストークンを作る

### これは何か

**プログラムがあなたの代わりにGitHubを操作するためのパスワード代わり**です。

承認メールのボタンを押すと、Cloudflare Worker が
「この記事を公開せよ」とGitHubに指示を出します。このときGitHubは
「お前は誰だ」と聞いてくるので、その答えとしてこのトークンを使います。

トークンは**Cloudflare側にだけ保管され、メールには一切載りません**。
だから承認リンクを他人に見られても、勝手に公開されることはありません。

> このトークンは**あなたのリポジトリを書き換えられる権限**を持ちます。
> 他人に渡さないでください。漏れた場合は同じ画面から削除すれば即座に無効になります。

### 取得手順

1. <https://github.com/settings/tokens> を開く
2. 「Generate new token」→ **「Generate new token (classic)」** を選ぶ
   （Fine-grained ではなく classic です）
3. **Note**：`auto-blog-worker` など分かる名前
4. **Expiration**：有効期限。切れると承認ボタンが動かなくなるので
   `No expiration` か長め（1年）を推奨
5. **Select scopes**：**`repo`** にチェック（一番上の親項目。これだけでよい）
6. 一番下の「Generate token」

**控える値：** `ghp_...` で始まる文字列

> **この画面を閉じると二度と表示されません。** その場でコピーしてください。

---

## □ 手順7：Cloudflare Workerをデプロイする

承認ボタンの受け口です。無料枠で足ります。

```powershell
cd worker
npx wrangler login
```

ブラウザが開くので許可してください。続けて秘密変数を登録します。

```powershell
npx wrangler secret put APPROVAL_SECRET
# → 手順5の値を貼り付けて Enter

npx wrangler secret put GITHUB_TOKEN
# → 手順6の ghp_... を貼り付けて Enter

npx wrangler secret put GITHUB_REPO
# → 手順1の ユーザー名/リポジトリ名 を貼り付けて Enter
```

```powershell
npx wrangler deploy
cd ..
```

成功すると `https://auto-blog-approver.〇〇.workers.dev` というURLが表示されます。

**控える値：** そのURL

---

## □ 手順8：GitHub Secrets を登録する

リポジトリのページで
**Settings → Secrets and variables → Actions → New repository secret**

以下を1つずつ登録します（名前は完全一致させること）。

| Name | Secret（値） |
|---|---|
| `ANTHROPIC_API_KEY` | 手順2のキー |
| `RAKUTEN_APP_ID` | 手順3のアプリID |
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリエイトID（なければ空欄で登録しない） |
| `APPROVAL_SECRET` | 手順5の値（**Workerと同じ**） |
| `WORKER_BASE_URL` | 手順7のURL |
| `SMTP_USER` | Gmailアドレス |
| `SMTP_PASSWORD` | 手順4の16桁 |
| `SMTP_FROM` | Gmailアドレス（SMTP_USERと同じでよい） |
| `NOTIFY_TO` | 承認メールを受け取るアドレス |

`GSC_CREDENTIALS` は記事公開後に設定するので、今は不要です。

---

## □ 手順9：GitHub Pages を有効にする

**Settings → Pages → Source** を **「GitHub Actions」** に変更。

（「Deploy from a branch」ではありません。ここを間違えるとサイトが表示されません）

---

## □ 手順10：config.json を編集する

```json
{
  "site_title": "サイト名",
  "site_description": "サイトの説明",
  "author": "運営者名またはハンドルネーム",
  "contact_email": "問い合わせ用アドレス",
  "base_url": "https://<ユーザー名>.github.io/<リポジトリ名>",
  "path_prefix": "/<リポジトリ名>/"
}
```

**`path_prefix` に注意。** `github.io/リポジトリ名` で配信する場合は `/リポジトリ名/` です。
ここを間違えるとCSSが読み込まれず、文字だけのページになります。

### カテゴリを決める

`categories` に初期値としてガジェット・家具・季節トレンドの3つが入っています。
増やしても減らしても構いませんが、**`slug` は後から変えないでください。**
`/category/<slug>/` がそのままURLになるため、変更すると検索評価を失います。

```json
"categories": [
  { "slug": "gadget",    "name": "ガジェット",       "description": "..." },
  { "slug": "furniture", "name": "家具・インテリア", "description": "..." },
  { "slug": "seasonal",  "name": "季節・トレンド",   "description": "..." }
]
```

記事が1本もないカテゴリはページもナビも生成されません（404リンクを作らないため）。
なので最初から多めに定義しておいて問題ありません。

編集したらコミットします。

```powershell
git add config.json
git commit -m "サイト設定"
git push
```

---

## □ 手順11：テスト実行

リポジトリの **Actions** タブ →
**「記事ドラフトを生成して承認メールを送る」** → **Run workflow**

1〜2分でメールが届きます。

届いたら:
1. 内容を読む
2. 「GitHubで編集する」から `{{実体験}}` と `{{注意点}}` を埋める
3. 「内容を確認して公開する」→ 確認画面でもう一度押す
4. 1〜2分後、`https://<ユーザー名>.github.io/<リポジトリ名>/` を開く

---

## うまくいかないとき

| 症状 | 原因と対処 |
|---|---|
| Actionsが赤く失敗する | ログを開き、どのステップで落ちたか確認。Secretsの名前の打ち間違いが最多 |
| メールが届かない | アプリパスワードではなく通常パスワードを登録している（手順4） |
| 「トークンが一致しません」 | `APPROVAL_SECRET` がWorkerとGitHubで違う（手順5） |
| 承認しても公開されない | Workerの `GITHUB_TOKEN` に `repo` スコープがない（手順6） |
| サイトが404 | Pages の Source が「GitHub Actions」になっていない（手順9） |
| サイトの見た目が崩れる | `path_prefix` が違う（手順10） |
| 記事生成が HTTP 404 | `config.json` の `model` が古い。公式ドキュメントで現行IDを確認 |

エラーメッセージをそのまま貼ってもらえれば、どこが原因か判断します。
