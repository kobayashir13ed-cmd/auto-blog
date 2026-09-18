# 目利きラボ — 自動記事生成ブログ

キーワードを登録しておくと、記事が自動生成され、承認ボタン1つで公開されます。

```
[週3回 自動]                      [あなた]            [自動]
キーワードを1件取り出す
  ↓
Claude APIで本文を生成       →   メールで読む    →   サイトに公開
  ↓                              ボタンを押す        GitHub Pages
承認メールを送信
```

比較表の商品情報は**読者がページを開いた時点で楽天から取得**されるため、価格は常に最新です。

- 公開先: <https://mekikilab.com/>
- 費用: 記事1本あたり約 $0.04（Claude API）。サーバー代はゼロ。

---

## 設計の要点

### 1. 承認ボタンは2段階

メールのセキュリティスキャナがリンクを勝手に先読みすることがあります。1クリックで即公開する作りだと、読む前に公開される事故が起きます。

そのため、メールのボタンを押すと**確認画面が開くだけ**で、そこでもう一度押すまで公開されません。

### 2. 使用体験は書かせない

この仕組みで生成される記事の書き手は、その商品を使っていません。したがって「実際に使ってみると」のような一人称の体験表現を**プロンプトで禁止**しています。

経験していないことを経験したように書けば、読者はそれを信じて金を使います。これは嘘であり、景品表示法上も問題になり得ます。

生成後に `EXPERIENCE_WORDS`（`scripts/generate.py`）で検査し、体験表現が混じっていたら警告を出します。

記事が書けるのは「一般に知られている選び方」までです。**その天井は承知したうえで運用してください。**

### 3. 事実は保証されない

Claude は一般論で間違えることがあります（「耐荷重は一般に○kg」など）。**承認前に読むこと**が唯一の検出手段です。

`config.json` の `auto_publish` を `true` にすると承認なしで公開されますが、誰も確認しないまま誤りが蓄積します。数本読んで傾向を掴んでから切り替えてください。

---

## 日常の操作

### キーワードを追加する

`keywords.json` に追記します。上から順に1回の実行で1件ずつ消費されます。

```json
{
  "keyword": "モニターアーム 天板 厚い 挟めない",
  "slug": "monitor-arm-thick-desk",
  "category": "gadget",
  "search_keyword": "モニターアーム クランプ",
  "intent": "天板が厚すぎてクランプが留まらない人に、対応天板厚を示す",
  "min_price": 3000,
  "max_price": 30000,
  "hits": 4,
  "status": "pending"
}
```

| 項目 | 説明 |
|---|---|
| `keyword` | 記事が狙う検索語。**3語以上の具体的な悩み**にすると競合が弱くなる |
| `search_keyword` | 楽天の商品検索に使う語。**短い商品名**でないと商品が出ない |
| `slug` | 記事URL。英数字とハイフン。**後から変えない**（検索評価を失う） |
| `category` | `config.json` の `categories` の slug |
| `hits` | 比較表に並べる商品数 |

### 記事を生成する

**Actions → 「記事ドラフトを生成して承認メールを送る」→ Run workflow**

自動実行は `.github/workflows/draft.yml` で**月・水・金の朝7時（日本時間）**。cron は UTC 指定なので、日本時間から9時間引き、曜日も1つ前にずれます。

### 承認する

メールの「内容を確認して公開する」→ 確認画面でもう一度押す。1〜2分でサイトに反映されます。

内容がおかしければ「この記事を却下する」を押すと、キーワードが未着手に戻ります。

---

## 設定ファイル

### config.json

| 項目 | 説明 |
|---|---|
| `site_title` / `site_description` | 検索結果に出る。変えるなら記事が増える前に |
| `categories` | `slug` は URL になるので**後から変えない** |
| `base_url` / `path_prefix` | 独自ドメインなので `https://mekikilab.com` と `/` |
| `search_console_site` | ドメインプロパティなので `sc-domain:mekikilab.com` 形式 |
| `rakuten_client` | **サイトのJSに埋め込まれ公開される**（後述） |
| `model` | 現行IDは <https://platform.claude.com/docs/en/models/overview> で確認 |
| `auto_publish` | `true` で承認なし公開 |

### 楽天の認証情報について

`rakuten_client` の3つの値は**公開されます**。これは設計どおりです。

楽天APIは「Web Application」として登録するとリクエストに正しい Referer を要求するため、GitHub Actions のようなサーバーからは呼べません。そこで**読者のブラウザから呼ぶ**構成にしています。`pk_` で始まる Access Key はブラウザに埋め込む前提の公開鍵で、**楽天側の `Allowed websites`（ドメイン制限）が防御**になります。

したがって `Allowed websites` には自分のドメインだけを入れてください。

---

## GitHub Secrets

| 名前 | 中身 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude APIキー。**有効期限切れに注意** |
| `APPROVAL_SECRET` | 承認リンクの署名鍵。**Cloudflare Worker と同じ値** |
| `WORKER_BASE_URL` | `https://auto-blog-approver.rk-monosashi.workers.dev` |
| `SMTP_USER` / `SMTP_FROM` / `SMTP_PASSWORD` | Gmailアドレスと**アプリパスワード**（通常のパスワードでは送信不可） |
| `NOTIFY_TO` | 承認メールの受信先 |
| `GSC_CREDENTIALS` | Search Console のサービスアカウントJSON（週次レポート用） |

楽天の値は Secrets ではなく `config.json` にあります（公開前提のため）。

---

## キーワード選定

```bash
python -m scripts.research gsc       # Search Console の実データから候補を抽出
python -m scripts.research promote   # 候補を keywords.json に登録
```

`gsc` は2つを出します。

- **リライト候補** … 8〜30位で止まっている記事。**新規に書くより改善効果が大きい**
- **新規記事の候補** … 表示はあるのに専用記事がないクエリ

週次レポート（`.github/workflows/research.yml`）が毎週月曜にこれをメールで送ります。

> `score` / `scan`（楽天APIによる市場性評価）は**現在使えません**。楽天APIがサーバーから呼べないためです。ブラウザで動くページとして作り直す必要があります。

---

## 手元で動かす

```powershell
pip install -r requirements.txt

python -m scripts.generate --mock                      # APIなしでサンプル生成
python -m scripts.notify --draft-id <ID> --dry-run     # メールのHTMLを書き出す
python -m scripts.publish --draft-id <ID> --action approve
python -m scripts.build_site

cd site && python -m http.server 8000                  # ブラウザで確認
```

`file://` で直接開くとCSSが読み込まれません。必ずHTTPサーバー経由で確認してください。

---

## ファイル構成

```
auto-blog/
├── config.json              サイト設定
├── keywords.json            記事にするキーワード
├── candidates.json          キーワード候補（gsc が追記）
├── static/                  そのままサイトへコピーされる（CNAME など）
├── .github/workflows/
│   ├── draft.yml            週3回：生成 → メール送信（または自動公開）
│   ├── publish.yml          承認を受けて公開
│   ├── deploy.yml           サイトだけ再生成（手動）
│   └── research.yml         週次：Search Console分析 → レポート
├── scripts/
│   ├── common.py            設定・ドラフトの読み書き
│   ├── claude_api.py        Claude API
│   ├── generate.py          ドラフト生成（体験表現の検査を含む）
│   ├── notify.py            承認メール
│   ├── tokens.py            承認リンクの署名（HMAC）
│   ├── publish.py           公開 / 却下
│   ├── build_site.py        静的サイト生成
│   ├── research.py          キーワード選定CLI
│   ├── report.py            週次レポート
│   ├── kw/                  Search Console連携・市場性評価
│   └── hikaku/              比較表（widget.py がブラウザ用JSを生成）
├── worker/index.js          承認ボタンの受け口（Cloudflare Worker）
├── content/drafts/          未承認の記事
├── content/posts/           公開済みの記事
└── site/                    生成されたサイト（GitHub Pagesが配信）
```

---

## つまずいたとき

| 症状 | 原因 |
|---|---|
| `git push` が rejected | Actionsがコミットしている。**作業前に `git pull`** |
| メールが届かない | Gmailの通常パスワードを使っている（アプリパスワードが必要） |
| 「トークンが一致しません」 | `APPROVAL_SECRET` が GitHub と Cloudflare で違う |
| 記事生成が HTTP 401 | Claude APIキーが無効。有効期限切れの可能性 |
| 記事生成が HTTP 404 | `config.json` の `model` が古い |
| 比較表が出ない | 楽天の `Allowed websites` にドメインが入っていない |
| サイトのCSSが効かない | `path_prefix` が違う |
| Search Console が 404 | `search_console_site` の書式（`sc-domain:` 形式か） |

---

## 運用の考え方

**記事数を増やす前に、インデックスされているか確認してください。**

Search Console の **インデックス作成 → ページ** で状態が見られます。

| 表示 | 判断 |
|---|---|
| インデックス登録済み | 増やしてよい |
| 検出 - インデックス未登録 | クロール待ち。待つ |
| **クロール済み - インデックス未登録** | **増やしても無駄。中身を変える** |

3つ目が増えたら、Googleが「載せる価値がない」と判断したということです。そこで記事数を増やしても結果は変わりません。一次情報（実データの集計など）を足す方向に切り替えてください。
