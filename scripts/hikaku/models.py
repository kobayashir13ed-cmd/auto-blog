"""共通の商品データモデル。

楽天・Amazon など提供元が違っても、ここで定義した Product に正規化してから
比較表を組み立てる。新しい提供元を足すときは Product を返す関数を書くだけでよい。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Product:
    """比較表に並べる1商品ぶんのデータ。"""

    # --- API から自動取得される項目 ---
    name: str
    url: str                      # アフィリエイトリンク
    price: int | None = None      # 税込価格（円）
    image_url: str = ""
    shop: str = ""
    rating: float | None = None   # 5点満点
    review_count: int | None = None
    free_shipping: bool | None = None
    provider: str = ""            # "rakuten" / "amazon"
    item_code: str = ""

    # --- 人間があとから手で埋める項目 ---
    # API では取れない / 取れても信用できないスペックはここに入れる。
    # 例: {"重量": "1.2kg", "バッテリー": "10時間"}
    specs: dict[str, str] = field(default_factory=dict)
    # 表の下に出る一言コメント。ここが成約率を左右する一番大事な部分。
    comment: str = ""
    # 「編集部イチオシ」バッジを付ける商品を1つだけ True にする
    recommended: bool = False
    # バッジの文言（"最安値" "高コスパ" など任意）
    badge: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Product":
        # 未知のキーは無視して、将来フィールドが増えても壊れないようにする
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def price_text(self) -> str:
        if self.price is None:
            return "価格変動あり"
        return f"{self.price:,}円"


def spec_columns(products: list[Product]) -> list[str]:
    """全商品の specs に現れるキーを、登場順を保ったまま列挙する。

    商品ごとに specs のキーが違っても、表の列がずれないようにするために使う。
    """
    columns: list[str] = []
    for p in products:
        for key in p.specs:
            if key not in columns:
                columns.append(key)
    return columns
