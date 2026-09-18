/* 楽天商品比較表ウィジェット（自動生成。編集しないこと） */
(function () {
  "use strict";

  var CONFIG = {"applicationId": "f805f3ec-aee5-4559-8dfe-78621a3ed4d4", "accessKey": "pk_dIcRpCq4iXdYzJe34Ew2iqQ8jfjiUV3uuyzWWYYdnWs", "affiliateId": "57989289.47524eba.5798928a.3cd1bfae", "placeholderClass": "hkg-live"};
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
