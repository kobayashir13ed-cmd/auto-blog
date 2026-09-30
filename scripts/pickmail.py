"""朝のメール：今日の記事で紹介する商品を選んでもらう。

キーワードの在庫から次の1件を選び、商品選択ページへのリンクを送る。
リンクには署名付きのトークンを付けるので、メールを受け取った本人しか依頼を出せない。

    python -m scripts.pickmail                 # 次のキーワードでメールを送る
    python -m scripts.pickmail --slug xxx      # キーワードを指定して送る
    python -m scripts.pickmail --rewrite-all   # 公開済み記事の作り直し用リンクをまとめて送る
    python -m scripts.pickmail --dry-run       # 送らずにリンクだけ表示する
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlencode

from . import build_site, common, notify, tokens


def pick_url(config: dict, secret: str, entry: dict) -> str:
    base = config.get("base_url", "").rstrip("/")
    prefix = config.get("path_prefix", "/")
    query = {
        "k": entry["slug"],
        "t": tokens.make_token(secret, entry["slug"], "pick"),
        "q": entry.get("search_keyword") or entry["keyword"],
        "kw": entry["keyword"],
    }
    if entry.get("min_price"):
        query["min"] = entry["min_price"]
    if entry.get("max_price"):
        query["max"] = entry["max_price"]
    return f"{base}{prefix}pick/?{urlencode(query)}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="商品選択のメールを送ります")
    parser.add_argument("--slug", default="", help="キーワードを slug で指定する")
    parser.add_argument("--rewrite-all", action="store_true",
                        help="公開済み記事を作り直すためのリンクをまとめて送る")
    parser.add_argument("--dry-run", action="store_true", help="送らずに表示だけする")
    args = parser.parse_args(argv)

    config = common.load_config()
    secret = common.env("APPROVAL_SECRET", required=not args.dry_run, default="dry-run")

    if args.rewrite_all:
        links = []
        for post in build_site.load_posts():
            if post.products:
                continue                      # すでに商品紹介形式のものは除く
            entry, _ = common.find_keyword(post.slug)
            entry = entry or {"keyword": post.keyword, "slug": post.slug,
                              "search_keyword": post.keyword}
            links.append((post.title, pick_url(config, secret, entry)))
        if not links:
            print("作り直しが必要な記事はありません。")
            return
        for title, url in links:
            print(f"- {title}\n  {url}")
        if not args.dry_run:
            notify.send_rewrite_links(links, config)
        return

    if args.slug:
        entry, _ = common.find_keyword(args.slug)
        if entry is None:
            sys.exit(f"[エラー] slug '{args.slug}' が keywords.json にありません。")
    else:
        entry, _ = common.next_keyword()
        if entry is None:
            print("未着手のキーワードがありません。")
            return

    url = pick_url(config, secret, entry)
    print(f"今日のキーワード: {entry['keyword']}\n  {url}")
    if not args.dry_run:
        notify.send_pick(entry, url, config)


if __name__ == "__main__":
    main()
