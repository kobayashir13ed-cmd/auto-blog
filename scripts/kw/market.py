"""キーワードの市場性評価（楽天APIベース）。

【このツールが測れるもの・測れないもの】

測れる（実データ）:
  - そのキーワードの商品数        … 市場が存在するか、飽和していないか
  - 上位商品の総レビュー数        … 実際に売れている証拠。最も信頼できる指標
  - 平均価格                      … 1件成約あたりの報酬額に直結

測れない（無料では取得手段がない）:
  - 検索ボリューム（月に何人が検索したか）
  - 検索結果の競合サイトの強さ

検索ボリュームを正確に知るにはキーワードプランナー（Google広告アカウントが必要）か
有料ツールが要ります。Googleの検索結果をスクレイピングする方法は規約違反なので採りません。

そのため本ツールのスコアは**「売れている商品が多く、単価が高いキーワード」を見つけるもの**
であり、「検索されている数」の指標ではありません。ここを混同しないでください。
実際の検索需要は、記事を公開したあと Search Console（scripts/research/gsc.py）で
実データとして確認するのが唯一確実な方法です。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict, field

from ..hikaku.models import Product
from ..hikaku.providers import rakuten

# 購買意図が強い語。これらを含むキーワードは、情報収集ではなく
# 「買う直前の人」が検索している可能性が高い＝成約しやすい。
INTENT_WORDS = [
    "おすすめ", "比較", "ランキング", "選び方", "人気",
    "安い", "最安", "コスパ", "違い", "どっち",
    "評判", "口コミ", "レビュー", "評価",
]

# 逆に、買う気が薄い（調べているだけの）語
INFO_WORDS = ["とは", "意味", "使い方", "直し方", "無料", "自作", "代用"]


@dataclass
class MarketScore:
    keyword: str
    product_count: int = 0          # 楽天のヒット総数
    total_reviews: int = 0          # 上位商品のレビュー合計
    avg_price: int = 0
    avg_rating: float = 0.0

    demand_score: float = 0.0       # レビュー数から：売れている度合い（0〜45）
    revenue_score: float = 0.0      # 平均価格から：報酬の大きさ（0〜30）
    supply_score: float = 0.0       # 商品数から：ニッチすぎず飽和もしていないか（0〜25）
    base_score: float = 0.0         # 上記3つの合計（0〜100）
    # 購買意図は加点ではなく「係数」にする。情報収集目的のキーワードは、
    # どれだけ商品市場が大きくてもアフィリエイトでは成約しないため、
    # 加点方式だと悪いキーワードが中途半端に高得点になってしまう。
    intent_factor: float = 1.0      # 0.45〜1.0
    total_score: float = 0.0        # base_score × intent_factor

    longtail: int = 0               # 語数。多いほど競合は弱い傾向（あくまで推定）
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _word_count(keyword: str) -> int:
    """検索語の語数を数える。

    日本語の検索クエリは通常スペースで区切って入力されるため、
    区切りの数をそのまま語数とする。
    （文字種の切れ目で数えると「使い方」が3語になるなど過大に出る）

    スペースがない1語の場合だけ、文字数から粗く推定する。
    """
    parts = [p for p in re.split(r"[\s　]+", keyword.strip()) if p]
    if len(parts) > 1:
        return len(parts)
    # 1語のみ：長い複合語（「電動昇降デスク」など）は実質2語相当とみなす
    return 2 if len(keyword.strip()) >= 8 else 1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_keyword(keyword: str, count: int, products: list[Product]) -> MarketScore:
    """取得済みのデータからスコアを計算する（API呼び出しはしない）。"""
    result = MarketScore(keyword=keyword, product_count=count)

    prices = [p.price for p in products if p.price]
    reviews = [p.review_count for p in products if p.review_count]
    ratings = [p.rating for p in products if p.rating is not None]

    result.total_reviews = sum(reviews)
    result.avg_price = int(sum(prices) / len(prices)) if prices else 0
    result.avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    result.longtail = _word_count(keyword)

    # --- 需要（0〜45点）---
    # レビュー総数は桁で効くので対数を取る。1万件で満点。
    if result.total_reviews > 0:
        result.demand_score = _clamp(math.log10(result.total_reviews + 1) / 4 * 45, 0, 45)
    else:
        result.notes.append("レビューが0件。売れている形跡がなく記事にしても成約しにくい。")

    # --- 報酬（0〜30点）---
    # 楽天の料率は数%なので、単価が高いほど1件あたりの報酬が大きい。
    # 価格も桁で効く（3千円と3万円の差は、3万円と6万円の差より大きい）ので対数を使う。
    # 1000円で0点、5万円で満点。
    if result.avg_price > 0:
        ratio = (math.log10(max(result.avg_price, 1000)) - 3) / (math.log10(50000) - 3)
        result.revenue_score = _clamp(ratio * 30, 0, 30)
        if result.avg_price < 2000:
            result.notes.append("平均単価が低く、成約しても報酬がごくわずか。")

    # --- 供給（0〜25点）---
    # 商品が少なすぎると比較記事が作れず、多すぎると競合が多く差別化しにくい。
    # 300〜20000件あたりを山の頂点にする。
    if count <= 0:
        result.notes.append("商品が見つからない。キーワードを見直すこと。")
    elif count < 30:
        result.supply_score = 5
        result.notes.append("商品数が少なすぎて比較記事にしにくい。")
    elif count > 200000:
        result.supply_score = 7
        result.notes.append("商品数が多すぎる。キーワードを絞り込むこと。")
    else:
        # log スケールで 300〜20000 を頂点とする山型
        position = (math.log10(count) - math.log10(300)) / (math.log10(20000) - math.log10(300))
        result.supply_score = _clamp(25 * (1 - abs(position - 0.5) * 2 * 0.6), 0, 25)

    result.base_score = round(
        result.demand_score + result.revenue_score + result.supply_score, 1)

    # --- 購買意図（係数 0.45〜1.0）---
    # ここを加点にすると「市場は大きいが誰も買う気がないキーワード」が
    # 中途半端に高得点になってしまうため、掛け算にして全体を引き下げる。
    hit_intent = [w for w in INTENT_WORDS if w in keyword]
    hit_info = [w for w in INFO_WORDS if w in keyword]
    if hit_info:
        result.intent_factor = 0.45
        result.notes.append(
            f"情報収集目的の語（{'・'.join(hit_info)}）が含まれる。"
            "調べているだけの人が多く、購入に結びつきにくい。")
    elif hit_intent:
        result.intent_factor = 1.0
    else:
        result.intent_factor = 0.8
        result.notes.append("「おすすめ」「比較」などを足すと購買意図が明確になる。")

    # --- ロングテールの注記（スコアには反映しない。実測ではなく推定のため）---
    if result.longtail <= 1:
        result.notes.append("単語1語は競合が非常に強い。立ち上げ期は避けるのが無難（推定）。")
    elif result.longtail >= 3:
        result.notes.append("複合語で競合が弱い可能性がある（推定）。狙い目になりやすい。")

    result.total_score = round(result.base_score * result.intent_factor, 1)
    for name in ("demand_score", "revenue_score", "supply_score"):
        setattr(result, name, round(getattr(result, name), 1))
    return result


def evaluate(keyword: str, application_id: str,
             search_keyword: str = "") -> MarketScore:
    """楽天APIを呼んでスコアを計算する。"""
    count, products = rakuten.search_with_stats(
        keyword=search_keyword or keyword,
        application_id=application_id,
        hits=30,
    )
    return score_keyword(keyword, count, products)


def verdict(score: MarketScore) -> str:
    """スコアの読み方を一言で返す。"""
    if score.total_score >= 60:
        return "有望：優先して記事にする価値がある"
    if score.total_score >= 45:
        return "検討可：他に候補がなければ書く"
    if score.total_score >= 30:
        return "弱い：キーワードを絞り込むか単価の高い商材を探す"
    return "見送り推奨：市場が小さいか購買意図が薄い"
