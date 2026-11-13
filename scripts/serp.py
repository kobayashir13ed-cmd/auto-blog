"""競合分析担当：同じキーワードで検索上位に出ている記事を読み、何が評価されているかを調べる。

記事を書く前に、キーワードでウェブ検索し、上位の記事を数本読んで
  ・上位の記事がそろって扱っている論点（読者が当然知りたいこと）
  ・上位の記事に欠けている切り口（このサイトが差をつけられるところ）
  ・タイトルや見出しの傾向
を整理する。企画担当とライターはこれを読んでから構成を決める。

守ること
  ・競合の文章や見出しをそのまま使わない。扱う「論点」と「構成の傾向」だけを学ぶ。
  ・競合の記事に書かれた商品の情報は、事実として記事に使わない（商品の事実は商品データだけ）。
  ・ここで使う検索は Claude API のウェブ検索で、Google の順位そのものではない。
    ただ、上位に出る記事の傾向をつかむには十分。

失敗しても記事は書ける。分析なしで、今までどおりの流れに戻る。
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from . import official

# 記事ではないページ（通販の商品ページ・SNS・動画）と、自分のサイトは読まない
BLOCKED_DOMAINS = [
    "rakuten.co.jp", "amazon.co.jp", "amazon.com", "shopping.yahoo.co.jp",
    "paypaymall.yahoo.co.jp", "qoo10.jp", "mercari.com", "auctions.yahoo.co.jp",
    "youtube.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
    "facebook.com", "mekikilab.com",
]
MAX_ITEMS = 8


SERP_PROMPT = """\
あなたは商品紹介サイトの「競合分析担当」です。
これから書く記事のキーワードで検索し、上位に出てくる記事を読んで、
どんな記事が読者と検索エンジンに評価されているかを分析してください。

■ キーワード
{keyword}

━━━━━━━━━━━━━━━━━━━━
■ 手順
━━━━━━━━━━━━━━━━━━━━
1. キーワードをそのままウェブ検索する。
2. 結果のうち、商品を比べたり選び方を説明したりしている「記事」を上から3〜4本選び、
   それぞれを取得（web_fetch）して読む。通販の商品ページ、SNS、動画は読まない。
3. 読んだ記事について、タイトル、## にあたる見出し、紹介している商品の数、
   ほかの記事にない切り口を整理する。
4. 読んだ記事全体から、次をまとめる。
   ・どの記事もそろって扱っている論点（このキーワードで読者が当然知りたいこと）
   ・どの記事も扱っていない、または浅い論点（差をつけられるところ）
   ・タイトルの付け方の傾向（数字・疑問形・読者の状況の書き方など）
   ・記事の中で答えている、読者の具体的な疑問

■ 守ること
・競合の文章や見出しを、そのまま写して使う前提でまとめない。論点を自分の言葉で要約する。
・競合が書いている商品の性能や評判は、まとめに含めない（このサイトでは使えないため）。

━━━━━━━━━━━━━━━━━━━━
■ 出力（最後にJSONだけを書く。前置きは不要）
━━━━━━━━━━━━━━━━━━━━
{{"articles": [{{"url": "読んだ記事のURL", "title": "タイトル",
                 "headings": ["見出しの要約", ...], "products": 紹介商品数,
                 "angle": "この記事ならではの切り口"}}],
  "must_cover": ["そろって扱っている論点", ...],
  "gaps": ["扱われていない・浅い論点", ...],
  "title_patterns": ["タイトルの傾向", ...],
  "questions": ["読者の具体的な疑問", ...]}}
"""


def tools(config: dict) -> tuple[list[dict], list[str]]:
    conf = {**official.DEFAULT_TOOLS, **(config.get("web_tools") or {})}
    return [
        {"type": conf["search"], "name": "web_search", "max_uses": 2,
         "blocked_domains": BLOCKED_DOMAINS},
        # 記事の本文は長いが、見出しと論点がつかめれば十分なので取得量を絞る
        {"type": conf["fetch"], "name": "web_fetch", "max_uses": 4,
         "blocked_domains": BLOCKED_DOMAINS, "max_content_tokens": 8000},
    ], list(conf.get("betas") or [])


def _parse(text: str) -> dict:
    start, end = text.rfind('{"articles"'), text.rfind("}")
    if start == -1:
        start = text.find("{")
    if start == -1 or end == -1:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _strings(items, limit: int, length: int = 120) -> list[str]:
    return [str(x).strip()[:length] for x in (items or []) if str(x).strip()][:limit]


def validate(text: str, fetched: dict, log=print) -> dict:
    """実際に読んだ記事だけを残す。1本も読めていなければ空を返す。"""
    data = _parse(text)
    read = {u.rstrip("/") for u in fetched}
    articles = []
    for a in data.get("articles") or []:
        if not isinstance(a, dict):
            continue
        url = str(a.get("url") or "").strip()
        if url.rstrip("/") not in read:
            continue
        articles.append({
            "url": url, "domain": urlparse(url).hostname or "",
            "title": str(a.get("title") or "")[:100],
            "headings": _strings(a.get("headings"), 12, 60),
            "products": a.get("products") if isinstance(a.get("products"), int) else None,
            "angle": str(a.get("angle") or "")[:150],
        })
    if not articles:
        log("        上位の記事を読めなかったので、競合分析なしで進めます")
        return {}
    result = {
        "articles": articles[:5],
        "must_cover": _strings(data.get("must_cover"), MAX_ITEMS),
        "gaps": _strings(data.get("gaps"), MAX_ITEMS),
        "title_patterns": _strings(data.get("title_patterns"), 5),
        "questions": _strings(data.get("questions"), MAX_ITEMS),
    }
    log(f"        上位の記事を{len(articles)}本読みました"
        f"（そろって扱う論点{len(result['must_cover'])}個、差をつけられる論点{len(result['gaps'])}個）")
    return result


def analyze(keyword: str, config: dict, call, log=print) -> dict:
    """call(prompt, tools, betas) -> (text, fetched)。失敗しても空を返す。"""
    if not config.get("serp_analysis", True):
        return {}
    tool_defs, betas = tools(config)
    try:
        text, fetched = call(SERP_PROMPT.format(keyword=keyword), tool_defs, betas)
    except Exception as exc:                        # noqa: BLE001
        log(f"        競合分析をできませんでした: {str(exc)[:200]}")
        return {}
    return validate(text, fetched, log)


def for_prompt(result: dict) -> str:
    """企画担当・ライターに渡す文章。"""
    if not result:
        return "（今回は競合の分析がありません。基本方針どおりに企画してください）"
    lines = [f"検索上位の記事を{len(result['articles'])}本読んだ結果です。"
             "論点と構成の傾向だけを参考にし、文章や見出しは真似しないでください。"
             "競合に書かれた商品の情報は、事実として使わないでください。"]
    for title, key in (("上位の記事がそろって扱っている論点（この記事でも必ず答える）", "must_cover"),
                       ("上位の記事に欠けている・浅い論点（この記事で差をつける）", "gaps"),
                       ("読者の具体的な疑問", "questions"),
                       ("上位の記事のタイトルの傾向", "title_patterns")):
        if result.get(key):
            lines.append(f"【{title}】")
            lines += [f"・{x}" for x in result[key]]
    sizes = [a["products"] for a in result["articles"] if a.get("products")]
    if sizes:
        lines.append(f"【参考】上位の記事が紹介している商品数：{'、'.join(map(str, sizes))}個")
    return "\n".join(lines)
