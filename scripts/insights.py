"""公開済み記事の成績を分析し、次の記事の書き方に反映するためのメモを作る。

「分析担当」の仕事。Search Console の実測値（記事ごとの表示回数・掲載順位・
実際に検索された言葉）と、記事そのものの特徴（字数・見出し・タイトル・商品数など）を
突き合わせ、伸びている記事と伸びていない記事の違いを探す。

結果は2つのファイルに保存する。
  content/insights.json … 数字と分析結果（機械が読む）
  content/insights.md   … 人が読むための同じ内容

記事を書く担当（scripts/agents.py）は、企画と執筆のたびに insights.json を読み、
「これまでの記事の成績から分かったこと」として指示に加える。
キーワードの補充（scripts/research.py generate）も同じメモを参考にする。

データが少ないうちは偶然の差を「傾向」と読み違えやすい。分析担当には
データの量と確からしさを必ず書かせ、確からしさが低いうちは
「一般的に検索で評価されやすい書き方」を優先させる。

    python -m scripts.insights               # 分析して保存する
    python -m scripts.insights --max-age 6   # 6日以内に分析済みなら何もしない
    python -m scripts.insights --mock        # Search Console もAIも使わずに流れを確認
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from . import claude_api, common

JSON_PATH = common.CONTENT / "insights.json"
MD_PATH = common.CONTENT / "insights.md"
DAYS = 28

# 表示回数の合計がこれ未満なら、分析は「仮説」扱い。数字の偶然が大きすぎる
CONFIDENT_IMPRESSIONS = 300


# --------------------------------------------------------------------------
# 記事の特徴を数える（AIに頼らず確実に出せるもの）
# --------------------------------------------------------------------------

def features(post: common.Draft, keyword_entry: dict | None) -> dict:
    body = post.body
    text = re.sub(r"<!--.*?-->|\s", "", body)
    h2 = re.findall(r"^## (.+)$", body, flags=re.MULTILINE)
    # 「### Q. 〜」と「**Q. 〜**」の両方の書き方がある
    faq = re.findall(r"^(?:###\s*|\*\*)Q\d*[.．:：\s]", body, flags=re.MULTILINE)
    published = post.published_at or post.created_at
    try:
        age = (common.now_jst().date() - date.fromisoformat(published[:10])).days
    except ValueError:
        age = 0
    return {
        "slug": post.slug,
        "title": post.title,
        "title_chars": len(post.title),
        "keyword": post.keyword,
        "keyword_in_title_head": _keyword_head(post.keyword, post.title),
        "category": post.category,
        "published_at": published[:10],
        "age_days": age,
        "format": "商品紹介" if post.products else "選び方ガイド（旧形式）",
        "products": len(post.products),
        "body_chars": len(text),
        "h2_count": len(h2),
        "h2": h2[:12],
        "faq_count": len(faq),
        "description_chars": len(post.description or ""),
        "peak_month": (keyword_entry or {}).get("peak_month"),
    }


def _keyword_head(keyword: str, title: str) -> bool:
    """キーワードの最初の語がタイトルの前半（16字以内）に入っているか。"""
    words = keyword.split()
    return bool(words) and words[0] in title[:16]


# --------------------------------------------------------------------------
# Search Console の数字を記事に結びつける
# --------------------------------------------------------------------------

def fetch_gsc(config: dict) -> tuple[list, list]:
    from .kw import gsc
    credentials = common.env("GSC_CREDENTIALS", required=False)
    site = config.get("search_console_site", "")
    if not credentials or not site:
        raise RuntimeError("GSC_CREDENTIALS か search_console_site が設定されていません")
    pages = gsc.query(site, credentials, ["page"], days=DAYS)
    pairs = gsc.query(site, credentials, ["page", "query"], days=DAYS)
    return pages, pairs


def mock_gsc(articles: list[dict], base: str) -> tuple[list, list]:
    from .kw.gsc import Row
    pages, pairs = [], []
    for i, a in enumerate(articles[:6]):
        url = f"{base}{a['slug']}/"
        pages.append(Row(url, i % 2, 6 - i, 0.0, 8.0 + i * 5, (url,)))
        pairs.append(Row(url, 0, 2, 0.0, 9.0, (url, a["keyword"].replace(" ", "　"))))
    return pages, pairs


def attach(articles: list[dict], pages: list, pairs: list, base: str) -> None:
    by_url = {r.key: r for r in pages}
    for a in articles:
        url = f"{base}{a['slug']}/"
        r = by_url.get(url)
        a["url"] = url
        a["impressions"] = r.impressions if r else 0
        a["clicks"] = r.clicks if r else 0
        a["position"] = r.position if r else None
        # 公開からの日数で割り、古い記事ほど有利になる偏りを減らす（7日あたりの表示回数）
        window = max(1, min(a["age_days"], DAYS))
        a["impressions_per_week"] = round(a["impressions"] / window * 7, 2)
        a["queries"] = sorted(
            ({"query": p.keys[1], "impressions": p.impressions, "position": p.position}
             for p in pairs if len(p.keys) > 1 and p.keys[0] == url),
            key=lambda q: -q["impressions"])[:8]


def split_groups(articles: list[dict]) -> tuple[list, list, list]:
    """伸びている / 伸びていない / まだ判断できない（公開14日未満）に分ける。"""
    young = [a for a in articles if a["age_days"] < 14]
    judged = sorted((a for a in articles if a["age_days"] >= 14),
                    key=lambda a: (-a["impressions_per_week"], a["position"] or 999))
    if not judged:
        return [], [], young
    cut = max(1, len(judged) // 3)
    growing = [a for a in judged[:cut] if a["impressions"] > 0]
    rest = [a for a in judged if a not in growing]
    return growing, rest, young


def averages(group: list[dict]) -> dict:
    if not group:
        return {}
    def avg(key):
        vals = [a[key] for a in group if isinstance(a.get(key), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {
        "articles": len(group),
        "body_chars": avg("body_chars"),
        "title_chars": avg("title_chars"),
        "h2_count": avg("h2_count"),
        "faq_count": avg("faq_count"),
        "products": avg("products"),
        "keyword_in_title_head": round(
            sum(a["keyword_in_title_head"] for a in group) / len(group) * 100),
        "new_format_share": round(
            sum(a["format"] == "商品紹介" for a in group) / len(group) * 100),
    }


# --------------------------------------------------------------------------
# 分析担当（AI）
# --------------------------------------------------------------------------

ANALYST_PROMPT = """\
あなたは商品紹介サイト「{site}」の「分析担当」です。
公開済みの記事の検索成績（Google Search Console の実測値）と、記事の特徴を渡します。
伸びている記事と伸びていない記事の違いを見つけ、次に書く記事への具体的な指示を作ってください。

■ データの量
・対象期間：直近{days}日
・全記事の表示回数の合計：{total_impressions}回、クリック合計：{total_clicks}回
・記事数：{n_articles}本（うち公開14日未満でまだ判断できない記事：{n_young}本）

■ グループごとの平均
伸びている記事：{growing_avg}
それ以外の記事：{rest_avg}

■ 記事ごとの成績と特徴（JSON）
{articles}

━━━━━━━━━━━━━━━━━━━━
■ 分析のルール
━━━━━━━━━━━━━━━━━━━━
1. データが少ないときは、差を言い切らない。表示回数の合計が{confident}回未満なら
   確からしさは「低」とし、指示は「一般的に検索で評価されやすい書き方」を土台にして、
   データから見えた傾向は「仮説」として控えめに足す。
2. 公開からの日数の差に注意する。古い記事ほど表示が多いのは当たり前なので、
   impressions_per_week（7日あたりの表示回数）で比べる。
3. 掲載順位が5〜15位の記事は「あと一歩」。何が足りないかを特徴から推測する。
4. 実際に検索された言葉（queries）は最重要の材料。記事のキーワードと違う言葉で
   見つけられているなら、それは読者の本当の言い方なので、指示に反映する。
5. 季節（peak_month）の影響を、書き方の良し悪しと混同しない。
6. 指示は具体的に。「質を上げる」ではなく「各商品の節に、商品データの数値を使った
   用途の説明を必ず入れる」のように、ライターがそのまま実行できる形にする。
7. 事実ルール（使用体験・レビュー内容・具体的な金額を書かない）に反する指示は出さない。

━━━━━━━━━━━━━━━━━━━━
■ 出力（JSONのみ。説明文やコードブロックの記号は付けない）
━━━━━━━━━━━━━━━━━━━━
{{"confidence": "低" または "中" または "高",
  "summary": "全体の状況を2〜3文で",
  "growing_traits": ["伸びている記事に共通する特徴（根拠の記事名や数字を添える）", ...],
  "weak_traits": ["伸びていない記事に共通する特徴", ...],
  "plan_rules": ["企画担当への指示（タイトル・構成・切り口）", ...最大6個],
  "writer_rules": ["ライターへの指示（見出し・各節の中身・FAQ）", ...最大6個],
  "keyword_rules": ["次に選ぶキーワードへの指示", ...最大4個],
  "searched_phrases": ["実際に検索された言葉のうち、今後の見出しやFAQに使える言い方", ...最大10個]}}
"""


def analyze(articles: list[dict], growing: list, rest: list, young: list,
            config: dict, complete) -> dict:
    total_imp = sum(a["impressions"] for a in articles)
    total_clk = sum(a["clicks"] for a in articles)
    slim = [{k: a[k] for k in (
        "slug", "title", "keyword", "category", "published_at", "age_days", "format",
        "products", "body_chars", "h2_count", "h2", "faq_count", "title_chars",
        "keyword_in_title_head", "peak_month", "impressions", "clicks", "position",
        "impressions_per_week", "queries")} for a in articles]
    prompt = ANALYST_PROMPT.format(
        site=config.get("site_title", ""), days=DAYS,
        total_impressions=total_imp, total_clicks=total_clk,
        n_articles=len(articles), n_young=len(young),
        growing_avg=json.dumps(averages(growing), ensure_ascii=False),
        rest_avg=json.dumps(averages(rest), ensure_ascii=False),
        articles=json.dumps(slim, ensure_ascii=False, indent=1),
        confident=CONFIDENT_IMPRESSIONS)
    text = complete(prompt)
    result = _parse_json(text)
    # データ量に対してAIが強気すぎる判定をしても、下限は機械的に守る
    if total_imp < CONFIDENT_IMPRESSIONS:
        result["confidence"] = "低"
    result.update(total_impressions=total_imp, total_clicks=total_clk)
    return result


def _parse_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"分析結果をJSONとして読めませんでした:\n{text[:300]}")
    data = json.loads(cleaned[start:end + 1])
    for key in ("growing_traits", "weak_traits", "plan_rules", "writer_rules",
                "keyword_rules", "searched_phrases"):
        data[key] = [str(x) for x in data.get(key) or []][:10]
    data["confidence"] = str(data.get("confidence") or "低")
    data["summary"] = str(data.get("summary") or "")
    return data


def mock_complete(prompt: str) -> str:
    return json.dumps({
        "confidence": "低", "summary": "モックの分析です。",
        "growing_traits": ["表示が多い記事は掲載順位が10位前後"],
        "weak_traits": ["表示がない記事は公開から日が浅い"],
        "plan_rules": ["タイトルの前半にキーワードの主要な語を置く"],
        "writer_rules": ["FAQを5問以上にし、実際に検索された言い方を質問文に使う"],
        "keyword_rules": ["表示が出ているカテゴリの近い悩みを優先する"],
        "searched_phrases": ["賃貸 結露 対策"]}, ensure_ascii=False)


# --------------------------------------------------------------------------
# 記事を書く担当・キーワード補充に渡す形
# --------------------------------------------------------------------------

def load() -> dict:
    try:
        return json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def for_prompt(part: str) -> str:
    """プロンプトに差し込む文章。part は "plan" / "writer" / "keyword"。

    分析がまだない、または確からしさが低いときは、その旨を明記して渡す。
    担当がデータの弱い傾向を絶対のルールと受け取らないようにするため。
    """
    data = load().get("analysis") or {}
    rules = data.get(f"{part}_rules") or []
    if not rules:
        return "（まだ分析できるだけのデータがありません。一般的に検索で評価されやすい書き方を優先してください）"
    head = (f"確からしさ：{data.get('confidence', '低')}"
            f"（直近{DAYS}日の表示回数 合計{data.get('total_impressions', 0)}回）")
    if data.get("confidence") == "低":
        head += "\n※データが少ないため、以下は仮説です。ほかの指示や基本方針と矛盾する場合は、そちらを優先してください。"
    lines = [head] + [f"・{r}" for r in rules]
    phrases = data.get("searched_phrases") or []
    if part in ("plan", "writer") and phrases:
        lines.append("・実際に検索された言い方（見出しやFAQの言葉選びの参考に）："
                     + "／".join(phrases))
    return "\n".join(lines)


def to_markdown(report: dict) -> str:
    a = report.get("analysis") or {}
    out = [f"# 記事の成績の分析（{report.get('generated_at', '')}）", "",
           f"確からしさ：**{a.get('confidence', '-')}**　"
           f"直近{DAYS}日の表示 {a.get('total_impressions', 0)}回 / "
           f"クリック {a.get('total_clicks', 0)}回", "", a.get("summary", ""), ""]
    for title, key in (("伸びている記事の特徴", "growing_traits"),
                       ("伸びていない記事の特徴", "weak_traits"),
                       ("企画担当への指示", "plan_rules"),
                       ("ライターへの指示", "writer_rules"),
                       ("キーワード選びへの指示", "keyword_rules"),
                       ("実際に検索された言い方", "searched_phrases")):
        out += [f"## {title}", ""] + [f"- {x}" for x in a.get(key) or ["（なし）"]] + [""]
    out += ["## 記事ごとの成績", "",
            "| 記事 | 公開 | 表示 | 7日あたり | 順位 | 本文字数 | FAQ |",
            "|---|---|---|---|---|---|---|"]
    for r in sorted(report.get("articles", []), key=lambda r: -r["impressions_per_week"]):
        pos = f"{r['position']:.1f}" if r.get("position") else "-"
        out.append(f"| {r['slug']} | {r['published_at']} | {r['impressions']} | "
                   f"{r['impressions_per_week']} | {pos} | {r['body_chars']} | {r['faq_count']} |")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# 本体
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="記事の成績を分析して、書き方の指示を更新する")
    parser.add_argument("--max-age", type=int, default=0,
                        help="この日数以内に分析済みなら何もしない（0なら毎回分析する）")
    parser.add_argument("--mock", action="store_true", help="外部サービスを使わずに流れを確認する")
    args = parser.parse_args(argv)

    previous = load()
    if args.max_age and previous.get("generated_at"):
        try:
            age = (common.now_jst().date() - date.fromisoformat(previous["generated_at"])).days
        except ValueError:
            age = args.max_age + 1
        if age < args.max_age:
            print(f"{age}日前に分析済みです（{args.max_age}日ごとに更新）。何もしません。")
            return

    from . import build_site
    config = common.load_config()
    base = config.get("base_url", "").rstrip("/") + config.get("path_prefix", "/")
    keywords = {e.get("slug"): e for e in common.load_json(common.KEYWORDS_PATH).get("keywords", [])}
    articles = [features(p, keywords.get(p.slug)) for p in build_site.load_posts()]
    if not articles:
        print("公開済みの記事がないので、分析しません。")
        return

    try:
        pages, pairs = mock_gsc(articles, base) if args.mock else fetch_gsc(config)
    except Exception as exc:                        # noqa: BLE001
        # 分析は記事作りの補助。取れなければ前回の分析をそのまま使い続ける
        print(f"[注意] Search Console から数字を取得できませんでした: {exc}")
        print("       前回の分析をそのまま使います。")
        return
    attach(articles, pages, pairs, base)
    growing, rest, young = split_groups(articles)

    if args.mock:
        complete = mock_complete
    else:
        api_key = common.env("ANTHROPIC_API_KEY")
        model = config.get("agent_model") or config.get("model", "claude-sonnet-5")
        def complete(prompt: str) -> str:
            return claude_api.complete(prompt=prompt, api_key=api_key, model=model,
                                       max_tokens=16000, timeout=600)
    try:
        analysis = analyze(articles, growing, rest, young, config, complete)
    except Exception as exc:                        # noqa: BLE001
        print(f"[注意] 分析に失敗しました: {exc}")
        print("       前回の分析をそのまま使います。")
        return

    report = {
        "generated_at": common.today_str(),
        "days": DAYS,
        "growing": [a["slug"] for a in growing],
        "young": [a["slug"] for a in young],
        "averages": {"growing": averages(growing), "rest": averages(rest)},
        "analysis": analysis,
        "articles": articles,
    }
    common.save_json(JSON_PATH, report)
    MD_PATH.write_text(to_markdown(report), encoding="utf-8")
    print(f"分析しました（確からしさ：{analysis['confidence']}、"
          f"表示 合計{analysis['total_impressions']}回）。")
    print(f"  伸びている記事: {', '.join(report['growing']) or 'まだなし'}")
    for r in analysis.get("writer_rules", [])[:3]:
        print(f"  ライターへ: {r}")


if __name__ == "__main__":
    main(sys.argv[1:])
