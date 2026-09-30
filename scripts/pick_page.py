"""商品を選ぶページ（mekikilab.com/pick/）。

朝のメールのボタンからここを開き、記事で紹介する商品を選ぶ。
選んだ商品は Cloudflare Worker に送られ、そこから記事の執筆が始まる。

なぜこのページで楽天を検索するのか:
  楽天の公開キーは「自分のサイトから呼ぶ」専用で、GitHub Actions のような
  サーバーからは呼べない。運営者がこのページを開くと、運営者のブラウザが
  自分のサイト（mekikilab.com）から楽天を検索する。これが楽天の想定する使い方。

URLに付くもの:
  k  … 記事の slug（keywords.json のもの）
  t  … 署名トークン。Worker がこれを確かめ、本人のメールからの依頼だと判断する
  q / min / max / kw … 楽天の検索条件と、画面に出すキーワード
"""

from __future__ import annotations

import json
from html import escape

# 楽天の商品検索API。rakuten-table.js（hikaku/widget.py）と同じものを使う
ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"


def render(config: dict) -> str:
    rakuten = config.get("rakuten_client", {})
    settings = {
        "endpoint": ENDPOINT,
        "applicationId": rakuten.get("application_id", ""),
        "accessKey": rakuten.get("access_key", ""),
        "affiliateId": rakuten.get("affiliate_id", ""),
        "worker": config.get("worker_base_url", "").rstrip("/"),
        "min": int(config.get("pick_min", 2)),
        "max": int(config.get("pick_max", 5)),
    }
    prefix = escape(config.get("path_prefix", "/"))
    title = escape(config.get("site_title", ""))
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>商品を選ぶ｜{title}</title>
<link rel="stylesheet" href="{prefix}style.css">
<style>
body{{padding-bottom:110px}}
.pk-head{{padding:28px 0 8px}}
.pk-head h1{{font-size:1.45rem;margin:.2rem 0 .5rem}}
.pk-kw{{display:inline-block;padding:.2rem .7rem;border-radius:999px;background:var(--brand-soft);
  color:var(--brand);font-weight:700;font-size:.85rem}}
.pk-help{{font-size:.88rem;color:var(--muted);margin:.6rem 0 0}}
.pk-state{{margin:28px 0;padding:22px;border-radius:16px;background:var(--surface);text-align:center;
  font-size:.95rem}}
.pk-state h2{{border:0;padding:0;margin:0 0 .6rem;font-size:1.2rem}}
.pk-state p{{margin:0}}
.pk-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px;margin:18px 0}}
.pk-item{{position:relative;display:flex;flex-direction:column;border:2px solid var(--border);
  border-radius:14px;background:#fff;cursor:pointer;transition:border-color .15s}}
.pk-item.is-on{{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}}
.pk-item input{{position:absolute;top:10px;left:10px;width:22px;height:22px;accent-color:var(--brand)}}
.pk-order{{position:absolute;top:8px;right:8px;min-width:26px;height:26px;border-radius:8px;
  background:var(--brand);color:#fff;font-weight:700;font-size:.85rem;display:none;
  align-items:center;justify-content:center}}
.pk-item.is-on .pk-order{{display:flex}}
.pk-img{{aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;
  border-bottom:1px solid var(--border);border-radius:12px 12px 0 0;overflow:hidden}}
.pk-img img{{width:100%;height:100%;object-fit:contain;padding:10px}}
.pk-body{{padding:10px 12px 12px;display:flex;flex-direction:column;gap:4px;flex:1;font-size:.84rem}}
.pk-name{{font-weight:700;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;
  -webkit-box-orient:vertical;overflow:hidden}}
.pk-price{{font-size:1.1rem;font-weight:700}}
.pk-meta{{color:var(--muted);font-size:.78rem}}
.pk-rec{{align-self:flex-start;padding:.05rem .5rem;border-radius:999px;background:#fff4e6;
  color:#d9480f;font-size:.72rem;font-weight:700}}
.pk-link{{margin-top:auto;font-size:.8rem;font-weight:700}}
.pk-bar{{position:fixed;left:0;right:0;bottom:0;z-index:20;background:rgba(255,255,255,.97);
  border-top:1px solid var(--border);padding:12px 20px calc(12px + env(safe-area-inset-bottom))}}
.pk-bar .container{{display:flex;align-items:center;gap:14px;max-width:1040px}}
.pk-count{{font-size:.9rem;font-weight:700;flex:1}}
.pk-count small{{display:block;font-weight:400;color:var(--muted);font-size:.76rem}}
.pk-submit{{min-height:52px;padding:.8rem 1.6rem;border:0;border-radius:12px;background:var(--cta);
  color:#fff;font-size:1rem;font-weight:700;cursor:pointer;font-family:inherit}}
.pk-submit:disabled{{background:#c9ccd1;cursor:not-allowed}}
@media (max-width:640px){{.pk-grid{{grid-template-columns:1fr 1fr;gap:10px}}
  .pk-bar .container{{gap:10px}}.pk-submit{{padding:.8rem 1rem}}}}
</style>
</head>
<body>
<header class="site"><div class="container"><a class="brand" href="{prefix}">{title}</a></div></header>
<div class="container container--wide">
  <section class="pk-head">
    <span class="pk-kw" id="kw">…</span>
    <h1>記事で紹介する商品を選んでください</h1>
    <p class="pk-help">楽天市場の検索結果（レビュー数の多い順）です。
      おすすめの3つに最初から印を付けています。入れ替えて、2〜5個を選んでください。
      押した順が、あとで企画担当が順位を決めるときの参考になります。</p>
  </section>
  <div id="state" class="pk-state"><p>楽天市場から候補を読み込んでいます…</p></div>
  <div id="grid" class="pk-grid" hidden></div>
</div>
<div class="pk-bar" id="bar" hidden><div class="container">
  <p class="pk-count" id="count">0個を選択中</p>
  <button class="pk-submit" id="submit" disabled>この商品で記事を書く</button>
</div></div>
<script>
(function () {{
  "use strict";
  var S = {json.dumps(settings, ensure_ascii=False)};
  var q = new URLSearchParams(location.search);
  var slug = q.get("k") || "", token = q.get("t") || "";
  var state = document.getElementById("state"), grid = document.getElementById("grid");
  var bar = document.getElementById("bar"), countEl = document.getElementById("count");
  var submit = document.getElementById("submit");
  var items = [], market = null, order = [];

  function esc(s) {{
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {{
      return {{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}}[c];
    }});
  }}
  function yen(n) {{ return Number(n).toLocaleString("ja-JP") + "円"; }}
  function show(title, message) {{
    state.hidden = false; grid.hidden = true; bar.hidden = true;
    state.innerHTML = (title ? "<h2>" + esc(title) + "</h2>" : "") + "<p>" + message + "</p>";
  }}
  function today() {{
    // 日本時間の日付。記事の「〇/〇時点」に使う
    var d = new Date(Date.now() + 9 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
  }}

  document.getElementById("kw").textContent = q.get("kw") || q.get("q") || "";
  if (!slug || !token || !q.get("q")) {{
    show("リンクが正しくありません", "朝のメールにあるボタンから開いてください。");
    return;
  }}
  var expires = parseInt(token.split(".")[0], 10);
  if (expires && expires * 1000 < Date.now()) {{
    show("このリンクは期限切れです", "新しいメールのボタンから開いてください。");
    return;
  }}

  /* ---------- 楽天から候補を取る ---------- */
  var params = new URLSearchParams({{
    applicationId: S.applicationId, accessKey: S.accessKey, keyword: q.get("q"),
    hits: "30", sort: "-reviewCount", imageFlag: "1", format: "json"
  }});
  if (S.affiliateId) params.set("affiliateId", S.affiliateId);
  if (q.get("min")) params.set("minPrice", q.get("min"));
  if (q.get("max")) params.set("maxPrice", q.get("max"));

  fetch(S.endpoint + "?" + params).then(function (r) {{
    if (!r.ok) throw new Error("楽天の応答が HTTP " + r.status + " でした");
    return r.json();
  }}).then(function (data) {{
    items = (data.Items || []).map(function (row) {{ return row.Item || row; }});
    if (!items.length) {{
      show("候補が見つかりませんでした", "検索条件（キーワードや価格帯）を見直す必要があります。");
      return;
    }}
    market = summarize(items, Number(data.count || items.length));
    render();
  }}).catch(function (e) {{
    show("候補を読み込めませんでした", esc(e.message) + "<br>時間をおいて開き直してください。");
  }});

  function median(v) {{
    var s = v.slice().sort(function (a, b) {{ return a - b; }}), m = Math.floor(s.length / 2);
    return s.length ? (s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2)) : 0;
  }}
  function summarize(list, total) {{
    var prices = list.map(function (it) {{ return Number(it.itemPrice) || 0; }})
                     .filter(function (n) {{ return n > 0; }});
    var rated = list.filter(function (it) {{ return Number(it.reviewCount) > 0; }});
    var free = list.filter(function (it) {{ return it.postageFlag === 0; }}).length;
    return {{
      total: total, sampled: list.length, priceMedian: median(prices),
      priceMin: Math.min.apply(null, prices), priceMax: Math.max.apply(null, prices),
      ratingAverage: rated.length ? rated.reduce(function (a, it) {{
        return a + Number(it.reviewAverage); }}, 0) / rated.length : 0,
      freeShippingRate: list.length ? free / list.length : 0
    }};
  }}
  // 評価の高さと件数の多さの両方を見る。件数が少ない高評価は偶然のことがある
  function score(it) {{
    var n = Number(it.reviewCount) || 0;
    return n < 3 ? 0 : (Number(it.reviewAverage) || 0) * Math.log10(n + 1);
  }}
  function image(it) {{
    var u = it.mediumImageUrls || [];
    if (!u.length) return "";
    return String(typeof u[0] === "string" ? u[0] : u[0].imageUrl).split("?")[0];
  }}

  /* ---------- 画面 ---------- */
  function render() {{
    var ranked = items.map(function (it, i) {{ return {{ i: i, s: score(it) }}; }})
      .sort(function (a, b) {{ return b.s - a.s; }});
    var rec = ranked.slice(0, 3).filter(function (r) {{ return r.s > 0; }})
      .map(function (r) {{ return r.i; }});
    order = rec.slice();
    // 印を付けた候補を先頭に。残りは楽天の並び（レビュー数の多い順）のまま
    var shown = rec.concat(items.map(function (_, i) {{ return i; }})
      .filter(function (i) {{ return rec.indexOf(i) < 0; }}));

    grid.innerHTML = shown.map(function (i) {{
      var it = items[i];
      var img = image(it);
      var rating = Number(it.reviewCount) > 0
        ? "★" + Number(it.reviewAverage).toFixed(2) + "（" + Number(it.reviewCount).toLocaleString("ja-JP") + "件）"
        : "レビューなし";
      return '<label class="pk-item" data-i="' + i + '">' +
        '<input type="checkbox" aria-label="この商品を選ぶ">' +
        '<span class="pk-order"></span>' +
        '<div class="pk-img">' + (img ? '<img src="' + esc(img) + '?_ex=300x300" alt="" loading="lazy">' : "画像なし") + "</div>" +
        '<div class="pk-body">' +
        (rec.indexOf(i) >= 0 ? '<span class="pk-rec">おすすめ候補</span>' : "") +
        '<span class="pk-name">' + esc(it.itemName) + "</span>" +
        '<span class="pk-price">' + yen(it.itemPrice) + "</span>" +
        '<span class="pk-meta">' + esc(rating) + "</span>" +
        '<span class="pk-meta">' + esc(it.shopName) + (it.postageFlag === 0 ? "・送料無料" : "") + "</span>" +
        // 運営者のクリックが紹介の成果に混ざらないよう、ここは通常の商品ページへ飛ばす
        '<a class="pk-link" href="' + esc(it.itemUrl) + '" target="_blank" rel="noopener">楽天で詳しく見る ↗</a>' +
        "</div></label>";
    }}).join("");

    Array.prototype.forEach.call(grid.querySelectorAll(".pk-item"), function (el) {{
      var box = el.querySelector("input");
      box.addEventListener("change", function () {{
        var i = Number(el.getAttribute("data-i")), at = order.indexOf(i);
        if (box.checked && at < 0) {{
          if (order.length >= S.max) {{ box.checked = false; return; }}
          order.push(i);
        }} else if (!box.checked && at >= 0) {{ order.splice(at, 1); }}
        paint();
      }});
      el.querySelector(".pk-link").addEventListener("click", function (e) {{ e.stopPropagation(); }});
    }});
    state.hidden = true; grid.hidden = false; bar.hidden = false;
    paint();
  }}

  function paint() {{
    Array.prototype.forEach.call(grid.querySelectorAll(".pk-item"), function (el) {{
      var i = Number(el.getAttribute("data-i")), at = order.indexOf(i);
      el.classList.toggle("is-on", at >= 0);
      el.querySelector("input").checked = at >= 0;
      el.querySelector(".pk-order").textContent = at >= 0 ? String(at + 1) : "";
    }});
    var n = order.length;
    countEl.innerHTML = n + "個を選択中<small>" + S.min + "〜" + S.max + "個まで選べます</small>";
    submit.disabled = n < S.min || n > S.max;
    submit.textContent = n ? "この" + n + "個で記事を書く" : "商品を選んでください";
  }}

  function product(it) {{
    return {{
      itemCode: it.itemCode, itemName: it.itemName, itemPrice: Number(it.itemPrice),
      itemUrl: it.itemUrl, affiliateUrl: it.affiliateUrl || it.itemUrl, imageUrl: image(it),
      reviewAverage: Number(it.reviewAverage) || 0, reviewCount: Number(it.reviewCount) || 0,
      postageFlag: it.postageFlag, shopName: it.shopName,
      catchcopy: String(it.catchcopy || "").slice(0, 200),
      itemCaption: String(it.itemCaption || "").slice(0, 1500),
      capturedAt: today()
    }};
  }}

  submit.addEventListener("click", function () {{
    if (submit.disabled) return;
    submit.disabled = true;
    submit.textContent = "送信しています…";
    fetch(S.worker + "/pick", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        slug: slug, token: token, market: market,
        products: order.map(function (i) {{ return product(items[i]); }})
      }})
    }}).then(function (r) {{
      return r.json().catch(function () {{ return {{}}; }}).then(function (body) {{
        if (!r.ok || !body.ok) throw new Error(body.error || ("HTTP " + r.status));
      }});
    }}).then(function () {{
      window.scrollTo(0, 0);
      show("執筆を始めました",
        "5人の担当が順番に記事を仕上げます。10〜15分ほどで公開され、メールでお知らせします。<br>" +
        "このページは閉じて大丈夫です。");
    }}).catch(function (e) {{
      submit.disabled = false; paint();
      alertBox("送信できませんでした：" + e.message);
    }});
  }});

  function alertBox(message) {{
    state.hidden = false;
    state.innerHTML = "<p>" + esc(message) + "</p>";
    window.scrollTo(0, 0);
  }}
}})();
</script>
</body>
</html>
"""
