"""監視リマインダーのメール送信。

公開直後のサイトでやることは「待つ」と「決まったタイミングで数字を見る」だけ。
ただしそのタイミングは忘れるので、週1でメールを送って思い出させる。

経過日数によって見るべき場所が変わるため、フェーズごとに内容を出し分ける。

    python -m scripts.remind            # 送信
    python -m scripts.remind --dry-run  # 送らずに標準出力で確認
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from . import common, notify

# Search Console のプロパティを直接開くURL
GSC_BASE = "https://search.google.com/search-console"


def gsc_url(site: str, page: str = "") -> str:
    """Search Console の該当ページURLを組み立てる。"""
    resource = quote(site, safe="")
    if page:
        return f"{GSC_BASE}/{page}?resource_id={resource}"
    return f"{GSC_BASE}?resource_id={resource}"


def elapsed_days(config: dict) -> int:
    start = config.get("monitor_start", "")
    if not start:
        return 0
    try:
        began = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (common.now_jst().date() - began).days


def phase(days: int, site: str) -> dict:
    """経過日数から、今週見るべきものを決める。"""
    if days < 7:
        return {
            "name": "待機中",
            "headline": f"公開から{days}日。まだ動きが無くて正常です。",
            "body": (
                "Googleが新しいドメインを見つけてクロールするまでには時間がかかります。"
                "この時期に数字を見ても何も分からないので、今週は何もしなくて大丈夫です。"
            ),
            "actions": [],
            "link": None,
        }
    if days < 30:
        return {
            "name": "インデックス確認",
            "headline": f"公開から{days}日。インデックスされたか確認する時期です。",
            "body": (
                "Search Console の「URL検査」に記事のURLを貼って、状態を確認してください。"
                "「URLはGoogleに登録されています」になっていれば成功です。"
                "「検出 – インデックス未登録」のままなら、まだ順番待ちなので、もう1週待ちます。"
            ),
            "actions": [
                "Search Console を開く",
                "上部の検索窓に記事のURLを貼って Enter",
                "結果が「登録されています」かどうかを見る",
                "未登録なら「インデックス登録をリクエスト」を押しておく",
            ],
            "link": ("URL検査を開く", gsc_url(site, "inspect")),
        }
    if days < 90:
        return {
            "name": "表示回数の確認",
            "headline": f"公開から{days}日。表示回数が出始める時期です。",
            "body": (
                "「検索パフォーマンス」を開いて、表示回数（インプレッション）を見てください。"
                "クリックはまだゼロで構いません。まず表示されているかどうかが先です。"
                "自分でGoogle検索して探すのはやめてください。"
                "検索履歴の影響で実際より上に見えるので、判断を誤ります。"
            ),
            "actions": [
                "検索パフォーマンス → 期間を「過去28日間」に",
                "表示回数の合計を見る",
                "「クエリ」タブで、どの検索語で出ているかを見る",
                "狙ったキーワードと違う語で出ているなら、そちらに寄せる",
            ],
            "link": ("検索パフォーマンスを開く",
                     gsc_url(site, "performance/search-analytics")),
        }
    return {
        "name": "判断",
        "headline": f"公開から{days}日。続けるか決めるタイミングです。",
        "body": (
            "事前に決めた判断基準はこうでした。過去28日間の表示回数で見てください。"
        ),
        "actions": [
            "月100表示以上 … 方向性は合っている。記事数を増やす段階へ",
            "月10〜100表示 … 拾われてはいる。キーワードを見直す",
            "ほぼゼロ … このやり方では厳しい。方針転換か撤退を検討する",
        ],
        "link": ("検索パフォーマンスを開く",
                 gsc_url(site, "performance/search-analytics")),
    }


def build_html(info: dict, days: int, config: dict) -> str:
    actions = ""
    if info["actions"]:
        items = "".join(
            f'<li style="margin:0 0 8px;">{escape(a)}</li>' for a in info["actions"]
        )
        actions = (
            '<ol style="margin:0 0 20px;padding-left:22px;font-family:sans-serif;'
            f'font-size:14px;line-height:1.8;color:#24292f;">{items}</ol>'
        )

    button = ""
    if info["link"]:
        label, url = info["link"]
        button = (
            f'<div style="margin:0 0 20px;"><a href="{escape(url)}" '
            'style="display:inline-block;padding:13px 26px;border-radius:6px;'
            'background:#1a7f37;color:#ffffff;font-family:sans-serif;font-size:15px;'
            f'font-weight:bold;text-decoration:none;">{escape(label)}</a></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ja"><body style="margin:0;padding:24px 12px;background:#f4f5f7;">
<table align="center" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:620px;margin:0 auto;background:#ffffff;border-radius:10px;">
  <tr><td style="padding:28px 28px 26px;">
    <div style="font-family:sans-serif;font-size:12px;color:#777;
      letter-spacing:.08em;padding:0 0 6px;">{escape(config.get('site_title',''))}／週次チェック・{escape(info['name'])}</div>
    <div style="font-family:sans-serif;font-size:20px;font-weight:bold;
      color:#1a1c1f;line-height:1.45;padding:0 0 14px;">{escape(info['headline'])}</div>
    <div style="font-family:sans-serif;font-size:14px;line-height:1.85;
      color:#24292f;padding:0 0 18px;">{escape(info['body'])}</div>
    {actions}
    {button}
    <div style="font-family:sans-serif;font-size:12px;color:#888;
      background:#f6f8fa;padding:12px 14px;border-radius:6px;line-height:1.7;">
      このメールは毎週1回、GitHub Actions から自動送信されています。<br>
      不要になったら .github/workflows/reminder.yml を削除するか、
      GitHubのActions画面で無効化してください。
    </div>
  </td></tr>
</table>
</body></html>"""


def build_text(info: dict) -> str:
    lines = [info["headline"], "", info["body"], ""]
    lines += [f"- {a}" for a in info["actions"]]
    if info["link"]:
        lines += ["", f"{info['link'][0]}: {info['link'][1]}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="監視リマインダーを送信します")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = common.load_config()
    days = elapsed_days(config)
    info = phase(days, config.get("search_console_site", ""))

    subject = f"[{config.get('site_title','サイト')}] {info['headline']}"
    html = build_html(info, days, config)
    text = build_text(info)

    if args.dry_run:
        print(f"件名: {subject}\n")
        print(text)
        return

    notify.send_html(subject=subject, html=html, text=text, config=config)


if __name__ == "__main__":
    main()
