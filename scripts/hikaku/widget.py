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
PLACEHOLDER_CLASS = "hkg-live"


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


JS_TEMPLATE = r"""/* 楽天商品比較表ウィジェット（自動生成。編集しないこと） */
(function () {
  "use strict";

  var CONFIG = __CONFIG__;
  var ENDPOINT = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";

  // 同じキーワードを複数箇所で使っても1回しか取りに行かないようにする
  var cache = {};

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function yen(n) {
    return Number(n).toLocaleString("ja-JP") + "円";
  }

  function stars(rating) {
    var full = Math.floor(rating);
    var half = rating - full >= 0.5 ? 1 : 0;
    return "★".repeat(full) + (half ? "◐" : "") + "☆".repeat(5 - full - half);
  }

  function searchUrl(keyword) {
    return "https://search.rakuten.co.jp/search/mall/" + encodeURIComponent(keyword) + "/";
  }

  function fetchItems(box) {
    var keyword = box.getAttribute("data-keyword") || "";
    var hits = box.getAttribute("data-hits") || "3";
    var sort = box.getAttribute("data-sort") || "-reviewCount";
    var minPrice = box.getAttribute("data-min-price");
    var maxPrice = box.getAttribute("data-max-price");

    var params = new URLSearchParams({
      applicationId: CONFIG.applicationId,
      accessKey: CONFIG.accessKey,
      keyword: keyword,
      hits: hits,
      sort: sort,
      format: "json"
    });
    if (CONFIG.affiliateId) params.set("affiliateId", CONFIG.affiliateId);
    if (minPrice) params.set("minPrice", minPrice);
    if (maxPrice) params.set("maxPrice", maxPrice);

    var key = params.toString();
    if (cache[key]) return cache[key];

    cache[key] = fetch(ENDPOINT + "?" + params).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      // 応答形式の揺れ（Items[].Item と Items[] のどちらでも動くように）
      return (data.Items || []).map(function (row) { return row.Item || row; });
    });
    return cache[key];
  }

  function card(item, rank) {
    var image = "";
    var urls = item.mediumImageUrls || [];
    if (urls.length) {
      var raw = typeof urls[0] === "string" ? urls[0] : urls[0].imageUrl;
      // 末尾の ?_ex=128x128 を外すと大きい画像が取れる
      image = String(raw).split("?")[0];
    }

    var meta = [];
    var rating = parseFloat(item.reviewAverage);
    if (rating > 0) {
      meta.push('<span><span class="hkg-stars">' + stars(rating) + "</span> " +
        rating.toFixed(2) +
        (item.reviewCount ? "（" + Number(item.reviewCount).toLocaleString("ja-JP") + "件）" : "") +
        "</span>");
    }
    if (item.shopName) meta.push("<span>" + esc(item.shopName) + "</span>");
    if (item.postageFlag === 0) meta.push("<span>送料無料</span>");

    var badge = rank === 1
      ? '<span class="hkg-badge">レビュー数1位</span>' : "";

    // catchcopy は出品者が書いた宣伝文。編集部の評価と混同されないよう、
    // 出典を明示したうえで控えめな見た目にする。
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
      '<div class="hkg-meta">' + meta.join("") + "</div>" +
      catch_ +
      '<div class="hkg-btns">' +
      '<a class="hkg-btn hkg-btn--rakuten" href="' + esc(item.affiliateUrl || item.itemUrl) +
      '" target="_blank" rel="sponsored nofollow noopener">楽天市場で価格を見る</a>' +
      "</div></div></article>";
  }

  function specTable(items) {
    var head = items.map(function (it) {
      var name = it.itemName.length > 22 ? it.itemName.slice(0, 21) + "…" : it.itemName;
      return '<th scope="col">' + esc(name) + "</th>";
    }).join("");

    var rows = [
      '<tr><th scope="row">価格</th>' +
      items.map(function (it) { return "<td>" + yen(it.itemPrice) + "</td>"; }).join("") + "</tr>",
      '<tr><th scope="row">評価</th>' +
      items.map(function (it) {
        var r = parseFloat(it.reviewAverage);
        return "<td>" + (r > 0 ? r.toFixed(2) : "—") + "</td>";
      }).join("") + "</tr>",
      '<tr><th scope="row">レビュー数</th>' +
      items.map(function (it) {
        return "<td>" + (it.reviewCount ? Number(it.reviewCount).toLocaleString("ja-JP") + "件" : "—") + "</td>";
      }).join("") + "</tr>",
      '<tr><th scope="row">送料</th>' +
      items.map(function (it) {
        return "<td>" + (it.postageFlag === 0 ? "無料" : "別途") + "</td>";
      }).join("") + "</tr>",
      '<tr><th scope="row">ショップ</th>' +
      items.map(function (it) { return "<td>" + esc(it.shopName) + "</td>"; }).join("") + "</tr>"
    ].join("");

    return '<div class="hkg-tablewrap"><table class="hkg-table">' +
      '<thead><tr><th scope="col">項目</th>' + head + "</tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>" +
      '<p class="hkg-scrollhint">※ 表は横にスクロールできます</p>';
  }

  function render(box, items) {
    if (!items.length) {
      fallback(box, "該当する商品が見つかりませんでした。");
      return;
    }
    var now = new Date();
    var stamp = now.getFullYear() + "年" + (now.getMonth() + 1) + "月" + now.getDate() + "日";

    box.innerHTML =
      '<div class="hkg-cards">' +
      items.map(function (it, i) { return card(it, i + 1); }).join("") +
      "</div>" +
      specTable(items) +
      '<p class="hkg-updated">価格・在庫はこのページを開いた時点（' + stamp +
      '）の楽天市場の情報です。</p>';
  }

  function fallback(box, message) {
    var keyword = box.getAttribute("data-keyword") || "";
    box.innerHTML =
      '<div class="hkg-fallback">' +
      "<p>" + esc(message) + "</p>" +
      '<p><a class="hkg-btn hkg-btn--rakuten" href="' + esc(searchUrl(keyword)) +
      '" target="_blank" rel="sponsored nofollow noopener">楽天市場で「' +
      esc(keyword) + '」を検索する</a></p></div>';
  }

  function loading(box) {
    box.innerHTML = '<p class="hkg-loading">商品情報を読み込んでいます…</p>';
  }

  function start() {
    var boxes = document.querySelectorAll("." + CONFIG.placeholderClass);
    if (!boxes.length) return;

    if (!CONFIG.applicationId || !CONFIG.accessKey) {
      Array.prototype.forEach.call(boxes, function (box) {
        fallback(box, "比較表の設定が未完了です。");
      });
      return;
    }

    Array.prototype.forEach.call(boxes, function (box) {
      loading(box);
      fetchItems(box).then(function (items) {
        render(box, items);
      }).catch(function (err) {
        // 失敗しても記事は読めるべきなので、検索リンクだけ残す
        if (window.console) console.warn("[rakuten-table]", err);
        fallback(box, "商品情報を取得できませんでした。");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
"""


def build_js(application_id: str, access_key: str, affiliate_id: str = "") -> str:
    """config.json の値を埋め込んだウィジェットJSを返す。"""
    config = {
        "applicationId": application_id,
        "accessKey": access_key,
        "affiliateId": affiliate_id,
        "placeholderClass": PLACEHOLDER_CLASS,
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
"""
