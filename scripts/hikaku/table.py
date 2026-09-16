"""比較表HTMLの生成。

生成物は2ブロック構成:
  1. 商品カード一覧  … 成約導線。ここが実際に売上を作る部分。
  2. スペック比較表  … 横スクロール可能。項目を並べて比べたい読者向け。

CSS は .hkg- プレフィックスで名前空間を切ってあるので、
WordPress のテーマや自作サイトの既存CSSと衝突しない。
"""

from __future__ import annotations

from html import escape

from .models import Product, spec_columns

# --- 法令・SEO上の必須要素 -------------------------------------------------
# 1. 景品表示法のステマ規制（2023年10月施行）により、広告であることの明示が必要。
# 2. Googleは金銭が絡むリンクに rel="sponsored"（または nofollow）を要求している。
#    これを怠るとサイト全体の評価を落とすリスクがあるため、ここは変更不可にしている。
AD_DISCLOSURE = "本記事にはアフィリエイト広告（PR）が含まれます。"
LINK_REL = "sponsored nofollow noopener"

PROVIDER_LABEL = {"rakuten": "楽天市場", "amazon": "Amazon"}
PROVIDER_CLASS = {"rakuten": "hkg-btn--rakuten", "amazon": "hkg-btn--amazon"}

CSS = """
.hkg-wrap{--hkg-fg:#1a1c1f;--hkg-muted:#5d646d;--hkg-bg:#fff;--hkg-card:#fff;
  --hkg-border:#e2e5e9;--hkg-accent:#c8102e;--hkg-accent-soft:#fdeef0;
  --hkg-thumb-bg:#f6f7f9;
  --hkg-shadow:0 1px 3px rgba(0,0,0,.06),0 6px 20px rgba(0,0,0,.05);
  color:var(--hkg-fg);background:var(--hkg-bg);
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP","Yu Gothic",sans-serif;
  line-height:1.7;margin:2rem 0;-webkit-font-smoothing:antialiased}
@media (prefers-color-scheme:dark){.hkg-wrap:not([data-theme="light"]){
  --hkg-fg:#e8eaed;--hkg-muted:#9aa3ad;--hkg-bg:#16181c;--hkg-card:#1e2126;
  --hkg-border:#2f343b;--hkg-accent:#ff6b81;--hkg-accent-soft:#2a1d21;
  --hkg-thumb-bg:#24282e;
  --hkg-shadow:0 1px 3px rgba(0,0,0,.4),0 6px 20px rgba(0,0,0,.3)}}
.hkg-wrap[data-theme="dark"]{--hkg-fg:#e8eaed;--hkg-muted:#9aa3ad;--hkg-bg:#16181c;
  --hkg-card:#1e2126;--hkg-border:#2f343b;--hkg-accent:#ff6b81;--hkg-accent-soft:#2a1d21;
  --hkg-thumb-bg:#24282e;
  --hkg-shadow:0 1px 3px rgba(0,0,0,.4),0 6px 20px rgba(0,0,0,.3)}
.hkg-wrap *{box-sizing:border-box}
.hkg-title{font-size:1.4rem;font-weight:700;margin:0 0 .25rem;letter-spacing:.01em}
.hkg-disclosure{font-size:.78rem;color:var(--hkg-muted);margin:0 0 1.25rem}
.hkg-cards{display:grid;gap:1rem;margin:0 0 2rem}
.hkg-card{position:relative;display:grid;grid-template-columns:132px 1fr;gap:1rem;
  padding:1rem;background:var(--hkg-card);border:1px solid var(--hkg-border);
  border-radius:14px;box-shadow:var(--hkg-shadow)}
.hkg-card--rec{border-color:var(--hkg-accent);border-width:2px}
.hkg-rank{position:absolute;top:-10px;left:-8px;width:30px;height:30px;display:flex;
  align-items:center;justify-content:center;background:var(--hkg-fg);color:var(--hkg-bg);
  border-radius:50%;font-size:.85rem;font-weight:700}
.hkg-badge{display:inline-block;padding:.15rem .6rem;margin:0 0 .35rem;
  background:var(--hkg-accent-soft);color:var(--hkg-accent);border-radius:999px;
  font-size:.72rem;font-weight:700}
/* align-self:start を付けないと、カードの高さぶんサムネイルが縦に伸びてしまう */
.hkg-thumb{width:132px;height:132px;align-self:start;display:flex;align-items:center;
  justify-content:center;background:var(--hkg-thumb-bg);border-radius:10px;overflow:hidden}
.hkg-thumb img{max-width:100%;max-height:100%;object-fit:contain}
.hkg-thumb--empty{color:var(--hkg-muted);font-size:.72rem}
.hkg-name{font-size:.97rem;font-weight:700;margin:0 0 .4rem;line-height:1.45;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hkg-price{font-size:1.35rem;font-weight:700;color:var(--hkg-accent);margin:0 0 .3rem}
.hkg-price small{font-size:.72rem;font-weight:500;color:var(--hkg-muted);margin-left:.3rem}
.hkg-meta{display:flex;flex-wrap:wrap;gap:.4rem .8rem;font-size:.78rem;
  color:var(--hkg-muted);margin:0 0 .5rem}
.hkg-stars{color:#f5a623;letter-spacing:.05em}
.hkg-specs{display:grid;grid-template-columns:auto 1fr;gap:.15rem .7rem;
  font-size:.8rem;margin:0 0 .6rem}
.hkg-specs dt{color:var(--hkg-muted)}
.hkg-specs dd{margin:0}
.hkg-comment{font-size:.84rem;padding:.6rem .8rem;margin:0 0 .7rem;
  background:var(--hkg-accent-soft);border-radius:8px}
.hkg-btns{display:flex;flex-wrap:wrap;gap:.5rem}
.hkg-btn{display:inline-flex;align-items:center;justify-content:center;flex:1 1 150px;
  padding:.65rem 1rem;border-radius:8px;font-size:.87rem;font-weight:700;
  text-decoration:none;color:#fff;transition:opacity .15s}
.hkg-btn:hover{opacity:.85}
.hkg-btn--rakuten{background:#bf0000}
.hkg-btn--amazon{background:#ff9900;color:#111}
.hkg-tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch;
  border:1px solid var(--hkg-border);border-radius:12px}
.hkg-table{width:100%;border-collapse:collapse;font-size:.83rem;min-width:520px}
.hkg-table th,.hkg-table td{padding:.6rem .8rem;text-align:left;
  border-bottom:1px solid var(--hkg-border);white-space:nowrap}
.hkg-table thead th{background:var(--hkg-accent-soft);font-weight:700;
  position:sticky;top:0}
.hkg-table tbody tr:last-child th,.hkg-table tbody tr:last-child td{border-bottom:0}
.hkg-table th[scope="row"]{color:var(--hkg-muted);font-weight:500;
  background:var(--hkg-card);position:sticky;left:0;z-index:1}
.hkg-scrollhint{font-size:.75rem;color:var(--hkg-muted);margin:.45rem 0 0}
.hkg-updated{font-size:.75rem;color:var(--hkg-muted);margin:1rem 0 0}
@media (max-width:600px){
  .hkg-card{grid-template-columns:1fr;gap:.75rem}
  .hkg-thumb{width:100%;height:170px}
  .hkg-price{font-size:1.2rem}
  .hkg-btn{flex:1 1 100%}
}
"""


def _stars(rating: float) -> str:
    """5点満点の評価を★で表現する。0.5刻みで半分は◐にする。"""
    full = int(rating)
    half = 1 if rating - full >= 0.5 else 0
    return "★" * full + "◐" * half + "☆" * (5 - full - half)


def _escape(value: object) -> str:
    return escape(str(value), quote=True)


def _card(product: Product, rank: int) -> str:
    classes = "hkg-card hkg-card--rec" if product.recommended else "hkg-card"

    if product.image_url:
        thumb = (
            f'<div class="hkg-thumb"><img src="{_escape(product.image_url)}" '
            f'alt="{_escape(product.name)}" loading="lazy" decoding="async"></div>'
        )
    else:
        thumb = '<div class="hkg-thumb hkg-thumb--empty">画像なし</div>'

    badge = ""
    label = product.badge or ("編集部おすすめ" if product.recommended else "")
    if label:
        badge = f'<span class="hkg-badge">{_escape(label)}</span>'

    meta: list[str] = []
    if product.rating is not None:
        review = f"（{product.review_count:,}件）" if product.review_count else ""
        meta.append(
            f'<span><span class="hkg-stars">{_stars(product.rating)}</span> '
            f"{product.rating:.2f}{review}</span>"
        )
    if product.shop:
        meta.append(f"<span>{_escape(product.shop)}</span>")
    if product.free_shipping:
        meta.append("<span>送料無料</span>")

    specs = ""
    if product.specs:
        rows = "".join(
            f"<dt>{_escape(k)}</dt><dd>{_escape(v)}</dd>"
            for k, v in product.specs.items()
        )
        specs = f'<dl class="hkg-specs">{rows}</dl>'

    comment = (
        f'<p class="hkg-comment">{_escape(product.comment)}</p>'
        if product.comment else ""
    )

    store = PROVIDER_LABEL.get(product.provider, "販売ページ")
    btn_class = PROVIDER_CLASS.get(product.provider, "hkg-btn--rakuten")
    button = (
        f'<a class="hkg-btn {btn_class}" href="{_escape(product.url)}" '
        f'target="_blank" rel="{LINK_REL}">{_escape(store)}で価格を見る</a>'
    )

    return f"""    <article class="{classes}">
      <span class="hkg-rank">{rank}</span>
      {thumb}
      <div>
        {badge}
        <h3 class="hkg-name">{_escape(product.name)}</h3>
        <p class="hkg-price">{_escape(product.price_text)}<small>税込・変動あり</small></p>
        <div class="hkg-meta">{"".join(meta)}</div>
        {specs}
        {comment}
        <div class="hkg-btns">{button}</div>
      </div>
    </article>"""


def _spec_table(products: list[Product]) -> str:
    """商品を列、項目を行にした比較表。商品数が増えても横スクロールで対応する。"""
    headers = "".join(
        f'<th scope="col">{_escape(p.name[:22])}{"…" if len(p.name) > 22 else ""}</th>'
        for p in products
    )

    rows: list[str] = []

    rows.append(
        '<tr><th scope="row">価格</th>'
        + "".join(f"<td>{_escape(p.price_text)}</td>" for p in products)
        + "</tr>"
    )

    if any(p.rating is not None for p in products):
        rows.append(
            '<tr><th scope="row">評価</th>'
            + "".join(
                f"<td>{p.rating:.2f}</td>" if p.rating is not None else "<td>—</td>"
                for p in products
            )
            + "</tr>"
        )

    if any(p.review_count for p in products):
        rows.append(
            '<tr><th scope="row">レビュー数</th>'
            + "".join(
                f"<td>{p.review_count:,}件</td>" if p.review_count else "<td>—</td>"
                for p in products
            )
            + "</tr>"
        )

    if any(p.free_shipping is not None for p in products):
        rows.append(
            '<tr><th scope="row">送料</th>'
            + "".join(
                "<td>—</td>" if p.free_shipping is None
                else ("<td>無料</td>" if p.free_shipping else "<td>別途</td>")
                for p in products
            )
            + "</tr>"
        )

    # 手入力した specs を行として追加する
    for column in spec_columns(products):
        rows.append(
            f'<tr><th scope="row">{_escape(column)}</th>'
            + "".join(f"<td>{_escape(p.specs.get(column, '—'))}</td>" for p in products)
            + "</tr>"
        )

    return f"""  <div class="hkg-tablewrap">
    <table class="hkg-table">
      <thead><tr><th scope="col">項目</th>{headers}</tr></thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </div>
  <p class="hkg-scrollhint">※ 表は横にスクロールできます</p>"""


def build_email(products: list[Product], updated_at: str = "") -> str:
    """承認メール用の、インラインCSSだけで組んだ商品一覧。

    メールクライアントは <style> タグを削除するため、サイト用のカードHTMLを
    そのまま送ると崩れて読みにくくなる。承認時に必要なのは「事実の確認」なので、
    価格・評価・スペック・リンクだけを素朴な表で並べる。
    """
    td = "padding:8px 10px;border-bottom:1px solid #e2e5e9;font-size:13px;vertical-align:top;"
    th = td + "color:#57606a;white-space:nowrap;background:#f6f8fa;"

    blocks: list[str] = []
    for i, p in enumerate(products, 1):
        rows = [f'<tr><td style="{th}">価格</td><td style="{td}">{_escape(p.price_text)}</td></tr>']
        if p.rating is not None:
            reviews = f"（{p.review_count:,}件）" if p.review_count else ""
            rows.append(
                f'<tr><td style="{th}">評価</td>'
                f'<td style="{td}">{p.rating:.2f} / 5.00{reviews}</td></tr>'
            )
        if p.shop:
            rows.append(f'<tr><td style="{th}">販売</td><td style="{td}">{_escape(p.shop)}</td></tr>')
        if p.free_shipping is not None:
            rows.append(
                f'<tr><td style="{th}">送料</td>'
                f'<td style="{td}">{"無料" if p.free_shipping else "別途"}</td></tr>'
            )
        for key, value in p.specs.items():
            rows.append(
                f'<tr><td style="{th}">{_escape(key)}</td>'
                f'<td style="{td}">{_escape(value)}</td></tr>'
            )

        badge = ""
        if p.recommended or p.badge:
            badge = (
                f'<span style="display:inline-block;padding:2px 8px;margin-left:6px;'
                f'background:#fdeef0;color:#c8102e;border-radius:10px;font-size:11px;'
                f'font-weight:bold;">{_escape(p.badge or "おすすめ")}</span>'
            )

        blocks.append(f"""
<table cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #e2e5e9;
  border-radius:6px;margin:0 0 14px;border-collapse:separate;">
  <tr><td colspan="2" style="padding:10px;font-size:14px;font-weight:bold;
    border-bottom:1px solid #e2e5e9;">{i}. {_escape(p.name)}{badge}</td></tr>
  {"".join(rows)}
  <tr><td colspan="2" style="padding:10px;font-size:13px;">
    <a href="{_escape(p.url)}" rel="{LINK_REL}">{_escape(PROVIDER_LABEL.get(p.provider, "販売ページ"))}のリンクを確認する</a>
  </td></tr>
</table>""")

    note = (
        f'<p style="font-size:12px;color:#57606a;margin:0 0 20px;">'
        f"価格は{_escape(updated_at)}時点の取得値です。</p>" if updated_at else ""
    )
    return "".join(blocks) + note


def build(
    products: list[Product],
    title: str = "おすすめ商品 比較",
    updated_at: str = "",
    include_style: bool = True,
    include_title: bool = True,
    include_disclosure: bool = True,
) -> str:
    """比較表のHTMLブロックを返す（記事本文にそのまま貼れる断片）。

    記事ページに埋め込む場合、見出しと広告表記はページ側が既に持っていることが多い。
    その場合は include_title / include_disclosure を False にして重複を避ける。
    ただしページ側に広告表記が**ない**ときは必ず True のままにすること
    （景品表示法のステマ規制により表示が必要）。
    """
    if not products:
        raise ValueError("商品が1件もありません")

    style = f"<style>{CSS}</style>\n" if include_style else ""
    heading = f'  <h2 class="hkg-title">{_escape(title)}</h2>\n' if include_title else ""
    disclosure = (
        f'  <p class="hkg-disclosure">{AD_DISCLOSURE}</p>\n' if include_disclosure else ""
    )
    cards = "\n".join(_card(p, i + 1) for i, p in enumerate(products))
    updated = (
        f'  <p class="hkg-updated">価格・在庫は{_escape(updated_at)}時点のものです。'
        "最新情報は各販売ページをご確認ください。</p>"
        if updated_at else ""
    )

    return f"""{style}<div class="hkg-wrap">
{heading}{disclosure}  <div class="hkg-cards">
{cards}
  </div>
{_spec_table(products)}
{updated}
</div>"""


def build_page(products: list[Product], title: str = "おすすめ商品 比較",
               updated_at: str = "") -> str:
    """ブラウザで単体確認するための完全なHTMLページ。"""
    block = build(products, title=title, updated_at=updated_at, include_style=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>{_escape(title)}</title>
<style>
body{{margin:0;padding:1.5rem;background:#fff}}
@media (prefers-color-scheme:dark){{body{{background:#16181c}}}}
.hkg-page{{max-width:820px;margin:0 auto}}
{CSS}
</style>
</head>
<body><div class="hkg-page">
{block}
</div></body>
</html>"""
