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
from .hikaku import widget

# --------------------------------------------------------------------------
# プロンプト
# --------------------------------------------------------------------------

SYSTEM_PROMPT = """\
あなたは日本語の商品選びガイド記事を書く編集者です。次の原則を必ず守ってください。

1. 具体的な商品名・型番・メーカー名を書かない。
   記事に並ぶ実際の商品は、読者がページを開いた時点で自動取得されるため、
   あなたには何が表示されるか分からない。存在しない商品を書くと嘘になる。
2. 価格を断定しない。「〇〇円です」ではなく「〇〇円台から選べます」のように幅で書く。
3. 誇大な断定を避ける。「絶対に」「必ず」「No.1」は使わない。
4. 健康・医療・金銭的効果に関する主張はしない。
5. 読者が自分で判断できる基準を書く。何を見て選べばよいかを具体的に示す。
6. 検索順位のための水増しをしない。内容のない一般論で文字数を稼がない。

あなたが書くべきは「どう選ぶか」であって「どれを買うか」ではありません。
"""

USER_PROMPT = """\
次の条件で日本語の商品選びガイド記事をMarkdownで書いてください。

## キーワード
{keyword}

## 記事の狙い
{intent}

## 比較表について
記事中の `<!--TABLE-->` の位置には、読者がページを開いた時点で
楽天市場から取得した実際の商品一覧（商品名・価格・レビュー評価）が
自動で表示されます。**あなたは具体的な商品を書く必要はありませんし、書いてもいけません。**
あなたの仕事は、読者がその一覧を見たときに「どれを選べばよいか判断できる基準」を
先に与えることです。

## 必須の構成
以下の見出し構成に厳密に従ってください。

```
（リード文：2〜3文。読者の悩みを言い当てる。見出しなし）

## {keyword}の選び方

（判断基準を3つ。それぞれ小見出し `### ` を付けて3〜4文ずつ。
　「何を見るべきか」「どの数値がどういう意味を持つか」を具体的に書く）

## 失敗しやすいポイント

（2つ。`### ` を付けて。買ってから後悔しがちな点を、理由とともに説明する）

## 現在の人気商品

（1〜2文の導入。「以下は楽天市場のレビュー数が多い順の一覧です」のように、
　表が何を示しているかを説明する）

<!--TABLE-->

## 実際に使ってみて

{{{{実体験}}}}

## 購入前に知っておきたい注意点

{{{{注意点}}}}

## まとめ

（3〜4文。どういう人がどういう基準で選ぶとよいかを整理する。
　特定の商品名は挙げない）

## よくある質問

（Q&A形式で3組。`### Q. ` と回答。読者が実際に疑問に思うことを扱う）
```

## 厳守事項
- **具体的な商品名・型番・メーカー名を一切書かない**
- 価格は幅で書く（「5000円前後から」など）。断定しない
- `<!--TABLE-->` は必ずそのまま1行で残すこと
- `{{{{実体験}}}}` と `{{{{注意点}}}}` は**そのまま残すこと**。ここは人間が後で書きます。
  あなたが埋めてはいけません
- 記事タイトルは出力しない（本文のみ）
- 全体で2000〜2800字程度

## 出力形式
1行目に「TITLE: 」に続けて記事タイトル（32文字以内、キーワードを含む）。
2行目に「DESC: 」に続けてメタディスクリプション（120文字以内）。
3行目以降に本文Markdown。
"""


# --------------------------------------------------------------------------
# モック（APIキーなしの動作確認用）
# --------------------------------------------------------------------------

MOCK_BODY = """\
TITLE: 軽量ゲーミングマウスの選び方【2026年版】
DESC: 軽量ゲーミングマウスを選ぶときに見るべき3つの基準と、買ってから後悔しやすい点を整理しました。
長時間のプレイで手首が疲れる、という悩みは重量で解決できることが多いです。\
ただし軽ければ良いというものでもなく、接続方式との組み合わせで使い勝手は大きく変わります。\
ここでは選ぶときに見るべき基準を整理します。

## 軽量ゲーミングマウスの選び方

### 重量は80gを境に体感が変わる

80g以下だと長時間でも疲れにくくなります。ただし軽すぎると細かい制御がしにくいと\
感じる人もいます。商品ページに重量の記載があるか、まず確認してください。\
記載がない製品は、実測値がばらつくことがあります。

### 接続方式は用途で決める

遅延を最優先するなら有線、取り回しを優先するなら2.4GHz無線が無難です。\
Bluetoothは省電力ですが反応速度では劣ります。\
無線の場合は電池式か充電式かも確認しておくと、後の運用が楽になります。

### 価格帯は3000円台から

3000円台でも十分実用的です。1万円近い製品との差は、主にボタン数と\
カスタマイズ性、センサーの精度にあります。\
用途が決まっていないうちは、中価格帯から試すほうが失敗しにくいでしょう。

## 失敗しやすいポイント

### 軽さだけで選んでしまう

軽い個体は机の上で滑りやすく、マウスパッドとの相性が出ます。\
重量の数字だけを見て選ぶと、かえって操作精度が落ちることがあります。

### レビュー件数の少ない製品を選んでしまう

レビューが数件しかない製品は、当たり外れの判断材料が不足しています。\
同じ価格帯なら、レビュー件数が多いものから検討するほうが安全です。

## 現在の人気商品

以下は楽天市場で「ゲーミングマウス 軽量」を検索し、レビュー件数が多い順に並べたものです。\
価格と評価はこのページを開いた時点の最新情報です。

<!--TABLE-->

## 実際に使ってみて

{{実体験}}

## 購入前に知っておきたい注意点

{{注意点}}

## まとめ

重量・接続方式・価格帯の3点を先に決めておくと、選択肢はかなり絞れます。\
長時間の作業が中心なら軽さを、対戦ゲームが中心なら遅延の少なさを優先してください。\
どれも決めかねる場合は、レビュー件数が多く中価格帯のものから試すのが無難です。\
なお価格は変動するため、購入前に販売ページで最新の価格を確認してください。

## よくある質問

### Q. 軽いマウスは壊れやすいですか？

重量と耐久性に直接の相関はありません。\
ただし軽量化のために筐体を薄くしている製品はあるため、保証期間を確認してください。

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

    # --- 本文を生成 ---
    # 商品データはサーバーからは取得しない（楽天APIがRefererを要求するため）。
    # 実際の商品一覧は、読者がページを開いた時点でブラウザが取りに行く。
    hits = int(entry.get("hits") or config.get("products_per_post", 3))

    if args.mock:
        raw = MOCK_BODY
    else:
        prompt = USER_PROMPT.format(
            keyword=keyword,
            intent=entry.get("intent") or f"{keyword}を探している読者に、選択の判断材料を与える",
        )
        print("  Claude APIで本文を生成中...")
        raw = claude_api.complete(
            prompt=prompt,
            api_key=common.env("ANTHROPIC_API_KEY"),
            model=config.get("model", "claude-sonnet-5"),
            system=SYSTEM_PROMPT,
            max_tokens=config.get("max_tokens", 8000),
        )

    title, description, body = parse_response(raw)
    if not title:
        title = f"{keyword}の選び方"

    if "<!--TABLE-->" not in body:
        # 生成が指示を外した場合の保険。表が消えるより末尾に付くほうがまし。
        print("  [警告] <!--TABLE--> が本文にありません。末尾に追加します。")
        body += "\n\n<!--TABLE-->\n"

    # --- 比較表の置き場所（中身はブラウザが埋める） ---
    table_html = widget.placeholder(
        keyword=entry.get("search_keyword") or keyword,
        hits=hits,
        min_price=entry.get("min_price"),
        max_price=entry.get("max_price"),
    )

    # --- 保存 ---
    slug = entry.get("slug") or common.slugify(keyword, common.today_str())
    draft_id = f"{common.today_str()}-{slug}"
    draft = common.Draft(
        id=draft_id, title=title, keyword=keyword, slug=slug,
        category=entry.get("category", ""),
        body=body, description=description, table_html=table_html,
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
