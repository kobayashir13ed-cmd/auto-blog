"""Google Search Console 連携。

**これが唯一、実際の検索需要を無料かつ規約に沿って取得できる方法です。**
自分のサイトのデータなので、推定ではなく実測値が返ってきます。

取得できるもの:
  - クエリごとの表示回数(impressions)・クリック数・平均掲載順位
  - ページごとの同上

そこから2つを抽出します:
  1. リライト候補 … 8〜30位に留まっている既存記事。
     ここを1ページ目に押し上げるのが、新記事を書くより圧倒的に費用対効果が高い。
  2. 新規記事候補 … 表示はされているのに専用記事がないクエリ。
     Googleが「このサイトはこの話題に関連する」と既に判断している証拠であり、
     新規で勝負するより勝ち目がある。

【前提】サイト公開後、データが溜まるまで数週間かかります。
立ち上げ直後は market.py（楽天ベース）で候補を出し、
データが溜まったらこちらに主軸を移すのが正しい順序です。

【準備】
  1. Google Cloud でサービスアカウントを作成し、JSONキーをダウンロード
  2. Search Console API を有効化
  3. Search Console の「設定 > ユーザーと権限」で、
     サービスアカウントのメールアドレス(...iam.gserviceaccount.com)を
     「制限付き」権限で追加する  ← これを忘れると 403 になります
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import timedelta

from .. import common

API_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


@dataclass
class Row:
    key: str
    clicks: int
    impressions: int
    ctr: float
    position: float

    def to_dict(self) -> dict:
        return asdict(self)


def _access_token(credentials_json: str) -> str:
    """サービスアカウントのJSONからアクセストークンを取得する。"""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        raise RuntimeError(
            "google-auth がインストールされていません。\n"
            "  pip install -r requirements.txt を実行してください。"
        ) from None

    try:
        info = json.loads(credentials_json)
    except json.JSONDecodeError:
        raise RuntimeError(
            "GSC_CREDENTIALS の中身がJSONとして読めません。\n"
            "  サービスアカウントのJSONキーファイルの中身を、\n"
            "  そのまま丸ごとGitHub Secretsに貼り付けてください。"
        ) from None

    creds = service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    creds.refresh(Request())
    return creds.token


def query(
    site_url: str,
    credentials_json: str,
    dimensions: list[str],
    days: int = 28,
    row_limit: int = 1000,
    offset_days: int = 0,
) -> list[Row]:
    """Search Console に検索パフォーマンスを問い合わせる。

    offset_days で期間をさかのぼれる。前週との比較に使う。
      offset_days=0, days=7 … 直近7日間
      offset_days=7, days=7 … その前の7日間
    """
    token = _access_token(credentials_json)

    # 直近2日はデータが未確定なので、常にそこを終点にする
    # Search Console の期間は開始日・終了日の両方を含むので、7日分なら -6 する。
    # ここを -7 にすると8日分になり、前週と1日重なって比較が狂う。
    end = common.now_jst().date() - timedelta(days=2 + offset_days)
    start = end - timedelta(days=days - 1)

    body = json.dumps({
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": dimensions,
        "rowLimit": row_limit,
    }).encode("utf-8")

    encoded_site = urllib.parse.quote(site_url, safe="")
    request = urllib.request.Request(
        f"{API_BASE}/{encoded_site}/searchAnalytics/query",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        if exc.code == 403:
            raise RuntimeError(
                "Search Console にアクセスできません（403）。\n"
                "  サービスアカウントのメールアドレスを、Search Console の\n"
                "  「設定 > ユーザーと権限」で追加したか確認してください。"
            ) from exc
        if exc.code == 404:
            raise RuntimeError(
                f"サイト '{site_url}' が見つかりません（404）。\n"
                "  Search Console に登録したプロパティと完全に同じ文字列か確認してください。\n"
                "  URLプレフィックス型なら末尾のスラッシュまで一致させる必要があります。\n"
                "  ドメインプロパティなら 'sc-domain:example.com' の形式です。"
            ) from exc
        raise RuntimeError(f"Search Console APIエラー (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Search Console に接続できません: {exc.reason}") from exc

    return [
        Row(
            key=r["keys"][0],
            clicks=int(r.get("clicks", 0)),
            impressions=int(r.get("impressions", 0)),
            ctr=round(float(r.get("ctr", 0)) * 100, 2),
            position=round(float(r.get("position", 0)), 1),
        )
        for r in payload.get("rows", [])
    ]


# --------------------------------------------------------------------------
# 分析
# --------------------------------------------------------------------------

def rewrite_candidates(pages: list[Row], min_impressions: int = 50) -> list[Row]:
    """リライトすると効果が大きいページを抽出する。

    8〜30位は「あと少しで1ページ目」の位置。
    ここは表示されているのにクリックされていないため、伸びしろが最も大きい。
    1〜7位は既に取れており、31位以下は改善に時間がかかる。
    """
    found = [
        r for r in pages
        if 8 <= r.position <= 30 and r.impressions >= min_impressions
    ]
    # 表示回数が多く、順位が1ページ目に近いものから
    return sorted(found, key=lambda r: (-r.impressions, r.position))


def new_article_candidates(
    queries: list[Row],
    covered: set[str],
    min_impressions: int = 30,
) -> list[Row]:
    """専用記事がないのに表示されているクエリを抽出する。

    covered には既存記事のキーワードを入れる。
    """
    found = []
    for row in queries:
        if row.impressions < min_impressions:
            continue
        # 既存のキーワードに含まれる語が入っていれば「対応済み」とみなす
        if any(c and c in row.key for c in covered):
            continue
        found.append(row)
    return sorted(found, key=lambda r: -r.impressions)


def covered_keywords() -> set[str]:
    """すでに記事化済み・予定済みのキーワードを集める。"""
    covered: set[str] = set()
    data = common.load_json(common.KEYWORDS_PATH, required=False)
    for entry in data.get("keywords", []):
        if entry.get("keyword"):
            covered.add(entry["keyword"])
    for path in common.POSTS.glob("*.md"):
        try:
            draft = common.Draft.from_text(path.read_text(encoding="utf-8"))
            covered.add(draft.keyword)
        except (ValueError, KeyError):
            continue
    return covered


# --------------------------------------------------------------------------
# モック（サイト公開前でも動きを確認できるように）
# --------------------------------------------------------------------------

def mock_queries() -> list[Row]:
    return [
        Row("モニターアーム 耐荷重", 2, 480, 0.42, 14.2),
        Row("ゲーミングマウス 軽量 おすすめ", 8, 350, 2.29, 9.4),
        Row("モニターアーム クランプ 挟めない", 0, 210, 0.0, 23.8),
        Row("マウス 静音 疲れない", 1, 145, 0.69, 18.1),
        Row("デスク 配線 まとめる", 0, 96, 0.0, 34.5),
        Row("ゲーミングマウス 軽量", 12, 620, 1.94, 6.2),
    ]


def mock_pages() -> list[Row]:
    return [
        Row("https://example.com/lightweight-gaming-mouse/", 20, 970, 2.06, 8.9),
        Row("https://example.com/monitor-arm/", 3, 690, 0.43, 17.4),
        Row("https://example.com/desk-cable/", 0, 88, 0.0, 41.2),
    ]
