"""静的サイトの生成。

content/posts/*.md を読んで site/ 以下にHTMLを書き出す。
GitHub Pages が site/ を配信する想定。

生成されるもの:
  site/index.html          記事一覧
  site/<slug>/index.html   記事ページ
  site/about/index.html    運営者情報・免責事項（アフィリエイト運営では実質必須）
  site/style.css
  site/sitemap.xml
  site/robots.txt
"""

from __future__ import annotations

import shutil
from html import escape
from pathlib import Path

import markdown as md

from . import common
from .hikaku.table import CSS as TABLE_CSS

SITE_CSS = """
:root{--fg:#1a1c1f;--muted:#5d646d;--bg:#fff;--border:#e2e5e9;--link:#0b62d0;--soft:#f6f7f9}
@media (prefers-color-scheme:dark){
  :root{--fg:#e8eaed;--muted:#9aa3ad;--bg:#16181c;--border:#2f343b;--link:#6ea8fe;--soft:#1e2126}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.85;
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",sans-serif;
  -webkit-font-smoothing:antialiased}
a{color:var(--link)}
.container{max-width:760px;margin:0 auto;padding:0 20px}
header.site{border-bottom:1px solid var(--border);padding:18px 0;margin-bottom:40px}
header.site .container{display:flex;align-items:center;justify-content:space-between;gap:16px}
header.site a.brand{font-weight:700;font-size:17px;color:var(--fg);text-decoration:none}
header.site nav a{font-size:14px;margin-left:16px}
h1{font-size:1.85rem;line-height:1.45;margin:0 0 12px;letter-spacing:.01em}
h2{font-size:1.35rem;margin:2.4rem 0 .9rem;padding-bottom:.4rem;border-bottom:2px solid var(--border)}
h2 a{color:var(--fg);text-decoration:none}
h2 a:hover{color:var(--link)}
h3{font-size:1.1rem;margin:1.8rem 0 .6rem}
p{margin:0 0 1.2rem}
.meta{font-size:.82rem;color:var(--muted);margin:0 0 28px}
article img{max-width:100%;height:auto}
article ul,article ol{padding-left:1.4em}
article li{margin:.3rem 0}
.postlist{list-style:none;padding:0;margin:0}
.postlist li{border-bottom:1px solid var(--border);padding:18px 0}
.postlist a{font-size:1.05rem;font-weight:700;text-decoration:none;color:var(--fg)}
.postlist a:hover{color:var(--link)}
.postlist a:hover{text-decoration:underline}
.postlist .meta{margin:4px 0 0;font-size:.78rem}
.lead{font-size:.95rem;color:var(--muted);margin:0 0 32px}
footer.site{margin-top:64px;border-top:1px solid var(--border);padding:24px 0 48px;
  font-size:.8rem;color:var(--muted)}
footer.site a{color:var(--muted)}
.notice{background:var(--soft);border-radius:8px;padding:12px 16px;font-size:.82rem;
  color:var(--muted);margin:0 0 28px}
@media (max-width:600px){h1{font-size:1.5rem}h2{font-size:1.2rem}body{line-height:1.8}}
"""


def categories(config: dict) -> list[dict]:
    """config.json に定義されたカテゴリ一覧。未定義なら空。"""
    return config.get("categories", [])


def category_name(config: dict, slug: str) -> str:
    for cat in categories(config):
        if cat.get("slug") == slug:
            return cat.get("name", slug)
    return slug or "その他"


def head(title: str, description: str, config: dict, canonical: str = "") -> str:
    base = config.get("base_url", "").rstrip("/")
    prefix = escape(config.get("path_prefix", "/"))
    canonical_tag = (
        f'<link rel="canonical" href="{escape(base + canonical)}">' if base and canonical else ""
    )
    # 記事が1本もないカテゴリはページを生成しないので、ナビにも出さない。
    # 出してしまうとリンク先が404になる。
    active = config.get("_active_categories")
    nav_links = "".join(
        f'<a href="{prefix}category/{escape(c["slug"])}/">{escape(c["name"])}</a>'
        for c in categories(config)
        if active is None or c.get("slug") in active
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description)}">
{canonical_tag}
<link rel="stylesheet" href="{prefix}style.css">
</head>
<body>
<header class="site"><div class="container">
  <a class="brand" href="{prefix}">{escape(config.get('site_title', 'ブログ'))}</a>
  <nav>{nav_links}<a href="{prefix}about/">運営者情報</a></nav>
</div></header>
<div class="container">"""


def foot(config: dict) -> str:
    prefix = escape(config.get("path_prefix", "/"))
    return f"""</div>
<footer class="site"><div class="container">
  <p>当サイトはアフィリエイトプログラムに参加しており、記事には広告（PR）が含まれます。</p>
  <p>&copy; {common.now_jst().year} {escape(config.get('site_title', ''))}
     <a href="{prefix}about/">運営者情報・免責事項</a></p>
</div></footer>
</body></html>"""


def render_post(draft: common.Draft, config: dict) -> str:
    body_html = md.markdown(draft.body, extensions=["extra", "sane_lists", "toc"])
    body_html = body_html.replace("<!--TABLE-->", draft.table_html or "")

    # 未記入欄が残ったまま公開された場合、読者に見せないよう除去する
    for name in ("実体験", "注意点", "結論"):
        body_html = body_html.replace("{{" + name + "}}", "")

    prefix = config.get("path_prefix", "/")
    published = draft.published_at or draft.created_at

    breadcrumb = ""
    if draft.category:
        breadcrumb = (
            f' / <a href="{escape(prefix)}category/{escape(draft.category)}/">'
            f"{escape(category_name(config, draft.category))}</a>"
        )

    return f"""{head(draft.title, draft.description, config, f"{prefix}{draft.slug}/")}
<article>
  <h1>{escape(draft.title)}</h1>
  <p class="meta">公開日：{escape(published)}{breadcrumb}</p>
  <p class="notice">本記事にはアフィリエイト広告（PR）が含まれます。
     価格・在庫は掲載時点のものです。</p>
  {body_html}
</article>
{foot(config)}"""


def post_list(posts: list[common.Draft], config: dict, show_category: bool = False) -> str:
    if not posts:
        return "<p>まだ記事がありません。</p>"
    prefix = escape(config.get("path_prefix", "/"))
    items = []
    for p in posts:
        label = ""
        if show_category and p.category:
            label = f"　{escape(category_name(config, p.category))}"
        items.append(
            f'  <li><a href="{prefix}{escape(p.slug)}/">{escape(p.title)}</a>'
            f'<p class="meta">{escape(p.published_at or p.created_at)}{label}</p></li>'
        )
    return '<ul class="postlist">\n' + "\n".join(items) + "\n</ul>"


def render_index(posts: list[common.Draft], config: dict) -> str:
    prefix = escape(config.get("path_prefix", "/"))
    body = ""

    # カテゴリが定義されていればカテゴリごとに最新数件を並べる。
    # 雑記型サイトでは、何を扱っているサイトなのかを一目で示すことが重要。
    cats = categories(config)
    if cats and posts:
        blocks = []
        for cat in cats:
            in_cat = [p for p in posts if p.category == cat["slug"]]
            if not in_cat:
                continue
            more = ""
            if len(in_cat) > 5:
                more = (f'<p class="meta"><a href="{prefix}category/{escape(cat["slug"])}/">'
                        f'{escape(cat["name"])}の記事をすべて見る（{len(in_cat)}件）</a></p>')
            blocks.append(
                f'<h2><a href="{prefix}category/{escape(cat["slug"])}/">'
                f'{escape(cat["name"])}</a></h2>\n'
                f'{post_list(in_cat[:5], config)}\n{more}'
            )
        uncategorized = [p for p in posts if not p.category
                         or p.category not in {c["slug"] for c in cats}]
        if uncategorized:
            blocks.append("<h2>その他</h2>\n" + post_list(uncategorized[:5], config))
        body = "\n".join(blocks)
    else:
        body = post_list(posts, config)

    return f"""{head(config.get('site_title', 'ブログ'), config.get('site_description', ''), config, config.get('path_prefix', '/'))}
<h1>{escape(config.get('site_title', 'ブログ'))}</h1>
<p class="lead">{escape(config.get('site_description', ''))}</p>
{body}
{foot(config)}"""


def render_category(cat: dict, posts: list[common.Draft], config: dict) -> str:
    prefix = config.get("path_prefix", "/")
    description = cat.get("description", "") or f"{cat['name']}に関する記事の一覧です。"
    return f"""{head(f"{cat['name']}の記事一覧", description, config, f"{prefix}category/{cat['slug']}/")}
<h1>{escape(cat['name'])}</h1>
<p class="lead">{escape(description)}</p>
{post_list(posts, config)}
{foot(config)}"""


def render_about(config: dict) -> str:
    """運営者情報・免責事項。

    アフィリエイトサイトでは、運営者情報とプライバシーポリシーの掲載が
    各ASPの規約やGoogleアドセンスの審査で求められる。空のまま公開しないこと。
    """
    prefix = config.get("path_prefix", "/")
    return f"""{head("運営者情報・免責事項", "当サイトの運営者情報と免責事項です。", config, f"{prefix}about/")}
<article>
  <h1>運営者情報・免責事項</h1>

  <h2>運営者</h2>
  <p>{escape(config.get('author', '（運営者名を config.json の author に設定してください）'))}</p>
  <p>お問い合わせ：{escape(config.get('contact_email', '（連絡先を config.json の contact_email に設定してください）'))}</p>

  <h2>広告について</h2>
  <p>当サイトは、楽天アフィリエイトをはじめとするアフィリエイトプログラムに参加しています。
     記事内のリンクを経由して商品が購入された場合、当サイトに紹介料が発生することがあります。
     広告を含む記事には、その旨を記事冒頭に明示しています。</p>

  <h2>掲載情報について</h2>
  <p>価格・在庫・仕様は記事の掲載時点の情報です。最新の情報は各販売ページでご確認ください。
     当サイトは掲載情報の正確性に努めていますが、その完全性を保証するものではありません。
     商品の購入は読者ご自身の判断と責任で行ってください。</p>

  <h2>アクセス解析について</h2>
  <p>当サイトでは、サイトの改善のためアクセス解析ツールを使用する場合があります。
     収集されるデータは匿名であり、個人を特定するものではありません。</p>

  <h2>著作権について</h2>
  <p>当サイトに掲載されている文章・画像の無断転載を禁じます。</p>
</article>
{foot(config)}"""


def render_sitemap(posts: list[common.Draft], config: dict) -> str:
    base = config.get("base_url", "").rstrip("/")
    prefix = config.get("path_prefix", "/")
    urls = [f"  <url><loc>{escape(base + prefix)}</loc></url>",
            f"  <url><loc>{escape(base + prefix)}about/</loc></url>"]
    used = {p.category for p in posts if p.category}
    for cat in categories(config):
        if cat.get("slug") in used:
            urls.append(f"  <url><loc>{escape(base + prefix)}category/{escape(cat['slug'])}/</loc></url>")
    for p in posts:
        lastmod = p.published_at or p.created_at
        urls.append(
            f"  <url><loc>{escape(base + prefix + p.slug)}/</loc>"
            f"<lastmod>{escape(lastmod)}</lastmod></url>"
        )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) + "\n</urlset>\n")


def load_posts() -> list[common.Draft]:
    posts: list[common.Draft] = []
    for path in sorted(common.POSTS.glob("*.md"), reverse=True):
        table_path = common.POSTS / f"{path.stem}.table.html"
        table_html = table_path.read_text(encoding="utf-8") if table_path.exists() else ""
        try:
            posts.append(common.Draft.from_text(path.read_text(encoding="utf-8"), table_html))
        except (ValueError, KeyError) as exc:
            print(f"  [警告] {path.name} を読み飛ばしました: {exc}")
    return posts


def main() -> None:
    config = common.load_config()
    posts = load_posts()

    # ナビゲーションに出してよいカテゴリ（記事が1本以上あるもの）を先に確定させる
    config["_active_categories"] = {p.category for p in posts if p.category}

    if common.SITE.exists():
        shutil.rmtree(common.SITE)
    common.SITE.mkdir(parents=True)

    (common.SITE / "style.css").write_text(SITE_CSS + "\n" + TABLE_CSS, encoding="utf-8")
    (common.SITE / "index.html").write_text(render_index(posts, config), encoding="utf-8")

    about_dir = common.SITE / "about"
    about_dir.mkdir()
    (about_dir / "index.html").write_text(render_about(config), encoding="utf-8")

    for post in posts:
        post_dir = common.SITE / post.slug
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "index.html").write_text(render_post(post, config), encoding="utf-8")

    # カテゴリ別ページ。記事が1本もないカテゴリは作らない
    # （中身のない一覧ページを量産すると低品質ページとみなされるため）
    built_categories = 0
    for cat in categories(config):
        in_cat = [p for p in posts if p.category == cat["slug"]]
        if not in_cat:
            continue
        cat_dir = common.SITE / "category" / cat["slug"]
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / "index.html").write_text(
            render_category(cat, in_cat, config), encoding="utf-8")
        built_categories += 1

    base = config.get("base_url", "").rstrip("/")
    if base:
        (common.SITE / "sitemap.xml").write_text(render_sitemap(posts, config), encoding="utf-8")
        (common.SITE / "robots.txt").write_text(
            f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")

    # GitHub Pages が _ で始まるパスをJekyll扱いしないようにする
    (common.SITE / ".nojekyll").write_text("", encoding="utf-8")

    print(f"サイトを生成しました: {len(posts)}記事 / "
          f"{built_categories}カテゴリ → {common.SITE.relative_to(common.ROOT)}/")

    uncategorized = [p for p in posts if not p.category]
    if uncategorized and categories(config):
        print(f"  [注意] カテゴリ未設定の記事が{len(uncategorized)}件あります。"
              "keywords.json の category を設定してください。")


if __name__ == "__main__":
    main()
