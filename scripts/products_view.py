"""商品紹介記事の部品（結論ボックス・比較表・商品カード）を組み立てる。

記事本文には差し込み記号だけを書かせ、見た目はここで作る。
AIに HTML を書かせると記事ごとに見た目がばらつき、壊れたタグも混ざるため。

  <!--TOP:n-->      結論ボックス（迷ったらこれ）
  <!--COMPARE-->    全商品の比較表
  <!--PRODUCT:n-->  商品カード

価格は記事を書いた日の値を入れておき、読者がページを開いたときに
ブラウザが楽天から最新の値を取り直して書き換える（rakuten-table.js）。
取り直しに失敗しても、日付つきの値が残るので空欄にはならない。
"""

from __future__ import annotations

import re
from html import escape

LINK_REL = "sponsored nofollow noopener"


def image_url(p: dict, size: int = 400) -> str:
    """楽天の画像は ?_ex=幅x高さ で縮小版を返してくれる。原寸は重いので縮める。"""
    url = p.get("imageUrl") or ""
    if not url:
        return ""
    base = url.split("?")[0]
    if "thumbnail.image.rakuten.co.jp" in base:
        return f"{base}?_ex={size}x{size}"
    return base


def price_text(p: dict) -> str:
    try:
        return f"{int(p['itemPrice']):,}円"
    except (KeyError, TypeError, ValueError):
        return "価格は販売ページで確認"


def as_of(p: dict) -> str:
    """「9/30時点」。最新化に成功したら JS がこの表記を消す。"""
    m = re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", p.get("capturedAt", ""))
    return f"{int(m.group(1))}/{int(m.group(2))}時点" if m else "掲載時点"


def stars(rating: float) -> str:
    """★は切り捨てで表示する（4.8を5つ星に見せない）。正確な値は隣に数字で出す。"""
    full = max(0, min(5, int(rating)))
    return "★" * full + "☆" * (5 - full)


def rating_html(p: dict) -> str:
    count = int(p.get("reviewCount") or 0)
    if not count:
        return '<span class="pc-rating pc-rating--none">レビューはまだありません</span>'
    avg = float(p.get("reviewAverage") or 0)
    return (f'<span class="pc-rating"><span class="pc-stars" aria-hidden="true">'
            f'{stars(avg)}</span><strong>{avg:.2f}</strong>'
            f'<span class="pc-count">（{count:,}件）</span></span>')


def short_name(name: str, limit: int = 48) -> str:
    """楽天の商品名は宣伝文句が長く続くので、読みやすい長さで切る。"""
    name = re.sub(r"[【\[［].*?[】\]］]", "", name).strip() or name
    return name if len(name) <= limit else name[:limit - 1] + "…"


def link(p: dict) -> str:
    return escape(p.get("affiliateUrl") or p.get("itemUrl") or "#", quote=True)


def buy_button(p: dict, label: str = "楽天で価格を見る") -> str:
    return (f'<a class="pc-buy" href="{link(p)}" target="_blank" rel="{LINK_REL}">'
            f'{escape(label)}</a>')


def price_block(p: dict) -> str:
    code = escape(p.get("itemCode", ""), quote=True)
    return (f'<p class="pc-price" data-item-code="{code}">'
            f'<span class="pc-price-num">{escape(price_text(p))}</span>'
            f'<span class="pc-price-note">（税込・{escape(as_of(p))}）</span></p>')


def thumb(p: dict, size: int, cls: str) -> str:
    src = image_url(p, size)
    if not src:
        return f'<div class="{cls} {cls}--empty">画像なし</div>'
    return (f'<div class="{cls}"><img src="{escape(src, quote=True)}" alt="" '
            f'width="{size}" height="{size}" loading="lazy" decoding="async"></div>')


# --------------------------------------------------------------------------
# 部品
# --------------------------------------------------------------------------

def top_box(p: dict, n: int) -> str:
    return f"""
<div class="pc-top">
  <p class="pc-top-label">編集部のいちばんのおすすめ</p>
  <div class="pc-top-body">
    {thumb(p, 240, "pc-top-thumb")}
    <div class="pc-top-info">
      <p class="pc-name"><span class="pc-num">{n}</span>{escape(short_name(p.get("itemName", ""), 60))}</p>
      {rating_html(p)}
      {price_block(p)}
      {buy_button(p)}
    </div>
  </div>
</div>"""


def product_card(p: dict, n: int, is_top: bool) -> str:
    chips = []
    if is_top:
        chips.append('<span class="pc-chip pc-chip--top">いちばんのおすすめ</span>')
    if p.get("postageFlag") == 0:
        chips.append('<span class="pc-chip">送料無料</span>')
    count = int(p.get("reviewCount") or 0)
    review_link = ""
    if count:
        review_link = (f'<a class="pc-sub" href="{link(p)}" target="_blank" rel="{LINK_REL}">'
                       f'レビュー{count:,}件を楽天で読む</a>')
    shop = escape(p.get("shopName", ""))
    return f"""
<div class="pc-card{' pc-card--top' if is_top else ''}">
  {thumb(p, 400, "pc-thumb")}
  <div class="pc-info">
    <div class="pc-chips">{''.join(chips)}</div>
    <p class="pc-name"><span class="pc-num">{n}</span>{escape(short_name(p.get("itemName", ""), 80))}</p>
    {rating_html(p)}
    {price_block(p)}
    <p class="pc-shop">{shop}</p>
    <div class="pc-actions">{buy_button(p)}{review_link}</div>
  </div>
</div>"""


def compare_table(products: list[dict], top: int) -> str:
    """全商品を横に並べた比較表。スマホでは横にスクロールする。"""
    cols = range(1, len(products) + 1)

    def cell(i: int, inner: str) -> str:
        cls = ' class="is-top"' if i == top else ""
        return f"<td{cls}>{inner}</td>"

    top_cls = ' class="is-top"'
    top_chip = '<span class="pc-chip pc-chip--top">おすすめ</span>'
    head = "".join(
        f'<th scope="col"{top_cls if i == top else ""}>'
        f'{top_chip if i == top else ""}'
        f'{thumb(p, 200, "pc-cmp-thumb")}'
        f'<span class="pc-cmp-name"><span class="pc-num">{i}</span>'
        f'{escape(short_name(p.get("itemName", ""), 36))}</span></th>'
        for i, p in zip(cols, products)
    )
    rows = [
        ("価格", [f'{price_block(p)}' for p in products]),
        ("評価", [rating_html(p) for p in products]),
        ("送料", ["無料" if p.get("postageFlag") == 0 else "別（商品ページで確認）"
                 for p in products]),
        ("ショップ", [escape(p.get("shopName", "")) for p in products]),
        ("", [buy_button(p, "楽天で見る") for p in products]),
    ]
    body = "".join(
        f'<tr><th scope="row">{escape(label)}</th>'
        + "".join(cell(i, v) for i, v in zip(cols, values)) + "</tr>"
        for label, values in rows
    )
    return f"""
<div class="pc-compare" role="region" aria-label="比較表" tabindex="0">
  <table>
    <thead><tr><th scope="col" class="pc-corner"></th>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</div>
<p class="pc-compare-note">表は横にスクロールできます。価格はページを開いた時点の楽天市場の値です。</p>"""


# --------------------------------------------------------------------------
# 本文への差し込み
# --------------------------------------------------------------------------

def _marker(name: str) -> re.Pattern:
    # Markdown 変換後は <p> に包まれることがあるので、包みごと置き換える
    return re.compile(rf"(?:<p>\s*)?<!--{name}-->(?:\s*</p>)?")


def fill(body_html: str, products: list[dict]) -> str:
    top_match = re.search(r"<!--TOP:(\d+)-->", body_html)
    top = int(top_match.group(1)) if top_match else 1
    if not 1 <= top <= len(products):
        top = 1

    body_html = _marker(r"TOP:\d+").sub(lambda m: top_box(products[top - 1], top), body_html)
    body_html = _marker("COMPARE").sub(lambda m: compare_table(products, top), body_html)

    def card(m: re.Match) -> str:
        n = int(m.group(1))
        if not 1 <= n <= len(products):
            return ""
        return product_card(products[n - 1], n, n == top)

    body_html = re.sub(r"(?:<p>\s*)?<!--PRODUCT:(\d+)-->(?:\s*</p>)?", card, body_html)
    return decorate(body_html)


# 小見出しの名前で、直後の箇条書きに見た目の種類を付ける
LIST_KINDS = {
    "こんな人に向いています": "fit",
    "向いている人": "fit",
    "良いところ": "pros",
    "良い点": "pros",
    "気をつけたいところ": "cons",
    "気をつけたい点": "cons",
    "注意点": "cons",
    "商品説明から分かる主な仕様": "spec",
    "主な仕様": "spec",
}


def decorate(body_html: str) -> str:
    """見出しや箇条書きに種類ごとのクラスを付ける。文章だけの画面にしないため。"""
    def list_kind(m: re.Match) -> str:
        kind = LIST_KINDS.get(re.sub(r"<[^>]+>", "", m.group(2)).strip())
        if not kind:
            return m.group(0)
        return f'{m.group(1)}\n<ul class="pc-list pc-list--{kind}">'

    body_html = re.sub(r"(<h3[^>]*>(.*?)</h3>)\s*<ul>", list_kind, body_html)
    # よくある質問：「Q.」で始まる小見出しを質問の見た目にする
    body_html = re.sub(r"<h3([^>]*)>\s*Q[.．]\s*", r'<h3\1 class="pc-q"><span>Q</span>', body_html)
    return body_html


def top_image(products: list[dict], body: str) -> str:
    """一覧やSNS共有で使う代表画像。1位の商品の画像にする。"""
    m = re.search(r"<!--TOP:(\d+)-->", body)
    n = int(m.group(1)) if m else 1
    if not products:
        return ""
    p = products[n - 1] if 1 <= n <= len(products) else products[0]
    return image_url(p, 600)


CSS = """
/* ---------- 商品の部品 ---------- */
.pc-top strong,.pc-card strong,.pc-compare strong{background:none}
.pc-num{display:inline-flex;align-items:center;justify-content:center;min-width:1.6em;height:1.6em;
  margin-right:.5em;padding:0 .35em;border-radius:6px;background:var(--brand);color:#fff;
  font-size:.78em;font-weight:700;vertical-align:.1em}
.pc-name{font-weight:700;line-height:1.5;margin:0 0 .4rem;font-size:1rem}
.pc-rating{display:flex;flex-wrap:wrap;align-items:baseline;gap:.25rem;font-size:.9rem;margin:0 0 .3rem}
.pc-rating--none{color:var(--muted);font-size:.82rem}
.pc-stars{color:var(--star);letter-spacing:.05em}
.pc-count{color:var(--muted);font-size:.82rem}
.pc-price{margin:0 0 .6rem;line-height:1.3}
.pc-price-num{font-size:1.35rem;font-weight:700;letter-spacing:.01em}
.pc-price-note{font-size:.75rem;color:var(--muted);margin-left:.25rem}
.pc-price.is-gone .pc-price-num{font-size:.95rem;color:var(--muted)}
.pc-shop{font-size:.78rem;color:var(--muted);margin:0 0 .8rem}
.pc-buy{display:inline-flex;align-items:center;justify-content:center;min-height:48px;
  padding:.7rem 1.4rem;border-radius:10px;background:var(--cta);color:#fff;font-weight:700;
  text-decoration:none;font-size:.95rem;box-shadow:0 2px 0 var(--cta-shade)}
.pc-buy:hover{filter:brightness(1.05);color:#fff}
.pc-buy:active{transform:translateY(1px);box-shadow:none}
.pc-sub{display:inline-flex;align-items:center;min-height:44px;font-size:.85rem;font-weight:700;
  color:var(--brand);text-decoration:none}
.pc-sub::after{content:"→";margin-left:.3rem}
.pc-actions{display:flex;flex-wrap:wrap;align-items:center;gap:.4rem 1rem}
.pc-chips{display:flex;flex-wrap:wrap;gap:.35rem;margin:0 0 .5rem}
.pc-chips:empty{display:none}
.pc-chip{display:inline-block;padding:.12rem .55rem;border-radius:999px;background:var(--surface);
  border:1px solid var(--border);font-size:.72rem;font-weight:700;color:var(--muted)}
.pc-chip--top{background:var(--brand);border-color:var(--brand);color:#fff}

/* 結論ボックス */
.pc-top{margin:1rem 0 2rem;border:2px solid var(--brand);border-radius:16px;overflow:hidden;background:#fff}
.pc-top-label{margin:0;padding:.55rem 1.1rem;background:var(--brand);color:#fff;font-weight:700;
  font-size:.9rem;letter-spacing:.06em}
.pc-top-body{display:grid;grid-template-columns:160px 1fr;gap:1.1rem;padding:1.1rem}
.pc-top-thumb,.pc-thumb,.pc-cmp-thumb{display:flex;align-items:center;justify-content:center;
  background:#fff;border:1px solid var(--border);border-radius:12px;overflow:hidden;aspect-ratio:1/1}
.pc-top-thumb img,.pc-thumb img,.pc-cmp-thumb img{width:100%;height:100%;object-fit:contain}
.pc-top-thumb--empty,.pc-thumb--empty,.pc-cmp-thumb--empty{font-size:.75rem;color:var(--muted)}

/* 商品カード */
.pc-card{display:grid;grid-template-columns:200px 1fr;gap:1.25rem;margin:1rem 0 1.5rem;padding:1.25rem;
  border:1px solid var(--border);border-radius:16px;background:#fff}
.pc-card--top{border:2px solid var(--brand)}

/* 比較表 */
.pc-compare{overflow-x:auto;margin:1rem 0 .4rem;border:1px solid var(--border);border-radius:14px;
  -webkit-overflow-scrolling:touch}
.pc-compare table{border-collapse:separate;border-spacing:0;min-width:100%;font-size:.86rem}
.pc-compare th,.pc-compare td{padding:.75rem .8rem;border-bottom:1px solid var(--border);
  vertical-align:top;text-align:left;min-width:170px;background:#fff}
.pc-compare tr:last-child th,.pc-compare tr:last-child td{border-bottom:0}
.pc-compare tbody th,.pc-compare .pc-corner{position:sticky;left:0;z-index:1;min-width:76px;
  width:76px;background:var(--surface);color:var(--muted);font-weight:700;font-size:.78rem}
.pc-compare thead th{font-weight:700}
.pc-compare .is-top{background:var(--brand-soft)}
.pc-compare .pc-chip{margin:0 0 .45rem}
.pc-cmp-thumb{width:110px;margin:0 0 .5rem}
.pc-cmp-name{display:block;line-height:1.45;font-size:.84rem}
.pc-compare .pc-price{margin:0}
.pc-compare .pc-price-num{font-size:1.05rem}
.pc-compare .pc-price-note{display:block;margin:0}
.pc-compare .pc-buy{min-height:40px;padding:.5rem .9rem;font-size:.82rem;width:100%}
.pc-compare-note{font-size:.75rem;color:var(--muted);margin:0 0 2rem}

/* 箇条書きの種類 */
.pc-list{list-style:none;padding:.9rem 1rem .9rem 1rem;margin:.4rem 0 1.4rem;border-radius:12px;
  background:var(--surface)}
.pc-list li{position:relative;padding-left:1.7rem;margin:.35rem 0}
.pc-list li::before{position:absolute;left:0;top:.05rem;width:1.25rem;height:1.25rem;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:.72rem;font-weight:700;color:#fff}
.pc-list--fit li::before{content:"✓";background:var(--brand)}
.pc-list--pros li::before{content:"+";background:#2f9e44}
.pc-list--cons{background:#fff8f0}
.pc-list--cons li::before{content:"!";background:#e67700}
.pc-list--spec{background:#fff;border:1px solid var(--border)}
.pc-list--spec li::before{content:"";width:.45rem;height:.45rem;top:.65rem;left:.4rem;background:var(--muted)}

/* よくある質問 */
h3.pc-q{display:flex;gap:.6rem;align-items:flex-start;font-size:1rem}
h3.pc-q span{flex:none;display:inline-flex;align-items:center;justify-content:center;width:1.7rem;
  height:1.7rem;border-radius:50%;background:var(--brand);color:#fff;font-size:.85rem}

@media (max-width:640px){
  .pc-top-body{grid-template-columns:104px 1fr;gap:.85rem;padding:.9rem}
  .pc-card{grid-template-columns:1fr;padding:1rem}
  .pc-thumb{max-width:260px;width:100%;margin:0 auto}
  .pc-buy{width:100%}
  .pc-top .pc-buy{width:100%}
  .pc-price-num{font-size:1.2rem}
}
"""
