"""複数のAIに役割を分けて、商品紹介記事を書かせる。

1人のAIに一度に全部書かせると、調べる・決める・書く・直すが混ざって浅くなる。
人間の編集部と同じように役割を分け、前の担当の成果物を次の担当に渡す。

  1. リサーチ担当 … 選ばれた商品の実データを読み、比較の軸と事実を整理する
  2. 企画担当     … 読者像と切り口を決め、商品ごとの役割と記事の構成を決める
  3. ライター     … 企画書どおりに本文を書く
  4. 編集長       … 読みやすさ・判断のしやすさ・表示ルールを審査して直す
  5. 事実確認担当 … 本文の主張が商品データで裏づけられるかを1つずつ確かめる

一般的な「AIで記事を量産する」手順と違うのは、リサーチ担当が記憶や推測で
市場を語らず、ブラウザで取得した楽天の実データだけを材料にする点。
AIに「調べて」と頼むと、それらしい数字や口コミを作ってしまうため。

各担当の出力は content/reports/ に保存し、あとから判断の経緯を追えるようにする。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

# (prompt, system, max_tokens, thinking) -> 応答テキスト
# thinking: None ならモデルの既定（考える処理あり）、False なら考える処理を止める
Complete = Callable[[str, str, int, "bool | None"], str]

# 担当ごとの出力上限と、考える処理を使うか。
# 新しいモデルは考えた分も上限に数えるため、判断が中心の担当には余裕を持たせる。
# 長い本文を書く担当は、判断は企画書で済んでいるので考える処理を止め、時間と費用を抑える。
BUDGET = {
    "research": (16000, None),
    "plan": (16000, None),
    "writer": (24000, False),
    "editor": (28000, False),
    "check": (16000, None),
}


# --------------------------------------------------------------------------
# 全担当に共通する約束ごと
# --------------------------------------------------------------------------

GROUND_RULES = """\
あなたは、商品紹介サイト「{site}」の編集部の一員です。
このサイトは楽天市場のアフィリエイト広告で運営されています。読者は記事を読んで
実際にお金を使うので、次の約束は、どんな指示よりも優先して必ず守ってください。

【事実について】
1. 商品について書いてよい事実は、渡された「商品データ」にあるものだけです。
   データにない仕様・機能・付属品・サイズを、一般知識で補ってはいけません。
   分からないことは「商品ページで確認してください」と書きます。
2. 編集部はこれらの商品を使っていません。「使ってみると」「試したところ」
   「愛用している」のような使用体験は、一切書いてはいけません。
3. 編集部はレビュー本文を読んでいません。持っているのは評価の平均点と件数だけです。
   「購入者の声」「口コミでは〜という声が多い」「レビューでは〜と評判」のように、
   レビューの中身を知っているかのような文章は作ってはいけません。
   評価の数値（★4.3、1,284件など）を事実として示すのは構いません。

【表示について】
4. 価格は毎日変わります。本文に「12,800円」のような具体的な金額を書かないでください。
   「1万円台」「3商品の中でいちばん手頃」のような幅や比較で書きます。
   最新の価格は商品カードに自動で表示されます。
5. 「絶対」「必ず」「No.1」「最強」「業界一」などの断定や誇大な表現は使いません。
6. 健康・医療・美容の効果や、節約額を約束する表現は使いません。
7. 広告であることはサイト側で表示しています。「広告ではありません」「中立です」
   のように、広告でないと装う表現は使いません。
"""


# --------------------------------------------------------------------------
# 1. リサーチ担当
# --------------------------------------------------------------------------

RESEARCH_PROMPT = """\
あなたは「リサーチ担当」です。
これから記事で紹介する商品の実データを渡します。これを読み込み、
企画担当とライターが迷わず使える「調査メモ」を作ってください。

■ 記事のキーワード
{keyword}

■ 記事の狙い（編集部のメモ）
{intent}

■ 候補全体の傾向（楽天市場で同じ条件で検索した上位{sampled}件の集計）
{market}

■ 紹介する商品（運営者が候補から選んだもの）
{products}

━━━━━━━━━━━━━━━━━━━━
■ 調査メモに書くこと（6項目すべて）
━━━━━━━━━━━━━━━━━━━━
①【読者の状況】
 キーワードから考えられる読者の状況と、いちばん困っていること。
 これは推測なので、冒頭に「（推測）」と付けてください。

②【比較の軸】
 これらの商品を比べるときに、差が出る項目を3〜5個挙げてください。
 軸ごとに、各商品の値を「商品1：〇〇（商品説明に記載）」の形で並べます。
 記載がない商品は「記載なし」と書き、推測で埋めないこと。

③【商品ごとの事実】
 商品ごとに、次を箇条書きで整理します。
 ・価格の位置（候補全体の中で高いか安いか、選んだ商品の中で何番目か）
 ・評価の平均点とレビュー件数、その意味（件数が多いほど平均点は信頼できる）
 ・送料の条件
 ・商品説明から読み取れる主な仕様と特徴（数値はそのまま引用）
 ・この商品にしかない点、または弱い点

④【価格と評価の傾向】
 候補全体の集計から言えることを2〜3点。高い商品ほど評価が高いか、など。

⑤【記事で断定できないこと】
 データが足りず、記事では言い切れないこと。読者が商品ページで確認すべき点。

⑥【差別化の切り口】
 よくある「おすすめ〇選」記事にはなく、このデータだからこそ言える視点を3つ。

━━━━━━━━━━━━━━━━━━━━
■ 出力のルール
━━━━━━━━━━━━━━━━━━━━
・見出しと箇条書きで、短く正確に。飾った文章は不要です。
・事実には必ず出典（どの商品のどの項目か）を添えてください。
"""


# --------------------------------------------------------------------------
# 2. 企画担当
# --------------------------------------------------------------------------

PLAN_PROMPT = """\
あなたは「企画担当」です。
リサーチ担当の調査メモをもとに、読者が「これを買えばいいのか」と納得できる
商品紹介記事の企画書を作ってください。

■ 記事のキーワード
{keyword}

■ 紹介する商品（{count}個。番号は変えないこと）
番号は運営者が選んだ順です。先に選んだものほど推したい意向があるかもしれませんが、
1位はデータに基づいて決めてください。
{product_names}

■ リサーチ担当の調査メモ
{research}

━━━━━━━━━━━━━━━━━━━━
■ 企画書に書くこと（すべて必須）
━━━━━━━━━━━━━━━━━━━━
①【記事のひとこと】
 この記事は一言でいうと何か（30字以内）と、読み終えた読者がどうなっているか。

②【想定読者】
 この記事を読む人を1人、具体的に描写します（年代、暮らし、困っている場面、
 何を不安に思って検索したか）。記事の中で実在の人物のように語ることはしません。
 あくまで書き手が読者を思い浮かべるための設定です。

③【読者の迷いと、この記事の答え】
 読者が決めきれずにいる点を2〜3個。それぞれに、この記事がどう答えるか。

④【商品の役割分担】
 商品ごとに「〇〇な人に向いている」を1つずつ割り当て、根拠を調査メモから示します。
 役割が重ならないようにしてください。
 そのうえで「迷ったらこれ」の1位を1つ選び、理由を3点挙げます。
 1位の番号を、行頭に「TOP: 商品番号」の形で1行だけ書いてください（例：TOP: 2）。

⑤【タイトル】
 案を3つ出し、最後に1つ選びます。
 ・32字以内。キーワードの主要な語を自然な日本語で含める
 ・具体的な数字（紹介する商品数など）や、読者の状況を入れる
 ・煽りすぎない（「神」「最強」「絶対」は使わない）

⑥【構成】
 次の骨組みに沿って、見出しと、それぞれで書くことを決めます。
 見出しは、キーワードをそのまま貼り付けたものではなく、自然な日本語にしてください。
   ・リード文（見出しなし）
   ・結論：迷ったらこれ（1位の商品）
   ・比較表
   ・商品ごとの紹介（{count}個。④で決めた順）
   ・選び方のポイント（②の比較の軸を使う）
   ・買う前に確認したいこと
   ・楽天市場のデータから分かること
   ・よくある質問（3〜4問）
   ・まとめ

⑦【企画のまとめ】
 この記事がほかの記事に勝てる理由を3行以内で。
"""


# --------------------------------------------------------------------------
# 3. ライター
# --------------------------------------------------------------------------

WRITER_PROMPT = """\
あなたは「ライター」です。
企画書に従って、商品紹介記事の本文を書いてください。

■ 記事のキーワード
{keyword}

■ 企画書
{plan}

■ リサーチ担当の調査メモ（事実はここと商品データから取ること）
{research}

■ 商品データ
{products}

━━━━━━━━━━━━━━━━━━━━
■ 読みやすさ（とても重要）
━━━━━━━━━━━━━━━━━━━━
このサイトの読者はスマホで、急いで読みます。文字が詰まったページは読まれません。
・1段落は2〜3文まで。1文は60字くらいまで。
・商品ごとの紹介は、次の小見出しを使い、中身は箇条書き中心にします。
    ### こんな人に向いています
    ### 良いところ
    ### 気をつけたいところ
    ### 商品説明から分かる主な仕様
・大事な一文は **太字** にします。多用はしないこと（1セクションに1〜2か所）。
・補足や注意は、行頭を「> 」にした囲み（引用）にします。
    例）> **ポイント**：幅は商品ページの「サイズ」欄で確認できます。
・「良いところ」だけでなく、必ず「気をつけたいところ」も書きます。
  短所がない商品はありません。読者の信頼はここで決まります。

━━━━━━━━━━━━━━━━━━━━
■ 文体
━━━━━━━━━━━━━━━━━━━━
・です・ます調。詳しい友人が説明してくれるような、落ち着いた温度感。
・同じ語尾を3回続けない。「〜することが重要です」「〜が不可欠です」を多用しない。
・「いかがでしたか」「さあ、〜しましょう」「ここで大切なことをお伝えします」は使わない。
・専門用語は、初めて出てくるときに短く言い換える。

━━━━━━━━━━━━━━━━━━━━
■ 差し込み位置（この記号を、そのまま1行で書くこと）
━━━━━━━━━━━━━━━━━━━━
・<!--TOP:n-->     … 結論の見出しの直後に1回。nは1位の商品番号。1位の商品カードが入る
・<!--COMPARE-->   … 比較表の見出しの直後に1回。全商品の比較表が入る
・<!--PRODUCT:n--> … 商品ごとの見出しの直後に1回ずつ。その商品のカードが入る
・<!--STATS-->     … 「楽天市場のデータから分かること」の見出しの直後に1回。集計が入る
カードには商品名・画像・最新価格・評価・購入ボタンが自動で入ります。
本文で同じ情報を繰り返す必要はありません。

━━━━━━━━━━━━━━━━━━━━
■ 分量と出力形式
━━━━━━━━━━━━━━━━━━━━
・本文は全体で5,000〜8,000字。水増しはせず、判断材料で埋めること。
・1行目に「TITLE: 」に続けて企画書で選んだタイトル（32字以内）。
・2行目に「DESC: 」に続けて検索結果に出る説明文（120字以内）。
・3行目以降に本文（Markdown）。見出しは ## と ### を使い、# は使わない。
"""


# --------------------------------------------------------------------------
# 4. 編集長
# --------------------------------------------------------------------------

EDITOR_PROMPT = """\
あなたは「編集長」です。商品紹介記事を何百本も見てきたベテランです。
ライターの原稿を審査し、そのまま公開できる完成版に仕上げてください。

■ 記事のキーワード
{keyword}

■ 商品データ（事実の照合に使う）
{products}

■ 企画書（狙いからズレていないかの確認に使う）
{plan}
{extra}
■ 原稿
{draft}

━━━━━━━━━━━━━━━━━━━━
■ 審査の観点（5つ）
━━━━━━━━━━━━━━━━━━━━
【1. AIっぽさ】
 定番の言い回し、同じ語尾の連続、「まず〜次に〜最後に」の型どおりの並べ方、
 意味のない前置き、誰にでも当てはまるふわっとした表現を、人の言葉に直す。

【2. 読者の迷いが解けるか】
 結論が冒頭近くにあるか。商品ごとの「向いている人」が重ならず、はっきりしているか。
 比較の軸が記事の最初から最後まで一貫しているか。

【3. 買う判断ができるか】
 各商品に「良いところ」と「気をつけたいところ」の両方があるか。
 購入ボタンの前に、判断に必要な材料がそろっているか。

【4. 文章の質】
 誤字脱字、不自然な日本語、長すぎる文、近い場所での言い回しの重複、
 見出しと本文のズレ。スマホで詰まって見える段落は分ける。

【5. 事実と表示のルール】
 商品データにない仕様、使用体験、レビューの中身を知っているような表現、
 具体的な金額、誇大な表現がないか。見つけたら削るか、データに基づく表現に直す。
 差し込み記号（<!--TOP:n--> <!--COMPARE--> <!--PRODUCT:n--> <!--STATS-->）が
 正しい位置に1回ずつあるかも確認する。

━━━━━━━━━━━━━━━━━━━━
■ 出力の形式（この順番で）
━━━━━━━━━━━━━━━━━━━━
REPORT:
（5つの観点それぞれについて、直した点を箇条書きで短く。大きく直した箇所を3つ）
===ARTICLE===
TITLE: （タイトル）
DESC: （説明文）
（完成した本文の全文。省略せずに最後まで）
"""


# --------------------------------------------------------------------------
# 5. 事実確認担当
# --------------------------------------------------------------------------

CHECK_PROMPT = """\
あなたは「事実確認担当」です。公開直前の記事を、商品データと1文ずつ突き合わせます。
読みやすさや表現の好みは見ません。見るのは「事実として正しいか」と「ルール違反か」だけです。

■ 商品データ
{products}

■ 記事
{article}

━━━━━━━━━━━━━━━━━━━━
■ 確認すること
━━━━━━━━━━━━━━━━━━━━
1. 商品の仕様・機能・数値の記述が、その番号の商品データで裏づけられるか
   （商品2の紹介に商品3の仕様が書かれていないか、も含む）
2. 使用体験を書いていないか
3. レビューの中身を知っているかのような記述がないか
4. 具体的な金額を書いていないか（「1万円台」のような幅は可）
5. 「絶対」「必ず」「No.1」などの断定・誇大な表現、効果の約束がないか

━━━━━━━━━━━━━━━━━━━━
■ 出力（JSONのみ。説明文やコードブロックの記号は付けない）
━━━━━━━━━━━━━━━━━━━━
{{"ok": true または false,
  "issues": [
    {{"quote": "記事の該当箇所をそのまま抜き出す",
      "problem": "何が問題か",
      "fix": "どう直すか"}}
  ]}}
問題がなければ {{"ok": true, "issues": []}} だけを返します。
一般的な知識として正しいことでも、商品データにない商品固有の主張は問題として挙げてください。
"""


# --------------------------------------------------------------------------
# 機械的な検査（AIに頼らず確実に見られるもの）
# --------------------------------------------------------------------------

EXPERIENCE_WORDS = [
    "実際に使って", "使ってみると", "使ってみて", "試してみ", "筆者", "私が使",
    "愛用し", "購入して", "使い始めて", "使い続け", "手に取って", "届いてすぐ",
]
REVIEW_WORDS = [
    "購入者の声", "口コミでは", "口コミによると", "レビューでは", "レビューによると",
    "という声", "との声", "利用者からは", "評判です", "と好評",
]
HYPE_WORDS = ["絶対", "必ず", "No.1", "ナンバーワン", "最強", "業界一", "日本一"]
# 「3,000円台」「1万円前後」のような幅は許し、ぴったりの金額だけを拾う
EXACT_PRICE = re.compile(
    r"(?:\d{1,3}(?:,\d{3})+|\d{4,})円(?!台|前後|以下|以上|未満|程度|くらい|ほど|帯|〜|~)")


def lint(body: str, count: int, top: int) -> list[str]:
    """公開してはいけない原稿を機械的に見つける。問題を文章で返す。"""
    issues = []
    for n in range(1, count + 1):
        c = body.count(f"<!--PRODUCT:{n}-->")
        if c != 1:
            issues.append(f"<!--PRODUCT:{n}--> が{c}回あります（1回だけにする）")
    for marker in ("<!--COMPARE-->", "<!--STATS-->"):
        c = body.count(marker)
        if c != 1:
            issues.append(f"{marker} が{c}回あります（1回だけにする）")
    tops = re.findall(r"<!--TOP:(\d+)-->", body)
    if len(tops) != 1:
        issues.append(f"<!--TOP:n--> が{len(tops)}回あります（1回だけにする）")
    elif not 1 <= int(tops[0]) <= count:
        issues.append(f"<!--TOP:{tops[0]}--> の番号が商品の範囲外です")

    chars = len(re.sub(r"<!--.*?-->|\s", "", body))
    if chars < 4000:
        issues.append(f"本文が{chars}字しかありません（5,000字以上にする）")

    for label, words in (("使用体験", EXPERIENCE_WORDS), ("レビューの中身", REVIEW_WORDS),
                         ("誇大な表現", HYPE_WORDS)):
        found = [w for w in words if w in body]
        if found:
            issues.append(f"{label}を示す表現があります：{'、'.join(found)}")
    prices = EXACT_PRICE.findall(body)
    if prices:
        issues.append(f"具体的な金額があります：{'、'.join(sorted(set(prices))[:5])}"
                      "（幅や比較の表現に直す）")
    if re.search(r"^# ", body, flags=re.MULTILINE):
        issues.append("見出しに # が使われています（## と ### だけにする）")
    return issues


# --------------------------------------------------------------------------
# 材料の整形
# --------------------------------------------------------------------------

def yen(n) -> str:
    try:
        return f"{int(n):,}円"
    except (TypeError, ValueError):
        return "不明"


def describe_products(products: list[dict]) -> str:
    blocks = []
    for i, p in enumerate(products, 1):
        rating = p.get("reviewAverage") or 0
        count = p.get("reviewCount") or 0
        blocks.append("\n".join([
            f"[商品{i}]",
            f"商品名: {p.get('itemName', '')}",
            f"価格: {yen(p.get('itemPrice'))}（{p.get('capturedAt', '取得日不明')}時点。毎日変わるので本文には書かない）",
            f"評価: {float(rating):.2f}（レビュー{int(count):,}件）" if count else "評価: レビューなし",
            f"送料: {'無料' if p.get('postageFlag') == 0 else '別（条件は商品ページ）'}",
            f"ショップ: {p.get('shopName', '')}",
            f"キャッチコピー: {p.get('catchcopy', '') or '（なし）'}",
            "商品説明（ショップの記載・抜粋）:",
            p.get("itemCaption", "") or "（なし）",
        ]))
    return "\n\n".join(blocks)


def describe_market(market: dict) -> str:
    if not market:
        return "（集計なし）"
    lines = []
    if market.get("total"):
        lines.append(f"・検索結果の総数：{int(market['total']):,}件")
    if market.get("priceMedian"):
        lines.append(f"・価格の中央値：{yen(market['priceMedian'])}"
                     f"（最安 {yen(market.get('priceMin'))} ／ 最高 {yen(market.get('priceMax'))}）")
    if market.get("ratingAverage"):
        lines.append(f"・評価の平均：{float(market['ratingAverage']):.2f}")
    if market.get("freeShippingRate") is not None:
        lines.append(f"・送料無料の割合：{round(float(market['freeShippingRate']) * 100)}%")
    return "\n".join(lines) or "（集計なし）"


def product_names(products: list[dict]) -> str:
    return "\n".join(f"商品{i}：{p.get('itemName', '')[:60]}" for i, p in enumerate(products, 1))


def parse_article(text: str) -> tuple[str, str, str]:
    """「TITLE: / DESC: / 本文」を分解する。前後に余計な行があっても拾う。"""
    title = desc = ""
    lines = text.strip().splitlines()
    body_start = 0
    for i, line in enumerate(lines[:6]):
        if line.startswith("TITLE:"):
            title, body_start = line[6:].strip(), i + 1
        elif line.startswith("DESC:"):
            desc, body_start = line[5:].strip(), i + 1
    return title, desc, "\n".join(lines[body_start:]).strip()


def parse_top(plan: str, count: int) -> int:
    m = re.search(r"TOP:\s*(?:商品)?\s*(\d+)", plan)
    if m and 1 <= int(m.group(1)) <= count:
        return int(m.group(1))
    return 1


def parse_check(text: str) -> dict:
    """事実確認担当のJSONを読む。壊れていたら「確認できなかった」扱いにする。"""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    try:
        data = json.loads(cleaned[start:end + 1])
        issues = [i for i in data.get("issues", []) if isinstance(i, dict)]
        return {"ok": bool(data.get("ok")) and not issues, "issues": issues}
    except (ValueError, AttributeError):
        return {"ok": False, "issues": [{"quote": "", "problem": "事実確認の結果を読み取れませんでした",
                                         "fix": "人が確認する"}]}


# --------------------------------------------------------------------------
# 本体
# --------------------------------------------------------------------------

@dataclass
class Result:
    title: str
    description: str
    body: str
    top: int
    ok: bool                                   # 公開してよいか
    issues: list[str] = field(default_factory=list)
    reports: dict = field(default_factory=dict)


def write_article(entry: dict, products: list[dict], market: dict,
                  config: dict, complete: Complete, log=print) -> Result:
    """5つの担当を順に動かして記事を仕上げる。"""
    system = GROUND_RULES.format(site=config.get("site_title", "当サイト"))
    keyword = entry["keyword"]
    intent = entry.get("intent") or f"{keyword}で探している読者が、自分に合う商品を選べるようにする"
    facts = describe_products(products)
    count = len(products)
    reports: dict = {}

    log("  [1/5] リサーチ担当が商品データを整理しています")
    research = complete(RESEARCH_PROMPT.format(
        keyword=keyword, intent=intent, market=describe_market(market),
        sampled=market.get("sampled", "数十"), products=facts), system, *BUDGET["research"])
    reports["research"] = research

    log("  [2/5] 企画担当が構成を決めています")
    plan = complete(PLAN_PROMPT.format(
        keyword=keyword, count=count, product_names=product_names(products),
        research=research), system, *BUDGET["plan"])
    reports["plan"] = plan
    top = parse_top(plan, count)

    log("  [3/5] ライターが本文を書いています")
    draft = complete(WRITER_PROMPT.format(
        keyword=keyword, plan=plan, research=research, products=facts), system, *BUDGET["writer"])
    reports["draft"] = draft

    def edit(text: str, extra: str = "") -> tuple[str, str, str, str]:
        out = complete(EDITOR_PROMPT.format(
            keyword=keyword, products=facts, plan=plan, draft=text,
            extra=extra), system, *BUDGET["editor"])
        report, _, article = out.partition("===ARTICLE===")
        if not article.strip():                  # 区切りを書き忘れた場合
            report, article = "", out
        title, desc, body = parse_article(article)
        return report.replace("REPORT:", "").strip(), title, desc, body

    log("  [4/5] 編集長が審査して直しています")
    report, title, desc, body = edit(draft)
    reports["edit"] = report

    # 事実確認と機械検査。問題があれば編集長に1回だけ差し戻す
    problems: list[str] = []
    for attempt in (1, 2):
        log(f"  [5/5] 事実確認担当が確認しています（{attempt}回目）")
        try:
            checked = parse_check(complete(CHECK_PROMPT.format(
                products=facts, article=f"TITLE: {title}\n\n{body}"), system, *BUDGET["check"]))
        except RuntimeError as exc:
            # 確認できなかった記事は公開しない。ただし書き上げた原稿は捨てず、承認待ちに回す
            log(f"        事実確認を実行できませんでした: {exc}")
            problems = lint(body, count, top) + [f"事実確認を実行できませんでした（{exc}）"]
            reports[f"check_{attempt}"] = {"error": str(exc), "lint": lint(body, count, top)}
            break
        problems = lint(body, count, top) + [
            f"「{i.get('quote', '')[:60]}」… {i.get('problem', '')}（→ {i.get('fix', '')}）"
            for i in checked["issues"]]
        reports[f"check_{attempt}"] = {"ai": checked, "lint": lint(body, count, top)}
        if not problems or attempt == 2:
            break
        log(f"        問題が{len(problems)}件あったので編集長に差し戻します")
        extra = ("\n■ 事実確認で見つかった問題（すべて直すこと）\n"
                 + "\n".join(f"- {p}" for p in problems) + "\n")
        try:
            report2, t2, d2, b2 = edit(f"TITLE: {title}\nDESC: {desc}\n{body}", extra)
        except RuntimeError as exc:
            log(f"        差し戻しの修正に失敗しました: {exc}")
            problems.append(f"差し戻しの修正に失敗しました（{exc}）")
            break
        reports["edit_2"] = report2
        if b2:
            title, desc, body = t2 or title, d2 or desc, b2

    return Result(title=title or f"{keyword}で選ぶなら", description=desc, body=body,
                  top=top, ok=not problems, issues=problems, reports=reports)


def market_summary(market: dict) -> dict:
    """選択ページから届いた集計値を、数値として使える形にそろえる。"""
    out = {}
    for key in ("total", "sampled", "priceMedian", "priceMin", "priceMax"):
        try:
            out[key] = int(market.get(key))
        except (TypeError, ValueError):
            pass
    for key in ("ratingAverage", "freeShippingRate"):
        try:
            out[key] = float(market.get(key))
        except (TypeError, ValueError):
            pass
    return out


def fallback_market(products: list[dict]) -> dict:
    """集計が届かなかったとき、選んだ商品だけで最低限の値を作る。"""
    prices = [int(p["itemPrice"]) for p in products if p.get("itemPrice")]
    if not prices:
        return {}
    return {"sampled": len(products), "priceMedian": int(median(prices)),
            "priceMin": min(prices), "priceMax": max(prices)}
