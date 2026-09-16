"""楽天市場 商品検索API (IchibaItem/Search) クライアント。

アプリID（applicationId）は https://webservice.rakuten.co.jp/ で無料登録すればすぐ発行される。
アフィリエイトID（affiliateId）は楽天アフィリエイトの管理画面で確認できる。
affiliateId を渡すと、APIが返す affiliateUrl がそのまま成果対象リンクになる。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..models import Product

ENDPOINT = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"

# 楽天APIは概ね1秒1リクエストが上限。連続実行で弾かれないよう間隔を空ける。
_MIN_INTERVAL_SEC = 1.1
_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    elapsed = time.time() - _last_call_at
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _last_call_at = time.time()


def search(
    keyword: str,
    application_id: str,
    affiliate_id: str = "",
    hits: int = 5,
    sort: str = "-reviewCount",
    min_price: int | None = None,
    max_price: int | None = None,
    timeout: int = 20,
) -> list[Product]:
    """キーワードで商品を検索して Product のリストを返す。

    sort の例:
        "-reviewCount" レビュー件数が多い順（比較記事では基本これが無難）
        "+itemPrice"   価格が安い順
        "-reviewAverage" 評価が高い順（レビュー1件でも上に来るので注意）
    """
    if not application_id:
        raise ValueError("楽天アプリID(application_id)が設定されていません")

    params = {
        "applicationId": application_id,
        "keyword": keyword,
        "hits": max(1, min(hits, 30)),  # APIの上限は30件
        "sort": sort,
        "format": "json",
        # 必要なフィールドだけ受け取ってレスポンスを軽くする
        "elements": ",".join([
            "itemName", "itemPrice", "itemUrl", "affiliateUrl", "shopName",
            "reviewAverage", "reviewCount", "postageFlag",
            "mediumImageUrls", "itemCode",
        ]),
    }
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    if min_price is not None:
        params["minPrice"] = min_price
    if max_price is not None:
        params["maxPrice"] = max_price

    payload = _request(params, timeout)
    return [_to_product(entry.get("Item", {})) for entry in payload.get("Items", [])]


def _request(params: dict, timeout: int = 20) -> dict:
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    _throttle()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 429:
            raise RuntimeError(
                "楽天APIのレート制限です。リクエスト間隔を空けてください。"
            ) from exc
        raise RuntimeError(f"楽天APIエラー (HTTP {exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"楽天APIに接続できません: {exc.reason}") from exc


def search_with_stats(
    keyword: str,
    application_id: str,
    hits: int = 30,
    timeout: int = 20,
) -> tuple[int, list[Product]]:
    """市場性の評価用。(ヒット総数, 上位商品) を返す。

    ヒット総数はそのキーワードで楽天に何商品あるかで、
    「市場として存在するか」「飽和していないか」の目安になる。
    検索ボリューム（何人が検索したか）ではない点に注意。
    """
    if not application_id:
        raise ValueError("楽天アプリID(application_id)が設定されていません")

    payload = _request({
        "applicationId": application_id,
        "keyword": keyword,
        "hits": max(1, min(hits, 30)),
        "sort": "-reviewCount",
        "format": "json",
        "elements": ",".join([
            "itemName", "itemPrice", "itemUrl", "shopName",
            "reviewAverage", "reviewCount", "postageFlag", "itemCode",
        ]),
    }, timeout)

    products = [_to_product(e.get("Item", {})) for e in payload.get("Items", [])]
    return int(payload.get("count", 0)), products


def _to_product(item: dict) -> Product:
    images = item.get("mediumImageUrls") or []
    image_url = ""
    if images:
        raw = images[0]
        image_url = raw.get("imageUrl", "") if isinstance(raw, dict) else str(raw)
        # 楽天の画像URL末尾の ?_ex=128x128 を外すと大きい画像が取れる
        image_url = image_url.split("?")[0]

    rating = item.get("reviewAverage")
    try:
        rating = float(rating) if rating else None
    except (TypeError, ValueError):
        rating = None
    if rating == 0.0:
        rating = None  # レビュー0件のときAPIは0.0を返すので「なし」扱いにする

    postage_flag = item.get("postageFlag")

    return Product(
        name=item.get("itemName", ""),
        # affiliateUrl はアフィリエイトID未設定だと空になるので itemUrl にフォールバック
        url=item.get("affiliateUrl") or item.get("itemUrl", ""),
        price=item.get("itemPrice"),
        image_url=image_url,
        shop=item.get("shopName", ""),
        rating=rating,
        review_count=item.get("reviewCount") or None,
        # postageFlag: 0 = 送料込み, 1 = 送料別
        free_shipping=(postage_flag == 0) if postage_flag is not None else None,
        provider="rakuten",
        item_code=item.get("itemCode", ""),
    )
