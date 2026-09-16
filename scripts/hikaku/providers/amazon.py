"""Amazon Product Advertising API v5 (PA-API) クライアント。

【重要】PA-APIはアソシエイト審査を通過していないと使えない。
審査通過には申請から180日以内に3件の適格な売上が必要なので、
サイト立ち上げ直後は楽天だけで運用し、売上が立ってからここを有効化するのが現実的。

必要な認証情報（アソシエイト管理画面の「ツール > Product Advertising API」で発行）:
    access_key / secret_key / partner_tag (例: yourname-22)

外部ライブラリを使わず、AWS SigV4 署名を標準ライブラリだけで実装している。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from ..models import Product

HOST = "webservices.amazon.co.jp"
REGION = "us-west-2"          # 日本のマーケットプレイスでも署名リージョンは us-west-2
SERVICE = "ProductAdvertisingAPI"
MARKETPLACE = "www.amazon.co.jp"
PATH = "/paapi5/searchitems"
TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"

RESOURCES = [
    "ItemInfo.Title",
    "ItemInfo.Features",
    "ItemInfo.ByLineInfo",
    "Offers.Listings.Price",
    "Offers.Listings.DeliveryInfo.IsFreeShippingEligible",
    "Images.Primary.Large",
]


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str) -> bytes:
    k_date = _sign(f"AWS4{secret_key}".encode("utf-8"), date_stamp)
    k_region = _sign(k_date, REGION)
    k_service = _sign(k_region, SERVICE)
    return _sign(k_service, "aws4_request")


def _build_headers(payload: str, access_key: str, secret_key: str) -> dict[str, str]:
    """AWS Signature Version 4 の署名ヘッダーを組み立てる。"""
    now = _dt.datetime.now(_dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    # --- 1. 正規リクエスト ---
    # 署名対象ヘッダーはアルファベット順・小文字でなければならない
    canonical_headers = (
        "content-encoding:amz-1.0\n"
        f"host:{HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{TARGET}\n"
    )
    signed_headers = "content-encoding;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        "POST", PATH, "", canonical_headers, signed_headers, payload_hash,
    ])

    # --- 2. 署名文字列 ---
    scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    # --- 3. 署名 ---
    signature = hmac.new(
        _signing_key(secret_key, date_stamp),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Content-Encoding": "amz-1.0",
        "Content-Type": "application/json; charset=utf-8",
        "Host": HOST,
        "X-Amz-Date": amz_date,
        "X-Amz-Target": TARGET,
        "Authorization": authorization,
    }


def search(
    keyword: str,
    access_key: str,
    secret_key: str,
    partner_tag: str,
    hits: int = 5,
    timeout: int = 20,
) -> list[Product]:
    """キーワードで商品を検索して Product のリストを返す。"""
    if not (access_key and secret_key and partner_tag):
        raise ValueError("Amazon PA-APIの認証情報が設定されていません")

    payload = json.dumps({
        "Keywords": keyword,
        "PartnerTag": partner_tag,
        "PartnerType": "Associates",
        "Marketplace": MARKETPLACE,
        "ItemCount": max(1, min(hits, 10)),  # PA-APIの上限は10件
        "Resources": RESOURCES,
    }, ensure_ascii=False)

    headers = _build_headers(payload, access_key, secret_key)
    request = urllib.request.Request(
        f"https://{HOST}{PATH}",
        data=payload.encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        if exc.code == 429:
            raise RuntimeError(
                "Amazon PA-APIのレート制限です。売上実績が少ないうちは"
                "リクエスト上限が非常に低い点に注意してください。"
            ) from exc
        raise RuntimeError(f"Amazon PA-APIエラー (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Amazon PA-APIに接続できません: {exc.reason}") from exc

    items = (body.get("SearchResult") or {}).get("Items") or []
    return [_to_product(item) for item in items]


def _to_product(item: dict) -> Product:
    info = item.get("ItemInfo") or {}
    title = ((info.get("Title") or {}).get("DisplayValue")) or ""

    listing = {}
    listings = (item.get("Offers") or {}).get("Listings") or []
    if listings:
        listing = listings[0]

    price_info = listing.get("Price") or {}
    price = price_info.get("Amount")
    if price is not None:
        price = int(price)

    free_shipping = (
        (listing.get("DeliveryInfo") or {}).get("IsFreeShippingEligible")
    )

    brand = ((info.get("ByLineInfo") or {}).get("Brand") or {}).get("DisplayValue", "")

    # Features（箇条書き仕様）を specs の下地として最大3件だけ取り込む。
    # 精度は高くないので、最終的には人間が products.json を手直しする前提。
    features = (info.get("Features") or {}).get("DisplayValues") or []
    specs = {f"特徴{i + 1}": text for i, text in enumerate(features[:3])}

    return Product(
        name=title,
        url=item.get("DetailPageURL", ""),   # PartnerTag付きのリンクが返る
        price=price,
        image_url=((item.get("Images") or {}).get("Primary") or {}).get("Large", {}).get("URL", ""),
        shop=brand or "Amazon",
        rating=None,          # PA-API v5 では星評価は取得できない
        review_count=None,
        free_shipping=free_shipping,
        provider="amazon",
        item_code=item.get("ASIN", ""),
        specs=specs,
    )
