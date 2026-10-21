"""仕様確認担当：選ばれた商品の仕様を、メーカー公式サイトで確かめる。

楽天の商品説明はショップが書いたもので、サイズや付属品などが抜けていることが多い。
そこで、商品名から「メーカー名と型番」を特定し、メーカー公式サイトの製品ページを
ウェブ検索で探して、書かれている仕様だけを出典つきで取り出す。

ここで扱うのは仕様（事実）だけ。レビュー・口コミ・価格は取らない。
レビュー本文は書いた人の文章であり、多くのサイトで機械的な収集が禁止されているため。

AIが「見ていないページ」や「別の型番のページ」を出典にしないよう、次を機械的に確かめる。
  1. 出典のURLが、実際に取得されたページの中にあること
  2. 型番が、楽天の商品名・説明の中にあること（この商品の型番であること）
  3. 取得したページの本文に、型番が書かれていること
  4. 通販モール・比較サイト・ブログなど、メーカー以外のサイトでないこと
どれか1つでも満たさない結果は捨てる。仕様が取れなくても記事は今までどおり書ける。
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from . import common

# メーカー公式ではないサイト。検索の対象からも外す
BLOCKED_DOMAINS = [
    "rakuten.co.jp", "rakuten.com", "amazon.co.jp", "amazon.com", "shopping.yahoo.co.jp",
    "paypaymall.yahoo.co.jp", "kakaku.com", "mybest.com", "monotaro.com", "biccamera.com",
    "yodobashi.com", "joshinweb.jp", "askul.co.jp", "lohaco.yahoo.co.jp", "qoo10.jp",
    "mercari.com", "auctions.yahoo.co.jp", "note.com", "ameblo.jp", "hatenablog.com",
    "youtube.com", "x.com", "twitter.com", "instagram.com", "tiktok.com",
]

DEFAULT_TOOLS = {
    "search": "web_search_20250305",
    "fetch": "web_fetch_20250910",
    "betas": ["web-fetch-2025-09-10"],
}

MAX_SPECS = 20


SPEC_PROMPT = """\
あなたは商品紹介サイトの「仕様確認担当」です。
楽天市場で選ばれた商品について、メーカー公式サイトに書かれている仕様を確かめてください。

■ 商品（楽天市場のショップが書いた商品名と説明）
{products}

━━━━━━━━━━━━━━━━━━━━
■ 手順（商品ごとに）
━━━━━━━━━━━━━━━━━━━━
1. 商品名と説明から、メーカー名と型番（例：EGL-C1281、PCM-N080）を特定する。
   型番が書かれていない商品（ノーブランド品など）は、調べずに飛ばす。
2. 「メーカー名 型番」でウェブ検索し、メーカー自身の公式サイト（またはメーカー直営の
   公式ストア）の、その型番の製品ページを探す。
   通販モール、量販店、比較サイト、ブログ、動画は使わない。
3. 見つけたページを取得（web_fetch）し、型番が一致していることを本文で確かめる。
   色違い以外で型番が違う場合（後継機・旧型など）は使わない。
4. 製品ページに書かれている仕様だけを取り出す。
   取り出してよいもの：サイズ、重さ、容量、消費電力、電源、材質、付属品、対応機種・規格、
   機能の有無、保証期間、運転音などの数値（メーカーが公表している値として）
   取り出してはいけないもの：レビュー・口コミ・評価、価格、「快適」「おすすめ」などの宣伝文句
5. ページに書かれていない項目は推測で埋めない。

━━━━━━━━━━━━━━━━━━━━
■ 出力（最後にJSONだけを書く。前置きは不要）
━━━━━━━━━━━━━━━━━━━━
{{"products": [
  {{"n": 商品番号,
    "maker": "メーカー名",
    "model": "型番（楽天の商品名・説明に書かれている表記のまま）",
    "source_url": "取得した公式ページのURL",
    "source_title": "そのページのタイトル",
    "specs": [{{"name": "項目名", "value": "ページに書かれている値"}}],
    "note": "楽天の商品説明と食い違う点があれば書く。なければ空"}}
]}}
見つからなかった商品は配列に入れません。1つも見つからなければ {{"products": []}} です。
"""


def tools(config: dict) -> tuple[list[dict], list[str]]:
    conf = {**DEFAULT_TOOLS, **(config.get("web_tools") or {})}
    return [
        {"type": conf["search"], "name": "web_search", "max_uses": 8,
         "blocked_domains": BLOCKED_DOMAINS},
        {"type": conf["fetch"], "name": "web_fetch", "max_uses": 8,
         "blocked_domains": BLOCKED_DOMAINS, "max_content_tokens": 20000},
    ], list(conf.get("betas") or [])


def build_prompt(products: list[dict]) -> str:
    blocks = []
    for i, p in enumerate(products, 1):
        blocks.append(f"[商品{i}]\n商品名: {p.get('itemName', '')}\n"
                      f"説明（抜粋）: {(p.get('itemCaption') or '')[:600]}")
    return SPEC_PROMPT.format(products="\n\n".join(blocks))


# --------------------------------------------------------------------------
# 結果の検査
# --------------------------------------------------------------------------

def _norm(text: str) -> str:
    """型番の照合用。全角・大文字小文字・記号の違いを無視する。"""
    import unicodedata
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[\s\-‐－_/・.]", "", text)


def _domain_ok(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    return not any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def _parse(text: str) -> list[dict]:
    start, end = text.rfind('{"products"'), text.rfind("}")
    if start == -1:
        start = text.find("{")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    items = data.get("products") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def validate(text: str, fetched: dict, products: list[dict], log=print) -> dict:
    """AIの答えを検査し、使えるものだけを {商品番号: 仕様} で返す。"""
    fetched_norm = {u.rstrip("/"): body for u, body in fetched.items()}
    found: dict[int, dict] = {}
    for item in _parse(text):
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(products) or n in found:
            continue
        url = str(item.get("source_url") or "").strip()
        model = str(item.get("model") or "").strip()
        p = products[n - 1]
        why = ""
        if not model or len(_norm(model)) < 4:
            why = "型番が特定できていない"
        elif _norm(model) not in _norm(p.get("itemName", "") + p.get("itemCaption", "")):
            why = f"型番 {model} が楽天の商品名・説明にない"
        elif not _domain_ok(url):
            why = f"メーカー公式ではないサイト（{url[:60]}）"
        elif url.rstrip("/") not in fetched_norm:
            why = "実際に取得されていないページを出典にしている"
        elif fetched_norm[url.rstrip("/")] and _norm(model) not in _norm(fetched_norm[url.rstrip("/")]):
            why = "取得したページに型番が書かれていない"
        specs = []
        for s in item.get("specs") or []:
            if isinstance(s, dict) and s.get("name") and s.get("value"):
                name, value = str(s["name"]).strip()[:40], str(s["value"]).strip()[:160]
                if "円" in value:                     # 価格は扱わない
                    continue
                specs.append({"name": name, "value": value})
        if not why and not specs:
            why = "仕様が1つも取り出せていない"
        if why:
            log(f"        商品{n}: 公式の仕様は使いません（{why}）")
            continue
        found[n] = {
            "maker": str(item.get("maker") or "")[:40],
            "model": model[:40],
            "source_url": url,
            "source_title": str(item.get("source_title") or "")[:100] or url,
            "specs": specs[:MAX_SPECS],
            "note": str(item.get("note") or "")[:200],
            "checked_at": common.today_str(),
        }
        log(f"        商品{n}: {found[n]['maker']} {model} の公式ページで仕様を{len(found[n]['specs'])}項目確認")
    return found


def lookup(products: list[dict], config: dict, call, log=print) -> dict:
    """call(prompt, tools, betas) -> (text, fetched)。失敗しても空の結果を返す。"""
    if not config.get("official_specs", True):
        return {}
    tool_defs, betas = tools(config)
    try:
        text, fetched = call(build_prompt(products), tool_defs, betas)
    except Exception as exc:                        # noqa: BLE001
        # 仕様確認は記事の補強。使えなくても記事は書けるので、止めずに先へ進む
        log(f"        メーカー公式サイトの確認をできませんでした: {str(exc)[:200]}")
        return {}
    return validate(text, fetched, products, log)


# --------------------------------------------------------------------------
# 記事への反映
# --------------------------------------------------------------------------

def describe(official: dict, n: int) -> str:
    """商品データに付け足す、公式仕様のブロック。"""
    o = official.get(n)
    if not o:
        return ""
    lines = [f"メーカー公式サイトの仕様（{o['maker']} {o['model']}、出典: {o['source_title']}、"
             f"{o['checked_at']}確認。本文で使うときは「メーカー公式サイトによると」と添える）:"]
    lines += [f"・{s['name']}: {s['value']}" for s in o["specs"]]
    if o.get("note"):
        lines.append(f"・楽天の商品説明との違い: {o['note']}")
    return "\n".join(lines)


def sources_section(official: dict) -> str:
    """記事の末尾に付ける出典の一覧。"""
    if not official:
        return ""
    rows = [f"- 商品{n}（{o['maker']} {o['model']}）：[{o['source_title']}]({o['source_url']})"
            for n, o in sorted(official.items())]
    return ("\n\n## 参考にしたメーカー公式ページ\n\n"
            "仕様の一部は、メーカー公式サイトの製品ページで確認しました"
            f"（{next(iter(official.values()))['checked_at']}時点）。\n\n" + "\n".join(rows) + "\n")
