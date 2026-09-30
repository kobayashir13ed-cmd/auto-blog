"""選ばれた商品で記事を書き、問題がなければそのまま公開する。

商品選択ページ（mekikilab.com/pick/）でボタンが押されると、Cloudflare Worker が
repository_dispatch で GitHub Actions を起動し、ここが呼ばれる。

  1. 届いた商品データを検査する（楽天以外のURLや、長すぎる文字列を弾く）
  2. 5つの担当（scripts/agents.py）が順に記事を書く
  3. 機械検査と事実確認をすべて通れば、そのまま公開する
     1つでも問題が残れば公開せず、ドラフトとして承認メールを送る

公開済みの記事の slug で呼ばれた場合は、同じURLのまま中身を作り直す（公開日は変えない）。

    python -m scripts.write --payload-file payload.json   # 手元での動作確認
    python -m scripts.write --payload-file payload.json --mock   # APIを使わない
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import unescape
from urllib.parse import urlparse

from . import agents, build_site, claude_api, common
from .hikaku import widget

REPORTS = common.CONTENT / "reports"
RESULT_PATH = common.ROOT / "write-result.json"   # お知らせメールのステップに渡す
MAX_PRODUCTS = 5

# 商品データに入ってよいURLの持ち主。これ以外は選択ページの改ざんとみなして捨てる。
ITEM_HOSTS = ("item.rakuten.co.jp", "hb.afl.rakuten.co.jp")
IMAGE_HOST_SUFFIXES = (".rakuten.co.jp", ".r10s.jp")


# --------------------------------------------------------------------------
# 届いたデータの検査
# --------------------------------------------------------------------------

def _host_ok(url: str, exact: tuple = (), suffixes: tuple = ()) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host in exact or host.endswith(suffixes))


def _text(value, limit: int) -> str:
    """HTMLタグと余分な空白を落とし、長さを切る。商品説明にはHTMLが混ざっている。"""
    text = re.sub(r"<br\s*/?>|</p>|</li>|</tr>", "\n", str(value or ""), flags=re.I)
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit]


def sanitize_products(raw) -> list[dict]:
    """選択ページから届いた商品を検査して、使える形にそろえる。"""
    if not isinstance(raw, list):
        raise ValueError("商品データが配列ではありません")
    products = []
    for item in raw[:MAX_PRODUCTS]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("affiliateUrl") or item.get("itemUrl") or "")
        item_url = str(item.get("itemUrl") or "")
        image = str(item.get("imageUrl") or "")
        if not _host_ok(url, exact=ITEM_HOSTS):
            print(f"  [除外] 楽天以外のURLです: {url[:60]}")
            continue
        try:
            price = int(item.get("itemPrice"))
            rating = float(item.get("reviewAverage") or 0)
            count = int(item.get("reviewCount") or 0)
        except (TypeError, ValueError):
            print("  [除外] 価格や評価が数値ではありません")
            continue
        if price <= 0 or not 0 <= rating <= 5 or count < 0:
            continue
        captured = str(item.get("capturedAt") or "")
        products.append({
            "itemCode": _text(item.get("itemCode"), 100),
            "itemName": _text(item.get("itemName"), 200),
            "itemPrice": price,
            "affiliateUrl": url,
            "itemUrl": item_url if _host_ok(item_url, exact=ITEM_HOSTS) else url,
            "imageUrl": image if _host_ok(image, suffixes=IMAGE_HOST_SUFFIXES) else "",
            "reviewAverage": round(rating, 2),
            "reviewCount": count,
            "postageFlag": 0 if item.get("postageFlag") == 0 else 1,
            "shopName": _text(item.get("shopName"), 60),
            "catchcopy": _text(item.get("catchcopy"), 200),
            "itemCaption": _text(item.get("itemCaption"), 1500),
            "capturedAt": captured if re.fullmatch(r"\d{4}-\d{2}-\d{2}", captured)
                          else common.today_str(),
        })
    if not products:
        raise ValueError("使える商品が1つもありません")
    return products


# --------------------------------------------------------------------------
# 経緯の保存
# --------------------------------------------------------------------------

def save_report(draft_id: str, result: agents.Result, products: list[dict]) -> None:
    """各担当の成果物を残す。どういう判断で書かれた記事かを後から確かめられる。"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    r = result.reports
    parts = [
        f"# {result.title}",
        f"- 判定: {'公開' if result.ok else '要確認'}",
        f"- 1位: 商品{result.top}",
        "- 商品: " + " / ".join(p["itemName"][:30] for p in products),
    ]
    if result.issues:
        parts += ["", "## 残った問題"] + [f"- {i}" for i in result.issues]
    for key, label in (("research", "リサーチ担当"), ("plan", "企画担当"),
                       ("edit", "編集長の講評"), ("edit_2", "編集長の講評（差し戻し後）")):
        if r.get(key):
            parts += ["", f"## {label}", "", str(r[key]).strip()]
    for key in ("check_1", "check_2"):
        if r.get(key):
            parts += ["", f"## 事実確認（{key[-1]}回目）", "", "```json",
                      json.dumps(r[key], ensure_ascii=False, indent=2), "```"]
    (REPORTS / f"{draft_id}.md").write_text("\n".join(parts) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# モック（APIを使わない動作確認）
# --------------------------------------------------------------------------

def mock_complete(products: list[dict]):
    """各担当の役割に応じた、それらしい応答を返す。仕組みの確認だけに使う。"""
    n = len(products)

    def body() -> str:
        sections = ["部屋の広さや置き場所で迷っている人に向けて、候補を比べます。",
                    "## 迷ったらこれ", "<!--TOP:1-->",
                    "商品1は評価の件数が多く、判断材料がそろっています。",
                    "## 比較表", "<!--COMPARE-->"]
        for i, p in enumerate(products, 1):
            sections += [f"## {p['itemName'][:24]}", f"<!--PRODUCT:{i}-->",
                         "### こんな人に向いています", "- 置き場所を取りたくない人",
                         "### 良いところ", "- 商品説明に主な仕様がまとまっている",
                         "### 気をつけたいところ", "- サイズは商品ページで確認が必要",
                         "### 商品説明から分かる主な仕様", "- 商品ページを参照"]
        sections += ["## 選び方のポイント", "> **ポイント**：置き場所の寸法を先に測っておきます。",
                     "## 楽天市場のデータから分かること", "<!--STATS-->",
                     "## よくある質問", "### Q. どれを選べばいいですか？", "迷ったら1位です。",
                     "## まとめ", "置き場所と予算から選びましょう。"]
        filler = "比較の軸をそろえて読むと、自分に合う商品が見えてきます。" * 160
        return "\n\n".join(sections[:3] + [filler] + sections[3:])

    def complete(prompt: str, system: str, max_tokens: int, thinking=None) -> str:
        if "「リサーチ担当」" in prompt:
            return "①【読者の状況】（推測）置き場所に困っている\n②【比較の軸】…"
        if "「企画担当」" in prompt:
            return "TOP: 1\n⑤ タイトル：置き場所に困らない選び方"
        if "「事実確認担当」" in prompt:
            return '{"ok": true, "issues": []}'
        article = f"TITLE: モック記事（商品{n}個）\nDESC: 動作確認用の記事です。\n{body()}"
        if "「編集長」" in prompt:
            return "REPORT:\n- 問題なし\n===ARTICLE===\n" + article
        return article

    return complete


# --------------------------------------------------------------------------
# 本体
# --------------------------------------------------------------------------

def summarize(result: agents.Result, products: list[dict]) -> list[str]:
    """お知らせメールに載せる短い要約。"""
    top = products[result.top - 1]["itemName"][:40] if products else ""
    chars = len(re.sub(r"<!--.*?-->|\s", "", result.body))
    lines = [f"紹介した商品：{len(products)}個（1位：{top}）", f"本文：約{chars:,}字"]
    if result.reports.get("check_2"):
        lines.append("事実確認：1回差し戻して修正しました" if result.ok
                     else "事実確認：差し戻し後も問題が残りました")
    else:
        lines.append("事実確認：問題なし")
    return lines


def save_result(**values) -> None:
    RESULT_PATH.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")


def send_notice(path: str) -> None:
    """記事を書いたあとのお知らせ。公開したら公開通知、保留したら承認メール。"""
    from . import notify
    config = common.load_config()
    data = json.loads(open(path, encoding="utf-8").read())
    if data.get("result") == "published":
        notify.send_published(data["title"], data["url"], config, data.get("summary", []))
    elif data.get("result") == "needs_review":
        notify.send(common.read_draft(data["draft_id"]), config, issues=data.get("issues", []))
    else:
        print("お知らせは不要です。")


def output(**values) -> None:
    """GitHub Actions の後続ステップに結果を渡す。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def load_payload(args: argparse.Namespace) -> dict:
    if args.payload_file:
        return json.loads(open(args.payload_file, encoding="utf-8").read())
    raw = os.environ.get("PAYLOAD", "")
    if not raw:
        sys.exit("[エラー] 商品データ（PAYLOAD）がありません。")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="選ばれた商品で記事を書きます")
    parser.add_argument("--payload-file", default="")
    parser.add_argument("--mock", action="store_true", help="APIを使わずに流れだけ確認する")
    parser.add_argument("--send-notice", default="", metavar="FILE",
                        help="書き終えたあとのお知らせメールだけを送る")
    args = parser.parse_args(argv)
    if args.send_notice:
        send_notice(args.send_notice)
        return

    config = common.load_config()
    payload = load_payload(args)
    slug = str(payload.get("slug") or "")
    if not re.fullmatch(r"[a-z0-9-]{3,80}", slug):
        sys.exit(f"[エラー] slug が不正です: {slug!r}")

    entry, keywords = common.find_keyword(slug)
    existing = common.find_post(slug)
    if entry is None and existing is None:
        sys.exit(f"[エラー] slug '{slug}' のキーワードも記事も見つかりません。")
    if entry is None:
        # キーワード一覧に無い古い記事。記事側の情報で代用する
        entry = {"keyword": existing.keyword, "slug": slug, "category": existing.category,
                 "search_keyword": existing.keyword}

    products = sanitize_products(payload.get("products"))

    # 二度押し対策。同じ内容の依頼が続けて来ても、1回しか書かない
    if existing is None and entry.get("status", "pending") != "pending":
        print(f"この記事はすでに処理済みです（{entry.get('status')}）。何もしません。")
        output(result="skipped")
        return
    if existing and existing.updated_at == common.today_str() and existing.products:
        print("この記事は今日すでに作り直しています。何もしません。")
        output(result="skipped")
        return

    market = agents.market_summary(payload.get("market") or {}) or agents.fallback_market(products)
    mode = "作り直し" if existing else "新規"
    print(f"{mode}: {entry['keyword']}（商品{len(products)}個）")

    if args.mock:
        complete = mock_complete(products)
    else:
        api_key = common.env("ANTHROPIC_API_KEY")
        model = config.get("agent_model") or config.get("model", "claude-sonnet-5")

        def complete(prompt: str, system: str, max_tokens: int, thinking=None) -> str:
            # 長い本文は生成に数分かかるので、待ち時間を長めに取る
            return claude_api.complete(prompt=prompt, api_key=api_key, model=model,
                                       max_tokens=max_tokens, system=system, timeout=600,
                                       thinking=thinking)

    result = agents.write_article(entry, products, market, config, complete)

    today = common.today_str()
    draft_id = existing.id if existing else f"{today}-{slug}"
    search_kw = entry.get("search_keyword") or entry["keyword"]
    draft = common.Draft(
        id=draft_id, title=result.title, keyword=entry["keyword"], slug=slug,
        body=result.body, category=entry.get("category", "") or (existing.category if existing else ""),
        description=result.description,
        created_at=existing.created_at if existing else today,
        stats_html=widget.stats_placeholder(
            keyword=search_kw, min_price=entry.get("min_price"), max_price=entry.get("max_price")),
        products=products,
        updated_at=today if existing else "",
    )
    save_report(draft_id, result, products)

    if not result.ok:
        common.write_draft(draft, common.DRAFTS)
        if existing is None and keywords.get("keywords"):
            common.mark_keyword(keywords, entry["keyword"], "drafted")
        print(f"\n公開を保留しました。問題が{len(result.issues)}件残っています:")
        for issue in result.issues:
            print(f"  - {issue}")
        output(result="needs_review", draft_id=draft_id)
        save_result(result="needs_review", draft_id=draft_id, title=result.title,
                    issues=result.issues, summary=summarize(result, products))
        return

    draft.published_at = existing.published_at if existing else today
    common.write_draft(draft, common.POSTS)
    if existing:
        # 旧形式の比較表は新しい記事では使わない。残すと古い内容が読み込まれる
        for suffix in (".table.html", ".email.html"):
            (common.POSTS / f"{draft_id}{suffix}").unlink(missing_ok=True)
    if keywords.get("keywords") and common.find_keyword(slug)[0]:
        common.mark_keyword(keywords, entry["keyword"], "published")

    print(f"\n{mode}で公開しました: {result.title}")
    build_site.main()
    base = config.get("base_url", "").rstrip("/")
    url = f"{base}{config.get('path_prefix', '/')}{slug}/"
    output(result="published", draft_id=draft_id, url=url)
    save_result(result="published", draft_id=draft_id, title=result.title, url=url,
                summary=[f"{mode}の記事です"] + summarize(result, products))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as exc:
        sys.exit(f"[エラー] {exc}")
