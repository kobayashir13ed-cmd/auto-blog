"""キーワード選定ツール。

    python -m scripts.research score --keyword "モニターアーム おすすめ"
        1件だけ評価して内訳を表示する（お試し用）

    python -m scripts.research scan
        candidates.json の候補をまとめて評価し、スコア順に並べ替える

    python -m scripts.research gsc
        Search Console から実データを取得し、
        リライト候補と新規記事候補を抽出して candidates.json に追記する

    python -m scripts.research promote --top 3
        スコア上位の候補を keywords.json に登録する（記事生成の対象になる）

【運用の順序】
  サイト公開前  … scan で楽天ベースの候補を作り、promote で登録する
  サイト公開後  … gsc を主軸にする。実データに勝る情報はない。
"""

from __future__ import annotations

import argparse
import re
import sys

from . import common
from .kw import gsc, market

CANDIDATES_PATH = common.ROOT / "candidates.json"


def load_candidates() -> dict:
    if not CANDIDATES_PATH.exists():
        return {"candidates": []}
    return common.load_json(CANDIDATES_PATH, required=False) or {"candidates": []}


def save_candidates(data: dict) -> None:
    data["candidates"].sort(key=lambda c: -(c.get("score") or 0))
    common.save_json(CANDIDATES_PATH, data)


def upsert(data: dict, keyword: str, **fields) -> dict:
    for entry in data["candidates"]:
        if entry["keyword"] == keyword:
            entry.update(fields)
            return entry
    entry = {"keyword": keyword, **fields}
    data["candidates"].append(entry)
    return entry


# --------------------------------------------------------------------------
# 表示
# --------------------------------------------------------------------------

def print_score(score: market.MarketScore) -> None:
    print(f"\n  キーワード : {score.keyword}")
    print(f"  総合スコア : {score.total_score} / 100  → {market.verdict(score)}")
    print(f"  {'-' * 56}")
    print(f"  需要（売れている度合い）  {score.demand_score:>5} / 45"
          f"   レビュー計 {score.total_reviews:,}件")
    print(f"  報酬（単価の高さ）        {score.revenue_score:>5} / 30"
          f"   平均 {score.avg_price:,}円")
    print(f"  供給（商品の多さ）        {score.supply_score:>5} / 25"
          f"   {score.product_count:,}件")
    print(f"  {'':>26}{score.base_score:>5} / 100  ← 市場の魅力")
    print(f"  購買意図の係数            ×{score.intent_factor:<4}"
          f"        語数 {score.longtail}")
    for note in score.notes:
        print(f"    ・{note}")


def print_rows(title: str, rows: list[gsc.Row], limit: int = 15) -> None:
    print(f"\n{title}")
    if not rows:
        print("  該当なし")
        return
    # 日本語は全角なので、見出しの空白数は「表示幅」に合わせて調整している
    print(f"  {'順位':>3}  {'表示':>5}  {'クリック':>4}  クエリ / ページ")
    print(f"  {'-' * 62}")
    for row in rows[:limit]:
        key = row.key if len(row.key) <= 42 else row.key[:41] + "…"
        print(f"  {row.position:>5}  {row.impressions:>7,}  {row.clicks:>8,}  {key}")


# --------------------------------------------------------------------------
# サブコマンド
# --------------------------------------------------------------------------

def cmd_score(args: argparse.Namespace) -> None:
    if args.mock:
        from .generate import mock_products
        score = market.score_keyword(args.keyword, 4820, mock_products())
    else:
        score = market.evaluate(args.keyword, common.env("RAKUTEN_APP_ID"))
    print_score(score)


def cmd_scan(args: argparse.Namespace) -> None:
    data = load_candidates()
    pending = [c for c in data["candidates"] if args.all or c.get("score") is None]

    if not pending:
        print("評価対象がありません。candidates.json にキーワードを追加してください。")
        print("（すでに評価済みのものを再評価するには --all を付けます）")
        return

    app_id = "" if args.mock else common.env("RAKUTEN_APP_ID")
    print(f"{len(pending)}件を評価します...\n")

    for entry in pending:
        keyword = entry["keyword"]
        try:
            if args.mock:
                from .generate import mock_products
                score = market.score_keyword(keyword, 4820, mock_products())
            else:
                score = market.evaluate(
                    keyword, app_id, entry.get("search_keyword", "")
                )
        except RuntimeError as exc:
            print(f"  [失敗] {keyword}: {exc}")
            continue

        entry.update({
            "score": score.total_score,
            "verdict": market.verdict(score),
            "detail": score.to_dict(),
            "evaluated_at": common.today_str(),
        })
        print(f"  {score.total_score:>5} / 100  {keyword}")

    save_candidates(data)
    print(f"\n{CANDIDATES_PATH.name} を更新しました（スコア順に並べ替え済み）。")
    print("内訳を見るには candidates.json を開くか、score コマンドを使ってください。")


def cmd_gsc(args: argparse.Namespace) -> None:
    config = common.load_config()

    if args.mock:
        queries, pages = gsc.mock_queries(), gsc.mock_pages()
        print("[モック] サンプルデータで動作を確認しています。\n")
    else:
        site_url = config.get("search_console_site") or config.get("base_url", "")
        if not site_url:
            sys.exit(
                "[エラー] config.json の search_console_site を設定してください。\n"
                "  Search Console に登録したプロパティと完全に同じ文字列にします。\n"
                "  例: https://yourname.github.io/auto-blog/\n"
                "  または sc-domain:example.com"
            )
        credentials = common.env("GSC_CREDENTIALS")
        queries = gsc.query(site_url, credentials, ["query"], days=args.days)
        pages = gsc.query(site_url, credentials, ["page"], days=args.days)
        print(f"直近{args.days}日間のデータを取得しました"
              f"（クエリ{len(queries)}件 / ページ{len(pages)}件）")

    rewrites = gsc.rewrite_candidates(pages, min_impressions=args.min_impressions)
    print_rows("■ リライト候補（8〜30位。1ページ目まであと少し）", rewrites)
    if rewrites:
        print("\n  これらは既に表示されているので、新記事を書くより改善効果が大きいです。")
        print("  content/posts/ の該当記事に、実体験・具体的な数値・不足している見出しを足してください。")

    covered = gsc.covered_keywords()
    fresh = gsc.new_article_candidates(
        queries, covered, min_impressions=args.min_impressions
    )
    print_rows("■ 新規記事の候補（表示はあるが専用記事がない）", fresh)

    if fresh and not args.no_save:
        data = load_candidates()
        added = 0
        for row in fresh[:args.limit]:
            if not any(c["keyword"] == row.key for c in data["candidates"]):
                upsert(data, row.key,
                       source="search-console",
                       impressions=row.impressions,
                       position=row.position,
                       score=None)
                added += 1
        save_candidates(data)
        print(f"\n{added}件を {CANDIDATES_PATH.name} に追加しました。")
        print("  次: python -m scripts.research scan  で市場性を評価してください。")


def overlaps(keyword: str, existing: str) -> bool:
    """2つのキーワードが実質同じ記事になるかを判定する。

    「ゲーミングマウス 軽量」と「ゲーミングマウス 軽量 おすすめ」は
    書く内容がほぼ同じになる。これを別記事として2本出すと、
    Googleがどちらを上位に出すか判断できず両方の順位が下がる
    （キーワードカニバリゼーション）。1本にまとめるほうが強くなる。
    """
    a = set(re.split(r"[\s　]+", keyword.strip()))
    b = set(re.split(r"[\s　]+", existing.strip()))
    if not a or not b:
        return False
    # 片方がもう片方を完全に含んでいれば、同じ記事とみなす
    return a <= b or b <= a


def cmd_promote(args: argparse.Namespace) -> None:
    data = load_candidates()
    scored = [c for c in data["candidates"] if c.get("score") is not None]
    if not scored:
        sys.exit("評価済みの候補がありません。先に scan を実行してください。")

    keywords = common.load_json(common.KEYWORDS_PATH)
    registered = keywords.get("keywords", [])
    existing = {k["keyword"] for k in registered}
    used_slugs = {k.get("slug") for k in registered if k.get("slug")}

    promoted = 0
    auto_slugs = []
    skipped: list[str] = []
    no_category: list[str] = []

    for candidate in scored:
        if promoted >= args.top:
            break
        keyword = candidate["keyword"]
        if keyword in existing:
            continue
        if candidate["score"] < args.min_score:
            continue

        # --- 実質重複の検出 ---
        if not args.force:
            clash = next((e for e in existing if overlaps(keyword, e)), None)
            if clash:
                skipped.append(
                    f"「{keyword}」は「{clash}」とほぼ同じ内容になります。"
                    "2本に分けると共倒れするため、既存記事に内容を足すことを推奨します。")
                continue

        slug = candidate.get("slug") or common.slugify(keyword, common.today_str())

        # --- slug の衝突検出（同じURLだと記事が上書きされる）---
        if slug in used_slugs:
            skipped.append(
                f"「{keyword}」のURL『{slug}』は既に使われています。"
                "candidates.json で別の slug を指定してください。")
            continue

        if slug.startswith("post-"):
            auto_slugs.append((keyword, slug))
        used_slugs.add(slug)

        keywords["keywords"].append({
            "keyword": candidate["keyword"],
            "slug": slug,
            "category": candidate.get("category", ""),
            "search_keyword": candidate.get("search_keyword", ""),
            "intent": candidate.get("intent", ""),
            "hits": 3,
            "status": "pending",
        })
        if not candidate.get("category"):
            no_category.append(keyword)
        candidate["promoted_at"] = common.today_str()
        promoted += 1
        print(f"  登録: {candidate['keyword']}  (スコア {candidate['score']})")

    if skipped:
        print("\n  [見送った候補]")
        for reason in skipped:
            print(f"    ・{reason}")
        if not args.force:
            print("    重複を承知で登録するには --force を付けます"
                  "（URLの衝突は --force でも回避できません）。")

    if promoted == 0:
        print(f"\n登録できる候補がありませんでした"
              f"（--min-score {args.min_score} 以上・重複なしの条件）。")
        return

    common.save_json(common.KEYWORDS_PATH, keywords)
    save_candidates(data)
    print(f"\n{promoted}件を keywords.json に登録しました。")

    if no_category:
        print("\n  [確認してください] 以下はカテゴリが未設定です。")
        print("  keywords.json の category に、config.json で定義した slug を入れてください。")
        for keyword in no_category:
            print(f"    {keyword}")

    if auto_slugs:
        print("\n  [確認してください] 以下はURLが自動生成された値です。")
        print("  日本語キーワードからは意味のあるURLを作れないため、")
        print("  keywords.json を開いて英語の短い語に直すことを推奨します。")
        for keyword, slug in auto_slugs:
            print(f"    {keyword} → {slug}")


# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="research", description="キーワードの選定と評価を行います。")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="キーワードを1件評価する")
    p_score.add_argument("--keyword", required=True)
    p_score.add_argument("--mock", action="store_true")
    p_score.set_defaults(func=cmd_score)

    p_scan = sub.add_parser("scan", help="candidates.json をまとめて評価する")
    p_scan.add_argument("--all", action="store_true", help="評価済みも再評価する")
    p_scan.add_argument("--mock", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_gsc = sub.add_parser("gsc", help="Search Console の実データから候補を出す")
    p_gsc.add_argument("--days", type=int, default=28)
    p_gsc.add_argument("--min-impressions", type=int, default=30)
    p_gsc.add_argument("--limit", type=int, default=20,
                       help="candidates.json に追加する上限件数")
    p_gsc.add_argument("--no-save", action="store_true", help="表示のみで保存しない")
    p_gsc.add_argument("--mock", action="store_true")
    p_gsc.set_defaults(func=cmd_gsc)

    p_promote = sub.add_parser("promote", help="上位候補を keywords.json に登録する")
    p_promote.add_argument("--top", type=int, default=3)
    p_promote.add_argument("--min-score", type=float, default=45.0)
    p_promote.add_argument("--force", action="store_true",
                           help="既存キーワードと内容が重複していても登録する")
    p_promote.set_defaults(func=cmd_promote)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (RuntimeError, ValueError) as exc:
        sys.exit(f"[エラー] {exc}")


if __name__ == "__main__":
    main()
