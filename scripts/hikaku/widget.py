"""比較表を読者のブラウザで描画するウィジェット。

なぜサーバー側で作らないのか:
  楽天APIは「Web Application」として登録すると、リクエストに正しいRefererが
  付いていることを要求する。GitHub Actionsからのサーバー呼び出しにはRefererが
  無いため弾かれる。読者のブラウザから呼べば本物のRefererが付くので、これが
  楽天の想定する正規の使い方になる。

  副次的な利点として、価格が常に最新になる。サーバー側で取得して埋め込む方式では、
  記事を書いた時点の価格が古いまま残り続ける問題があった。

Access Key について:
  ここで使う pk_ で始まるキーは、ブラウザに埋め込む前提の公開キー
  （Stripeの publishable key や Google Maps の API キーと同じ考え方）。
  楽天側の「Allowed websites」によるドメイン制限が防御になっている。
  他人がキーをコピーしても、自分のドメインからは呼べない。
"""

from __future__ import annotations

import json
from urllib.parse import quote

# 比較表を差し込む位置に置くプレースホルダ。記事本文の <!--TABLE--> と置き換わる。
PLACEHOLDER_CLASS = "hkg-live"      # 商品一覧（比較表）
STATS_CLASS = "hkg-stats"           # 集計セクション


def placeholder(keyword: str, hits: int = 3,
                min_price: int | None = None,
                max_price: int | None = None,
                sort: str = "-reviewCount") -> str:
    """記事ページに埋め込む、比較表の置き場所。

    中身には最初から検索リンクを入れておき、JavaScriptが成功したら置き換える。
    こうしておくと、スクリプトが読み込めない・JSが無効・通信が失敗した、
    のいずれの場合でも読者は楽天の検索結果へ進める。空欄になることがない。
    """
    from html import escape

    attrs = [
        # hkg-wrap も付ける。CSS変数(--hkg-*)は .hkg-wrap に定義されているため、
        # これが無いと枠線・背景・バッジの色がすべて無効になる。
        f'class="hkg-wrap {PLACEHOLDER_CLASS}"',
        f'data-keyword="{escape(keyword, quote=True)}"',
        f'data-hits="{hits}"',
        f'data-sort="{sort}"',
    ]
    if min_price is not None:
        attrs.append(f'data-min-price="{min_price}"')
    if max_price is not None:
        attrs.append(f'data-max-price="{max_price}"')

    search = ("https://search.rakuten.co.jp/search/mall/"
              + quote(keyword) + "/?s=4")

    return (
        f'<div {" ".join(attrs)}>\n'
        f'  <div class="hkg-fallback">\n'
        f'    <p>商品情報を読み込んでいます…</p>\n'
        f'    <p><a class="hkg-btn hkg-btn--rakuten" href="{escape(search, quote=True)}"\n'
        f'       target="_blank" rel="sponsored nofollow noopener">'
        f'楽天市場で「{escape(keyword)}」を検索する</a></p>\n'
        f'  </div>\n'
        f'</div>'
    )


def stats_placeholder(keyword: str,
                      min_price: int | None = None,
                      max_price: int | None = None) -> str:
    """統計セクションの置き場所。

    読者のブラウザが楽天APIを複数ページぶん呼んで集計し、ここへ描画する。
    解説文は記事側（静的HTML）にあり、数値だけが動的なので、
    検索エンジンには文章が読まれ、数値は常に最新になる。
    """
    from html import escape
    attrs = [
        f'class="hkg-wrap {STATS_CLASS}"',
        f'data-keyword="{escape(keyword, quote=True)}"',
    ]
    if min_price is not None:
        attrs.append(f'data-min-price="{min_price}"')
    if max_price is not None:
        attrs.append(f'data-max-price="{max_price}"')
    return (
        f'<div {" ".join(attrs)}>\n'
        f'  <p class="hkg-loading">集計しています…</p>\n'
        f'</div>'
    )


JS_TEMPLATE = r"""/* 楽天 比較表・集計ウィジェット（自動生成。編集しないこと） */
(function () {
  "use strict";

  var CONFIG = __CONFIG__;
  var ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";

  // 同じ条件のリクエストは1回だけ投げる
  var cache = {};

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function yen(n) { return Number(n).toLocaleString("ja-JP") + "円"; }
  function num(n) { return Number(n).toLocaleString("ja-JP"); }

  function stars(rating) {
    var full = Math.floor(rating);
    var half = rating - full >= 0.5 ? 1 : 0;
    return "★".repeat(full) + (half ? "◐" : "") + "☆".repeat(5 - full - half);
  }
  function searchUrl(k) {
    return "https://search.rakuten.co.jp/search/mall/" + encodeURIComponent(k) + "/";
  }

  /* ---------------- 取得 ---------------- */

  function request(box, opts) {
    var params = new URLSearchParams({
      applicationId: CONFIG.applicationId,
      accessKey: CONFIG.accessKey,
      keyword: box.getAttribute("data-keyword") || "",
      hits: String(opts.hits || 3),
      sort: opts.sort || "-reviewCount",
      format: "json"
    });
    if (opts.page) params.set("page", String(opts.page));
    if (CONFIG.affiliateId) params.set("affiliateId", CONFIG.affiliateId);
    var lo = box.getAttribute("data-min-price");
    var hi = box.getAttribute("data-max-price");
    if (lo) params.set("minPrice", lo);
    if (hi) params.set("maxPrice", hi);

    var key = params.toString();
    if (cache[key]) return cache[key];

    cache[key] = fetch(ENDPOINT + "?" + params).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      return {
        total: Number(data.count || 0),
        items: (data.Items || []).map(function (row) { return row.Item || row; })
      };
    });
    return cache[key];
  }

  /* ---------------- 集計セクション ---------------- */

  function median(values) {
    if (!values.length) return null;
    var s = values.slice().sort(function (a, b) { return a - b; });
    var m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
  }

  function summarize(items, total) {
    var prices = [], rated = [], freeShip = 0;
    items.forEach(function (it) {
      if (it.itemPrice > 0) prices.push(Number(it.itemPrice));
      var r = parseFloat(it.reviewAverage);
      if (r > 0 && Number(it.reviewCount) > 0) {
        rated.push({ price: Number(it.itemPrice), rating: r, reviews: Number(it.reviewCount) });
      }
      if (it.postageFlag === 0) freeShip++;
    });
    if (!prices.length) return null;

    // 価格で三分割し、安い層と高い層の平均評価を比べる
    var byPrice = rated.slice().sort(function (a, b) { return a.price - b.price; });
    var third = Math.floor(byPrice.length / 3);
    function avgRating(arr) {
      if (!arr.length) return null;
      return arr.reduce(function (s, x) { return s + x.rating; }, 0) / arr.length;
    }
    var cheap = third >= 3 ? avgRating(byPrice.slice(0, third)) : null;
    var pricey = third >= 3 ? avgRating(byPrice.slice(-third)) : null;

    return {
      sampled: items.length,
      total: total,
      priceMedian: median(prices),
      priceMin: Math.min.apply(null, prices),
      priceMax: Math.max.apply(null, prices),
      ratingAvg: avgRating(rated),
      highRatedPct: rated.length
        ? Math.round(rated.filter(function (x) { return x.rating >= 4.5; }).length / rated.length * 100)
        : null,
      freeShipPct: Math.round(freeShip / items.length * 100),
      cheapAvg: cheap,
      priceyAvg: pricey,
      cheapBound: third >= 3 ? byPrice[third - 1].price : null,
      priceyBound: third >= 3 ? byPrice[byPrice.length - third].price : null
    };
  }

  function priceComment(s) {
    // 数値から導ける範囲でだけ書く。差が小さいときに「相関がある」とは言わない。
    if (s.cheapAvg == null || s.priceyAvg == null) return "";
    var diff = s.priceyAvg - s.cheapAvg;
    var text;
    if (Math.abs(diff) < 0.1) {
      text = "価格帯による評価の差はほとんどありません。高い製品を選んでも満足度が上がるとは限らないため、" +
             "予算を上げる前に、自分に必要な機能があるかを先に確認したほうが無駄がありません。";
    } else if (diff > 0) {
      text = "価格が高い層のほうが平均評価は高くなっていますが、差は " + diff.toFixed(2) +
             " ポイントです。この差を大きいと見るかは、追加で払う金額に見合うかどうかで判断してください。";
    } else {
      text = "価格が安い層のほうが平均評価は高くなっています。高価格帯の製品は用途が限定されるものが多く、" +
             "合わない人が低評価を付けている可能性があります。";
    }
    return '<p class="hkg-stats-note">' + text + "</p>";
  }

  function renderStats(box, s) {
    if (!s) { box.innerHTML = '<p class="hkg-loading">集計できるデータがありませんでした。</p>'; return; }

    var rows = [
      ["集計した商品数", num(s.sampled) + "件（該当商品は全" + num(s.total) + "件）"],
      ["価格の中央値", yen(s.priceMedian)],
      ["価格の範囲", yen(s.priceMin) + " 〜 " + yen(s.priceMax)]
    ];
    if (s.ratingAvg != null) rows.push(["平均レビュー評価", s.ratingAvg.toFixed(2) + " / 5.00"]);
    if (s.highRatedPct != null) rows.push(["評価4.5以上の割合", s.highRatedPct + "%"]);
    rows.push(["送料無料の割合", s.freeShipPct + "%"]);
    if (s.cheapAvg != null) {
      rows.push([yen(s.cheapBound) + "以下の平均評価", s.cheapAvg.toFixed(2)]);
      rows.push([yen(s.priceyBound) + "以上の平均評価", s.priceyAvg.toFixed(2)]);
    }

    box.innerHTML =
      '<table class="hkg-stats-table"><tbody>' +
      rows.map(function (r) {
        return '<tr><th scope="row">' + esc(r[0]) + "</th><td>" + esc(r[1]) + "</td></tr>";
      }).join("") +
      "</tbody></table>" +
      priceComment(s) +
      '<p class="hkg-updated">楽天市場の検索結果をこのページを開いた時点で集計したものです。' +
      "レビュー件数が0件の商品は評価の計算から除いています。</p>";
  }

  function startStats(box) {
    // 3ページぶん（最大90件）取って集計する
    Promise.all([1, 2, 3].map(function (p) {
      return request(box, { hits: 30, sort: "-reviewCount", page: p })
        .catch(function () { return { total: 0, items: [] }; });
    })).then(function (pages) {
      var items = [], total = 0;
      pages.forEach(function (p) {
        items = items.concat(p.items);
        if (p.total > total) total = p.total;
      });
      if (!items.length) throw new Error("empty");
      renderStats(box, summarize(items, total));
    }).catch(function (err) {
      if (window.console) console.warn("[rakuten-stats]", err);
      box.innerHTML = '<p class="hkg-loading">集計データを取得できませんでした。</p>';
    });
  }

  /* ---------------- 商品一覧（比較表） ---------------- */

  var SORTS = [
    { key: "-reviewCount",   label: "レビュー数順", rank: "レビュー数" },
    { key: "+itemPrice",     label: "価格が安い順", rank: "最安" },
    { key: "-reviewAverage", label: "評価が高い順", rank: "高評価",
      caveat: "評価順はレビューが1件だけの商品も上位に来ます。件数とあわせて見てください。" }
  ];

  function card(item, rank, sortDef) {
    var image = "";
    var urls = item.mediumImageUrls || [];
    if (urls.length) {
      var raw = typeof urls[0] === "string" ? urls[0] : urls[0].imageUrl;
      image = String(raw).split("?")[0];
    }

    var meta = [];
    var rating = parseFloat(item.reviewAverage);
    if (rating > 0) {
      meta.push('<span><span class="hkg-stars">' + stars(rating) + "</span> " + rating.toFixed(2) +
        (item.reviewCount ? "（" + num(item.reviewCount) + "件）" : "") + "</span>");
    }
    if (item.shopName) meta.push("<span>" + esc(item.shopName) + "</span>");
    if (item.postageFlag === 0) meta.push("<span>送料無料</span>");

    // 順位は「何の順か」を必ず添える。編集部が評価したわけではないため。
    var badge = rank === 1
      ? '<span class="hkg-badge">' + esc(sortDef.rank) + " 1位</span>" : "";

    var catch_ = item.catchcopy
      ? '<p class="hkg-catch"><span>ショップ紹介文</span>' + esc(item.catchcopy) + "</p>" : "";

    return '<article class="' + (rank === 1 ? "hkg-card hkg-card--rec" : "hkg-card") + '">' +
      '<span class="hkg-rank">' + rank + "</span>" +
      (image
        ? '<div class="hkg-thumb"><img src="' + esc(image) + '" alt="" loading="lazy" decoding="async"></div>'
        : '<div class="hkg-thumb hkg-thumb--empty">画像なし</div>') +
      "<div>" + badge +
      '<h3 class="hkg-name">' + esc(item.itemName) + "</h3>" +
      '<p class="hkg-price">' + yen(item.itemPrice) + "<small>税込</small></p>" +
      '<div class="hkg-meta">' + meta.join("") + "</div>" + catch_ +
      '<div class="hkg-btns"><a class="hkg-btn hkg-btn--rakuten" href="' +
      esc(item.affiliateUrl || item.itemUrl) +
      '" target="_blank" rel="sponsored nofollow noopener">楽天市場で価格を見る</a>' +
      "</div></div></article>";
  }

  function specTable(items) {
    var head = items.map(function (it) {
      var n = it.itemName.length > 22 ? it.itemName.slice(0, 21) + "…" : it.itemName;
      return '<th scope="col">' + esc(n) + "</th>";
    }).join("");
    var rows = [
      '<tr><th scope="row">価格</th>' + items.map(function (it) {
        return "<td>" + yen(it.itemPrice) + "</td>"; }).join("") + "</tr>",
      '<tr><th scope="row">評価</th>' + items.map(function (it) {
        var r = parseFloat(it.reviewAverage);
        return "<td>" + (r > 0 ? r.toFixed(2) : "—") + "</td>"; }).join("") + "</tr>",
      '<tr><th scope="row">レビュー数</th>' + items.map(function (it) {
        return "<td>" + (it.reviewCount ? num(it.reviewCount) + "件" : "—") + "</td>"; }).join("") + "</tr>",
      '<tr><th scope="row">送料</th>' + items.map(function (it) {
        return "<td>" + (it.postageFlag === 0 ? "無料" : "別途") + "</td>"; }).join("") + "</tr>",
      '<tr><th scope="row">ショップ</th>' + items.map(function (it) {
        return "<td>" + esc(it.shopName) + "</td>"; }).join("") + "</tr>"
    ].join("");
    return '<div class="hkg-tablewrap"><table class="hkg-table"><thead><tr>' +
      '<th scope="col">項目</th>' + head + "</tr></thead><tbody>" + rows +
      "</tbody></table></div><p class=\"hkg-scrollhint\">※ 表は横にスクロールできます</p>";
  }

  function renderTable(box, sortDef, items) {
    if (!items.length) { fallback(box, "該当する商品が見つかりませんでした。"); return; }
    var now = new Date();
    var stamp = now.getFullYear() + "年" + (now.getMonth() + 1) + "月" + now.getDate() + "日";

    var tabs = '<div class="hkg-tabs" role="tablist">' + SORTS.map(function (s) {
      return '<button type="button" role="tab" data-sort="' + s.key + '"' +
        (s.key === sortDef.key ? ' class="is-active" aria-selected="true"' : ' aria-selected="false"') +
        ">" + esc(s.label) + "</button>";
    }).join("") + "</div>";

    var caveat = sortDef.caveat
      ? '<p class="hkg-scrollhint">' + esc(sortDef.caveat) + "</p>" : "";

    box.innerHTML = tabs + caveat +
      '<div class="hkg-cards">' +
      items.map(function (it, i) { return card(it, i + 1, sortDef); }).join("") +
      "</div>" + specTable(items) +
      '<p class="hkg-updated">価格・在庫はこのページを開いた時点（' + stamp +
      "）の楽天市場の情報です。並び順は楽天の検索結果に基づくもので、" +
      "当サイトが商品を評価したものではありません。</p>";

    box.querySelectorAll(".hkg-tabs button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var def = SORTS.filter(function (s) { return s.key === btn.getAttribute("data-sort"); })[0];
        if (!def || def.key === sortDef.key) return;
        loadTable(box, def);
      });
    });
  }

  function loadTable(box, sortDef) {
    var hits = parseInt(box.getAttribute("data-hits") || "4", 10);
    request(box, { hits: hits, sort: sortDef.key }).then(function (res) {
      renderTable(box, sortDef, res.items);
    }).catch(function (err) {
      if (window.console) console.warn("[rakuten-table]", err);
      fallback(box, "商品情報を取得できませんでした。");
    });
  }

  function fallback(box, message) {
    var keyword = box.getAttribute("data-keyword") || "";
    box.innerHTML = '<div class="hkg-fallback"><p>' + esc(message) + "</p>" +
      '<p><a class="hkg-btn hkg-btn--rakuten" href="' + esc(searchUrl(keyword)) +
      '" target="_blank" rel="sponsored nofollow noopener">楽天市場で「' +
      esc(keyword) + '」を検索する</a></p></div>';
  }

  /* ---------------- 起動 ---------------- */

  function start() {
    var tables = document.querySelectorAll("." + CONFIG.placeholderClass);
    var statsBoxes = document.querySelectorAll("." + CONFIG.statsClass);
    if (!tables.length && !statsBoxes.length) return;

    if (!CONFIG.applicationId || !CONFIG.accessKey) {
      Array.prototype.forEach.call(tables, function (b) { fallback(b, "比較表の設定が未完了です。"); });
      Array.prototype.forEach.call(statsBoxes, function (b) { b.innerHTML = ""; });
      return;
    }
    Array.prototype.forEach.call(tables, function (b) {
      b.innerHTML = '<p class="hkg-loading">商品情報を読み込んでいます…</p>';
      loadTable(b, SORTS[0]);
    });
    Array.prototype.forEach.call(statsBoxes, startStats);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else { start(); }
})();
"""


def build_js(application_id: str, access_key: str, affiliate_id: str = "") -> str:
    """config.json の値を埋め込んだウィジェットJSを返す。"""
    config = {
        "applicationId": application_id,
        "accessKey": access_key,
        "affiliateId": affiliate_id,
        "placeholderClass": PLACEHOLDER_CLASS,
        "statsClass": STATS_CLASS,
    }
    return JS_TEMPLATE.replace("__CONFIG__", json.dumps(config, ensure_ascii=False))


# ウィジェット用に追加で必要なCSS（既存の hkg- 系に足す）
EXTRA_CSS = """
.hkg-catch{font-size:.8rem;color:var(--hkg-muted);margin:0 0 .6rem;line-height:1.6}
.hkg-catch span{display:inline-block;margin-right:.5rem;padding:.05rem .45rem;
  border:1px solid var(--hkg-border);border-radius:4px;font-size:.68rem}
.hkg-loading{font-size:.88rem;color:var(--hkg-muted);padding:1.5rem 0;text-align:center}
.hkg-fallback{padding:1.2rem;border:1px solid var(--hkg-border);border-radius:12px;
  background:var(--hkg-card);text-align:center}
.hkg-fallback p{margin:0 0 .8rem;font-size:.88rem;color:var(--hkg-muted)}
.hkg-fallback p:last-child{margin:0}
.hkg-fallback .hkg-btn{flex:0 1 auto;padding:.6rem 1.2rem}

/* 並び替えタブ */
.hkg-tabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1rem}
.hkg-tabs button{padding:.5rem 1rem;border:1px solid var(--hkg-border);border-radius:999px;
  background:var(--hkg-card);color:var(--hkg-muted);font-size:.82rem;font-weight:700;
  cursor:pointer;font-family:inherit}
.hkg-tabs button:hover{color:var(--hkg-fg)}
.hkg-tabs button.is-active{background:var(--hkg-accent);border-color:var(--hkg-accent);color:#fff}

/* 集計表 */
.hkg-stats-table{width:100%;border-collapse:collapse;font-size:.88rem;
  border:1px solid var(--hkg-border);border-radius:10px;overflow:hidden}
.hkg-stats-table th,.hkg-stats-table td{padding:.6rem .9rem;text-align:left;
  border-bottom:1px solid var(--hkg-border)}
.hkg-stats-table th{width:48%;font-weight:500;color:var(--hkg-muted);background:var(--hkg-card)}
.hkg-stats-table td{font-weight:700}
.hkg-stats-table tr:last-child th,.hkg-stats-table tr:last-child td{border-bottom:0}
.hkg-stats-note{font-size:.88rem;line-height:1.8;margin:1rem 0 0;padding:.9rem 1.1rem;
  background:var(--hkg-accent-soft);border-radius:8px}
@media (max-width:600px){.hkg-stats-table th{width:52%}}
"""
