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

from . import common, pick_page, products_view
from .hikaku import widget
from .hikaku.table import CSS as TABLE_CSS

SITE_CSS = """
/* 色と文字の決まりごと。色は「意味」にだけ使う：
   brand … サイトの印・順位・結論（読者を案内する色）
   cta   … 購入ボタンだけ（押してほしい場所を1つの色に絞る）
   ダークモードには切り替えない。商品写真は白地で撮られていることが多く、
   黒背景だと写真の白い縁が浮いて見づらいため。 */
:root{--ink:#1f2328;--muted:#5c6370;--bg:#fff;--surface:#f6f6f3;--border:#e4e4df;
  --brand:#0f5e5b;--brand-soft:#eaf4f3;--cta:#e8590c;--cta-shade:#b84308;--star:#f08c00;
  --head-font:"Zen Kaku Gothic New","Hiragino Sans","Noto Sans JP",sans-serif;
  color-scheme:light}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-size:16.5px;line-height:1.9;
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Hiragino Kaku Gothic ProN",
  "Noto Sans JP","Yu Gothic",Meiryo,sans-serif;-webkit-font-smoothing:antialiased;
  line-break:strict;overflow-wrap:anywhere}
a{color:var(--brand)}
img{max-width:100%;height:auto}
.container{max-width:760px;margin:0 auto;padding:0 20px}
.container--wide{max-width:1040px}

/* ヘッダー */
header.site{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.94);
  backdrop-filter:saturate(1.4) blur(8px);border-bottom:1px solid var(--border)}
header.site .container{display:flex;align-items:center;gap:20px;min-height:60px;max-width:1040px}
header.site a.brand{display:flex;align-items:center;gap:10px;font-family:var(--head-font);
  font-weight:700;font-size:1.15rem;color:var(--ink);text-decoration:none;letter-spacing:.04em;flex:none}
header.site a.brand::before{content:"";width:22px;height:22px;border-radius:6px;background:var(--brand);
  box-shadow:inset 0 0 0 5px var(--brand),inset 0 0 0 7px #fff}
header.site nav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;margin-left:auto}
header.site nav::-webkit-scrollbar{display:none}
header.site nav a{flex:none;font-size:.86rem;padding:.4rem .7rem;border-radius:8px;color:var(--muted);
  text-decoration:none;font-weight:700}
header.site nav a:hover{background:var(--surface);color:var(--ink)}

/* 記事 */
.post{padding:32px 0 0}
.post-head{margin:0 0 28px}
.chip{display:inline-block;padding:.18rem .7rem;border-radius:999px;background:var(--brand-soft);
  color:var(--brand);font-size:.78rem;font-weight:700;text-decoration:none;margin:0 0 .8rem}
h1{font-family:var(--head-font);font-size:1.9rem;line-height:1.45;margin:0 0 .8rem;
  letter-spacing:.02em;font-feature-settings:"palt"}
h2{font-family:var(--head-font);font-size:1.38rem;line-height:1.5;margin:3.2rem 0 1rem;
  padding:.1rem 0 .1rem .8rem;border-left:5px solid var(--brand);letter-spacing:.02em;
  font-feature-settings:"palt"}
h2 a{color:var(--ink);text-decoration:none}
h3{font-size:1.08rem;line-height:1.55;margin:2rem 0 .6rem}
p{margin:0 0 1.15rem}
strong{background:linear-gradient(transparent 62%,#ffe8a3 62%);font-weight:700}
.meta{font-size:.82rem;color:var(--muted);margin:0}
.notice{margin:14px 0 0;padding:.6rem .9rem;border-radius:10px;background:var(--surface);
  font-size:.78rem;color:var(--muted);line-height:1.7}
.post-body ul,.post-body ol{padding-left:1.4em;margin:0 0 1.2rem}
.post-body li{margin:.3rem 0}
blockquote{margin:1.2rem 0 1.6rem;padding:.9rem 1.1rem;border-left:4px solid var(--brand);
  border-radius:0 12px 12px 0;background:var(--brand-soft)}
blockquote p:last-child{margin:0}
blockquote strong{background:none;color:var(--brand)}
.post-body table:not(.hkg-stats-table){border-collapse:collapse;width:100%;font-size:.9rem;margin:0 0 1.4rem}
.post-body table:not(.hkg-stats-table) th,.post-body table:not(.hkg-stats-table) td{
  border:1px solid var(--border);padding:.55rem .7rem;text-align:left}
.post-body table:not(.hkg-stats-table) th{background:var(--surface)}

/* 一覧 */
.hero{padding:40px 0 8px}
.hero h1{font-size:1.7rem;margin:0 0 .4rem}
.lead{font-size:.95rem;color:var(--muted);margin:0 0 8px}
.section-title{font-family:var(--head-font);font-size:1.2rem;margin:2.4rem 0 1rem;
  display:flex;align-items:baseline;justify-content:space-between;gap:1rem;border:0;padding:0}
.section-title a{font-size:.82rem;font-family:inherit;font-weight:700;color:var(--brand)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:18px;
  list-style:none;margin:0;padding:0}
.card a{display:flex;flex-direction:column;height:100%;border:1px solid var(--border);border-radius:14px;
  overflow:hidden;text-decoration:none;color:var(--ink);background:#fff;
  transition:border-color .2s,transform .2s}
.card a:hover{border-color:var(--brand);transform:translateY(-2px)}
/* 画像の有無で高さがずれないよう、枠の比率を固定して中に収める */
.card-img{position:relative;height:0;padding-bottom:75%;background:#fff;border-bottom:1px solid var(--border)}
.card-img img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:12px}
.card-img--none span{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.card-img--none{background:var(--surface);color:var(--brand);font-family:var(--head-font);
  font-weight:700;font-size:1.05rem;letter-spacing:.06em}
.card-body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
.card-title{font-weight:700;font-size:.95rem;line-height:1.55}
.card-meta{font-size:.74rem;color:var(--muted);margin-top:auto}

footer.site{margin-top:80px;border-top:1px solid var(--border);padding:28px 0 56px;
  font-size:.8rem;color:var(--muted);background:var(--surface)}
footer.site .container{max-width:1040px}
footer.site a{color:var(--muted)}
footer.site p{margin:0 0 .4rem}
@media (max-width:640px){
  body{font-size:16px;line-height:1.85}
  h1{font-size:1.5rem}h2{font-size:1.22rem;margin-top:2.6rem}
  header.site .container{gap:12px}
  .cards{grid-template-columns:1fr 1fr;gap:12px}
  .card-body{padding:10px}
  .card-title{font-size:.86rem}
}
"""


def categories(config: dict) -> list[dict]:
    """config.json に定義されたカテゴリ一覧。未定義なら空。"""
    return config.get("categories", [])


def category_name(config: dict, slug: str) -> str:
    for cat in categories(config):
        if cat.get("slug") == slug:
            return cat.get("name", slug)
    return slug or "その他"


def head(title: str, description: str, config: dict, canonical: str = "",
         image: str = "", noindex: bool = False) -> str:
    base = config.get("base_url", "").rstrip("/")
    prefix = escape(config.get("path_prefix", "/"))
    canonical_url = base + canonical if base and canonical else ""
    canonical_tag = f'<link rel="canonical" href="{escape(canonical_url)}">' if canonical_url else ""
    # SNSで共有されたときの表示。画像があると一覧の中で目に留まりやすい
    og = [f'<meta property="og:title" content="{escape(title)}">',
          f'<meta property="og:description" content="{escape(description)}">',
          f'<meta property="og:site_name" content="{escape(config.get("site_title", ""))}">',
          '<meta property="og:type" content="article">']
    if canonical_url:
        og.append(f'<meta property="og:url" content="{escape(canonical_url)}">')
    if image:
        og += [f'<meta property="og:image" content="{escape(image)}">',
               '<meta name="twitter:card" content="summary_large_image">']
    robots = '<meta name="robots" content="noindex,nofollow">' if noindex else ""
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
{robots}
{chr(10).join(og)}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@700&display=swap">
<link rel="stylesheet" href="{prefix}style.css">
<script src="{prefix}rakuten-table.js" defer></script>
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
  <p>当サイトはアフィリエイトプログラムに参加しており、記事には広告（PR）が含まれます。
     商品の価格・在庫は、リンク先の販売ページで最新の情報をご確認ください。</p>
  <p>&copy; {common.now_jst().year} {escape(config.get('site_title', ''))}
     ・<a href="{prefix}about/">運営者情報・免責事項</a></p>
</div></footer>
</body></html>"""


def render_post(draft: common.Draft, config: dict) -> str:
    body_html = md.markdown(draft.body, extensions=["extra", "sane_lists", "toc"])
    if draft.products:
        # 商品紹介形式。差し込み記号を結論ボックス・比較表・商品カードに置き換える
        body_html = products_view.fill(body_html, draft.products)
    else:
        # 旧形式（選び方ガイド）。楽天の検索結果を読者のブラウザで並べる
        body_html = body_html.replace("<!--TABLE-->", draft.table_html or "")
    body_html = body_html.replace("<!--STATS-->", draft.stats_html or "")

    # 未記入欄が残ったまま公開された場合、読者に見せないよう除去する
    for name in ("実体験", "注意点", "結論"):
        body_html = body_html.replace("{{" + name + "}}", "")

    prefix = config.get("path_prefix", "/")
    published = draft.published_at or draft.created_at
    dates = f"公開日 {escape(published)}"
    if draft.updated_at and draft.updated_at != published:
        dates += f"　更新日 {escape(draft.updated_at)}"

    chip = ""
    if draft.category:
        chip = (f'<a class="chip" href="{escape(prefix)}category/{escape(draft.category)}/">'
                f"{escape(category_name(config, draft.category))}</a>")
    image = products_view.top_image(draft.products, draft.body) if draft.products else ""

    return f"""{head(draft.title, draft.description, config, f"{prefix}{draft.slug}/", image=image)}
<article class="post">
  <div class="post-head">
    {chip}
    <h1>{escape(draft.title)}</h1>
    <p class="meta">{dates}</p>
    <p class="notice">本記事にはアフィリエイト広告（PR）が含まれます。商品の情報は、
       楽天市場の商品情報（価格・評価・商品説明）にもとづいています。
       編集部は紹介する商品を実際には使用していません。</p>
  </div>
  <div class="post-body">
  {body_html}
  </div>
</article>
{foot(config)}"""


def post_list(posts: list[common.Draft], config: dict, show_category: bool = True) -> str:
    """記事をカードで並べる。商品紹介形式の記事は1位の商品画像を見出し画像にする。"""
    if not posts:
        return "<p>まだ記事がありません。</p>"
    prefix = escape(config.get("path_prefix", "/"))
    items = []
    for p in posts:
        img = products_view.top_image(p.products, p.body) if p.products else ""
        if img:
            figure = (f'<div class="card-img"><img src="{escape(img, quote=True)}" alt="" '
                      f'loading="lazy" decoding="async" width="300" height="225"></div>')
        else:
            figure = (f'<div class="card-img card-img--none">'
                      f'<span>{escape(category_name(config, p.category))}</span></div>')
        label = escape(category_name(config, p.category)) if show_category and p.category else ""
        date = escape(p.updated_at or p.published_at or p.created_at)
        items.append(
            f'  <li class="card"><a href="{prefix}{escape(p.slug)}/">{figure}'
            f'<div class="card-body"><span class="card-title">{escape(p.title)}</span>'
            f'<span class="card-meta">{label}{"　" if label else ""}{date}</span></div></a></li>'
        )
    return '<ul class="cards">\n' + "\n".join(items) + "\n</ul>"


def render_index(posts: list[common.Draft], config: dict) -> str:
    prefix = escape(config.get("path_prefix", "/"))
    # 新しい記事（作り直しを含む）を先頭に
    ordered = sorted(posts, key=lambda p: p.updated_at or p.published_at or p.created_at,
                     reverse=True)
    blocks = [f'<h2 class="section-title">新着</h2>\n{post_list(ordered[:8], config)}']

    # カテゴリごとに最新数件。雑記型サイトでは、何を扱うサイトなのかを一目で示すことが重要
    for cat in categories(config):
        in_cat = [p for p in ordered if p.category == cat["slug"]]
        if not in_cat:
            continue
        more = (f'<a href="{prefix}category/{escape(cat["slug"])}/">すべて見る（{len(in_cat)}件）</a>'
                if len(in_cat) > 4 else "")
        blocks.append(
            f'<h2 class="section-title"><span>{escape(cat["name"])}</span>{more}</h2>\n'
            f'{post_list(in_cat[:4], config, show_category=False)}')

    return f"""{head(config.get('site_title', 'ブログ'), config.get('site_description', ''), config, config.get('path_prefix', '/'))}
</div><div class="container container--wide">
<section class="hero">
  <h1>{escape(config.get('site_title', 'ブログ'))}</h1>
  <p class="lead">{escape(config.get('site_description', ''))}</p>
</section>
{chr(10).join(blocks)}
</div><div class="container">
{foot(config)}"""


def render_category(cat: dict, posts: list[common.Draft], config: dict) -> str:
    prefix = config.get("path_prefix", "/")
    description = cat.get("description", "") or f"{cat['name']}に関する記事の一覧です。"
    return f"""{head(f"{cat['name']}の記事一覧", description, config, f"{prefix}category/{cat['slug']}/")}
</div><div class="container container--wide">
<section class="hero">
  <h1>{escape(cat['name'])}</h1>
  <p class="lead">{escape(description)}</p>
</section>
{post_list(posts, config, show_category=False)}
</div><div class="container">
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

  <h2>記事の作り方について</h2>
  <p>当サイトの記事は、楽天市場で公開されている商品情報（価格・評価の平均点と件数・商品説明）を
     もとに、AIを使って作成し、運営者が紹介する商品を選んでいます。
     編集部は紹介する商品を実際には使用しておらず、使用感や購入者の感想を書くことはしていません。
     商品の仕様は販売ページの記載に基づいています。</p>

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
        def side(suffix: str) -> str:
            f = common.POSTS / f"{path.stem}{suffix}"
            return f.read_text(encoding="utf-8") if f.exists() else ""
        try:
            posts.append(common.Draft.from_text(
                path.read_text(encoding="utf-8"),
                side(".table.html"), side(".email.html"), side(".stats.html"),
                side(".products.json")))
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

    (common.SITE / "style.css").write_text(
        SITE_CSS + "\n" + TABLE_CSS + "\n" + widget.EXTRA_CSS + "\n" + products_view.CSS,
        encoding="utf-8")

    # 比較表ウィジェット。楽天の公開キーを埋め込んだJSを書き出す。
    # このキーはブラウザに露出する前提のもので、楽天側のドメイン制限が防御になる。
    rakuten = config.get("rakuten_client", {})
    (common.SITE / "rakuten-table.js").write_text(
        widget.build_js(
            application_id=rakuten.get("application_id", ""),
            access_key=rakuten.get("access_key", ""),
            affiliate_id=rakuten.get("affiliate_id", ""),
        ),
        encoding="utf-8",
    )
    if not rakuten.get("access_key"):
        print("  [注意] config.json の rakuten_client が未設定です。"
              "比較表は検索リンクのみの表示になります。")
    (common.SITE / "index.html").write_text(render_index(posts, config), encoding="utf-8")

    # 商品を選ぶページ。運営者だけが使う画面なので検索には出さない（noindex・robots で除外）
    pick_dir = common.SITE / "pick"
    pick_dir.mkdir()
    (pick_dir / "index.html").write_text(pick_page.render(config), encoding="utf-8")

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
            f"User-agent: *\nAllow: /\nDisallow: /pick/\n\nSitemap: {base}/sitemap.xml\n",
            encoding="utf-8")

    # static/ の中身はそのままサイトへコピーする。
    # 生成対象ではないファイル（検証用HTML、favicon、ads.txt など）を置く場所。
    static_dir = common.ROOT / "static"
    copied = 0
    if static_dir.is_dir():
        for source in static_dir.rglob("*"):
            if source.is_file():
                target = common.SITE / source.relative_to(static_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied += 1

    # GitHub Pages が _ で始まるパスをJekyll扱いしないようにする
    (common.SITE / ".nojekyll").write_text("", encoding="utf-8")

    print(f"サイトを生成しました: {len(posts)}記事 / "
          f"{built_categories}カテゴリ / static {copied}件 "
          f"→ {common.SITE.relative_to(common.ROOT)}/")

    uncategorized = [p for p in posts if not p.category]
    if uncategorized and categories(config):
        print(f"  [注意] カテゴリ未設定の記事が{len(uncategorized)}件あります。"
              "keywords.json の category を設定してください。")


if __name__ == "__main__":
    main()
