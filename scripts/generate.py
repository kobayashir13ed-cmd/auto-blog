"""記事ドラフトの生成。

処理の流れ:
  1. keywords.json から未着手のキーワードを1件取り出す
  2. 楽天APIで該当商品を取得し、比較表HTMLを作る
  3. Claude API に「取得した実データだけを使って」本文を書かせる
  4. content/drafts/ に保存し、キーワードを drafted に更新する

--mock を付けるとAPIを一切呼ばずサンプルを生成する（動作確認用）。
"""

from __future__ import annotations

import argparse
import sys

from . import claude_api, common
from .hikaku import table as hikaku_table
from .hikaku.models import Product
from .hikaku.providers import rakuten

# --------------------------------------------------------------------------
# プロンプト
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """\
あなたは日本語のレビュー記事を書く編集者です。次の原則を必ず守ってください。

1. 与えられた商品データ（商品名・価格・評価）以外の事実を創作しない。
   スペックが不明なものは「メーカー公表値を確認してください」と書く。
2. 誇大な断定を避ける。「絶対に」「必ず」「No.1」は使わない。
3. 健康・医療・金銭的効果に関する主張はしない。
4. 読者が判断を下せる情報を書く。長所だけでなく短所も必ず書く。
5. 検索順位のための水増しをしない。内容のない一般論で文字数を稼がない。
"""

USER_PROMPT = """\
次の条件で日本語のレビュー記事をMarkdownで書いてください。

## キーワード
{keyword}

## 記事の狙い
{intent}

## 取り上げる商品（この情報だけを事実として使うこと）
{products}

## 必須の構成
以下の見出し構成に厳密に従ってください。

```
（リード文：2〜3文。読者の悩みを言い当てる。見出しなし）

## {keyword}の選び方

（判断基準を3つ。それぞれ小見出し `### ` を付けて2〜3文ずつ）

## おすすめ{count}選 比較表

<!--TABLE-->

## 各商品の詳細

（商品ごとに `### 商品名` を付けて、3〜4文。必ず短所にも触れる）

## 実際に使ってみて

{{{{実体験}}}}

## 購入前に知っておきたい注意点

{{{{注意点}}}}

## まとめ

（3〜4文。どういう人にどれを勧めるかを明示する）

## よくある質問

（Q&A形式で3組。`### Q. ` と回答）
```

## 厳守事項
- `<!--TABLE-->` は必ずそのまま1行で残すこと（比較表が自動で差し込まれます）
- `{{{{実体験}}}}` と `{{{{注意点}}}}` は**そのまま残すこと**。ここは人間が後で書きます。
  あなたが埋めてはいけません。
- 記事タイトルは出力しない（本文のみ）
- 全体で2000〜3000字程度

## 出力形式
1行目に「TITLE: 」に続けて記事タイトル（32文字以内、キーワードを含む）。
2行目に「DESC: 」に続けてメタディスクリプション（120文字以内）。
3行目以降に本文Markdown。
"""


def format_products(products: list[Product]) -> str:
    lines = []
    for i, p in enumerate(products, 1):
        parts = [f"{i}. {p.name}", f"   価格: {p.price_text}"]
        if p.rating is not None:
            reviews = f"（{p.review_count}件）" if p.review_count else ""
            parts.append(f"   評価: {p.rating:.2f}/5.00{reviews}")
        if p.shop:
            parts.append(f"   販売: {p.shop}")
        if p.free_shipping is not None:
            parts.append(f"   送料: {'無料' if p.free_shipping else '別途'}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# モック（APIキーなしの動作確認用）
# --------------------------------------------------------------------------

def mock_products() -> list[Product]:
    return [
        Product(name="サンプル ワイヤレスマウス Pro 静音設計 充電式",
                url="https://example.com/a", price=4980, shop="サンプルストア",
                rating=4.52, review_count=1284, free_shipping=True,
                provider="rakuten", item_code="mock:a",
                specs={"重量": "78g", "接続": "2.4GHz / Bluetooth"},
                comment="軽さと静音性のバランスが良い。",
                recommended=True, badge="総合1位"),
        Product(name="サンプル 軽量マウス Air 超軽量49g 有線",
                url="https://example.com/b", price=3280, shop="サンプル電器",
                rating=4.21, review_count=642, free_shipping=False,
                provider="rakuten", item_code="mock:b",
                specs={"重量": "49g", "接続": "有線"},
                comment="とにかく軽い。コスパ重視ならこれ。", badge="最安値"),
        Product(name="サンプル 多ボタンマウス MX 8ボタン",
                url="https://example.com/c", price=8740, shop="サンプル工房",
                rating=4.38, review_count=203, free_shipping=True,
                provider="rakuten", item_code="mock:c",
                specs={"重量": "115g", "接続": "Bluetooth"},
                comment="多機能だが重い。割り切って使う人向け。"),
    ]


MOCK_BODY = """\
TITLE: 軽量ゲーミングマウス おすすめ3選【2026年版】
DESC: 軽量ゲーミングマウスを重量・接続方式・価格で比較。用途別にどれを選ぶべきかを整理しました。
長時間のプレイで手首が疲れる、という悩みは重量で解決できることが多いです。\
ただし軽ければ良いというものでもなく、接続方式との組み合わせで使い勝手は大きく変わります。\
ここでは3製品を実データで比較します。

## 軽量ゲーミングマウスの選び方

### 重量は80gを境に体感が変わる

80g以下だと長時間でも疲れにくくなります。ただし軽すぎると細かい制御がしにくいと感じる人もいます。

### 接続方式は用途で決める

遅延を最優先するなら有線、取り回しを優先するなら2.4GHz無線が無難です。\
Bluetoothは省電力ですが反応速度では劣ります。

### 価格帯は3000円台から

3000円台でも十分実用的です。1万円近い製品との差は主にボタン数とカスタマイズ性にあります。

## おすすめ3選 比較表

<!--TABLE-->

## 各商品の詳細

### サンプル ワイヤレスマウス Pro 静音設計 充電式

78gと扱いやすい重量で、静音設計のため共有スペースでも使いやすい製品です。\
評価4.52とレビュー数1284件は信頼できる水準といえます。\
一方で充電式のため、充電を忘れると使えなくなる点は運用上の手間になります。

### サンプル 軽量マウス Air 超軽量49g 有線

49gは今回の3製品で最軽量です。有線なので遅延と電池切れの心配がありません。\
ただし送料が別途かかる点と、ケーブルの取り回しが気になる人には向きません。

### サンプル 多ボタンマウス MX 8ボタン

8ボタンを自由に割り当てられるため、作業効率を上げたい人に向いています。\
115gとやや重く、価格も8740円と高めなので、多ボタンを使い切れない場合は割高になります。

## 実際に使ってみて

{{実体験}}

## 購入前に知っておきたい注意点

{{注意点}}

## まとめ

迷ったら78gのワイヤレスマウス Proが無難です。\
とにかく軽さとコスパを求めるなら軽量マウス Air、\
ボタン割り当てを使い倒したいなら多ボタンマウス MXを選ぶとよいでしょう。\
なお価格は変動するため、購入前に各販売ページで最新の価格を確認してください。

## よくある質問

### Q. 軽いマウスは壊れやすいですか？

重量と耐久性に直接の相関はありません。\
ただし軽量化のために筐体を薄くしている製品はあるため、メーカーの保証期間を確認してください。

### Q. 有線と無線でどちらが遅延しますか？

一般に有線のほうが遅延は少ないとされますが、\
近年の2.4GHz無線は体感できる差がほとんどないという評価も多くあります。

### Q. 充電式と電池式はどちらがよいですか？

充電の手間を避けたいなら電池式、ランニングコストを抑えたいなら充電式が向いています。\
用途に応じて選んでください。
"""


# --------------------------------------------------------------------------

def parse_response(text: str) -> tuple[str, str, str]:
    """「TITLE: / DESC: / 本文」の形式を分解する。"""
    title, description = "", ""
    lines = text.strip().splitlines()
    body_start = 0
    for i, line in enumerate(lines[:4]):
        if line.startswith("TITLE:"):
            title = line[len("TITLE:"):].strip()
            body_start = i + 1
        elif line.startswith("DESC:"):
            description = line[len("DESC:"):].strip()
            body_start = i + 1
    body = "\n".join(lines[body_start:]).strip()
    return title, description, body


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="記事ドラフトを生成します")
    parser.add_argument("--mock", action="store_true",
                        help="APIを呼ばずサンプルを生成（動作確認用）")
    parser.add_argument("--keyword", default="",
                        help="キーワードを直接指定（keywords.json を使わない）")
    args = parser.parse_args(argv)

    config = common.load_config()

    # --- キーワードを決める ---
    keywords_data = None
    if args.keyword:
        entry = {"keyword": args.keyword, "slug": "", "intent": ""}
    else:
        entry, keywords_data = common.next_keyword()
        if entry is None:
            print("未着手のキーワードがありません。keywords.json に追加してください。")
            return

    keyword = entry["keyword"]
    print(f"対象キーワード: {keyword}")

    # --- 商品を取得 ---
    hits = int(entry.get("hits") or config.get("products_per_post", 3))
    if args.mock:
        products = mock_products()[:hits]
        print(f"  [モック] 商品{len(products)}件")
    else:
        rk = config.get("rakuten", {})
        products = rakuten.search(
            keyword=entry.get("search_keyword") or keyword,
            application_id=common.env("RAKUTEN_APP_ID"),
            affiliate_id=common.env("RAKUTEN_AFFILIATE_ID", required=False),
            hits=hits,
            min_price=entry.get("min_price"),
            max_price=entry.get("max_price"),
        )
        if not products:
            sys.exit(f"[エラー] 商品が取得できませんでした: {keyword}")
        print(f"  楽天から{len(products)}件取得")
        # 1件目をおすすめ扱いにしておく（あとで人が入れ替えられる）
        products[0].recommended = True
        products[0].badge = "総合1位"

    # --- 本文を生成 ---
    if args.mock:
        raw = MOCK_BODY
    else:
        prompt = USER_PROMPT.format(
            keyword=keyword,
            intent=entry.get("intent") or f"{keyword}を探している読者に、選択の判断材料を与える",
            products=format_products(products),
            count=len(products),
        )
        print("  Claude APIで本文を生成中...")
        raw = claude_api.complete(
            prompt=prompt,
            api_key=common.env("ANTHROPIC_API_KEY"),
            model=config.get("model", "claude-sonnet-4-5"),
            system=SYSTEM_PROMPT,
            max_tokens=config.get("max_tokens", 8000),
        )

    title, description, body = parse_response(raw)
    if not title:
        title = f"{keyword} おすすめ{len(products)}選"

    if "<!--TABLE-->" not in body:
        # 生成が指示を外した場合の保険。表が消えるより末尾に付くほうがまし。
        print("  [警告] <!--TABLE--> が本文にありません。末尾に追加します。")
        body += "\n\n<!--TABLE-->\n"

    # --- 比較表を作る（サイト用とメール用で別々に持つ） ---
    fetched = common.now_jst().strftime("%Y年%m月%d日")
    table_html = hikaku_table.build(
        products, title=f"{keyword} 比較", updated_at=fetched,
        include_style=False,        # CSSはサイト側で1回だけ読み込む
        include_title=False,        # 見出しは本文の「## おすすめ○選 比較表」がある
        include_disclosure=False,   # 広告表記は記事ページ冒頭に出している
    )
    email_table_html = hikaku_table.build_email(products, updated_at=fetched)

    # --- 保存 ---
    slug = entry.get("slug") or common.slugify(keyword, common.today_str())
    draft_id = f"{common.today_str()}-{slug}"
    draft = common.Draft(
        id=draft_id, title=title, keyword=keyword, slug=slug,
        category=entry.get("category", ""),
        body=body, description=description, table_html=table_html,
        email_table_html=email_table_html,
    )
    path = common.write_draft(draft)

    if keywords_data is not None:
        common.mark_keyword(keywords_data, keyword, "drafted")

    missing = draft.placeholders()
    print(f"\nドラフトを保存しました: {path.relative_to(common.ROOT)}")
    print(f"  タイトル: {title}")
    print(f"  未記入欄: {len(missing)}箇所 {missing}")
    # GitHub Actions の後続ステップに draft_id を渡す
    import os
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"draft_id={draft_id}\n")


if __name__ == "__main__":
    main()
