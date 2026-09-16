"""週次レポートのメール送信。

Search Console の実データから、その週にやるべきことを1通にまとめて送る。

なぜ必要か:
  記事を増やし続けるより、既に表示されている記事を1ページ目に押し上げるほうが
  成果につながりやすい。しかし Search Console を毎週自分で開く習慣はまず続かない。
  だから「今週リライトすべき記事」を向こうから届くようにする。
"""

from __future__ import annotations

import argparse
from html import escape

from . import common, notify
from .kw import gsc

ROW = "padding:7px 10px;border-bottom:1px solid #e2e5e9;font-size:13px;"


def table(title: str, rows: list[gsc.Row], note: str, limit: int = 10) -> str:
    if not rows:
        return (f'<h2 style="font-size:15px;margin:26px 0 8px;">{escape(title)}</h2>'
                '<p style="font-size:13px;color:#57606a;margin:0;">該当なし</p>')

    body = "".join(
        f'<tr><td style="{ROW}">{r.position}位</td>'
        f'<td style="{ROW}">{r.impressions:,}</td>'
        f'<td style="{ROW}">{r.clicks:,}</td>'
        f'<td style="{ROW}word-break:break-all;">{escape(r.key)}</td></tr>'
        for r in rows[:limit]
    )
    head = f"{ROW}background:#f6f8fa;font-weight:bold;color:#57606a;"
    return f"""
<h2 style="font-size:15px;margin:26px 0 8px;">{escape(title)}</h2>
<p style="font-size:13px;color:#57606a;margin:0 0 10px;">{escape(note)}</p>
<table cellpadding="0" cellspacing="0" width="100%"
  style="border:1px solid #e2e5e9;border-radius:6px;border-collapse:separate;">
  <tr><td style="{head}">順位</td><td style="{head}">表示</td>
      <td style="{head}">クリック</td><td style="{head}">クエリ / ページ</td></tr>
  {body}
</table>"""


def build_report(rewrites: list[gsc.Row], fresh: list[gsc.Row], days: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="ja"><body style="margin:0;padding:24px 12px;background:#f4f5f7;">
<table align="center" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:680px;background:#fff;border-radius:10px;">
  <tr><td style="padding:28px;font-family:sans-serif;color:#1a1c1f;">
    <p style="font-size:12px;color:#777;letter-spacing:.08em;margin:0 0 6px;">週次レポート</p>
    <h1 style="font-size:20px;margin:0 0 6px;">今週やるべきこと</h1>
    <p style="font-size:13px;color:#666;margin:0 0 4px;">
      Search Console 直近{days}日間のデータ</p>
    {table("リライト候補", rewrites,
           "8〜30位で止まっている記事です。新しく書くより、ここを直すほうが成果が出ます。"
           "実体験・具体的な数値・不足している見出しを足してください。")}
    {table("新規記事の候補", fresh,
           "表示はされているのに専用記事がないクエリです。"
           "Googleが既にこのサイトと関連づけている話題なので、新規で勝負するより勝ち目があります。")}
    <p style="font-size:12px;color:#888;background:#f6f8fa;padding:12px 14px;
      border-radius:6px;margin:26px 0 0;">
      新規候補は candidates.json に自動で追加されています。<br>
      <code>python -m scripts.research scan</code> で市場性を評価し、
      <code>promote</code> で記事化の対象に登録してください。
    </p>
  </td></tr>
</table>
</body></html>"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="週次レポートを送信します")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--min-impressions", type=int, default=30)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="送信せずHTMLを書き出す")
    parser.add_argument("--out", default="preview-report.html")
    args = parser.parse_args(argv)

    config = common.load_config()

    if args.mock:
        queries, pages = gsc.mock_queries(), gsc.mock_pages()
    else:
        site_url = config.get("search_console_site") or config.get("base_url", "")
        credentials = common.env("GSC_CREDENTIALS")
        queries = gsc.query(site_url, credentials, ["query"], days=args.days)
        pages = gsc.query(site_url, credentials, ["page"], days=args.days)

    rewrites = gsc.rewrite_candidates(pages, args.min_impressions)
    fresh = gsc.new_article_candidates(
        queries, gsc.covered_keywords(), args.min_impressions)

    html = build_report(rewrites, fresh, args.days)

    if args.dry_run:
        from pathlib import Path
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"レポートのプレビューを {args.out} に書き出しました。")
        return

    if not rewrites and not fresh:
        print("報告すべき候補がないため、メールは送信しませんでした。")
        return

    notify.send_html(
        subject=f"[週次レポート] リライト候補{len(rewrites)}件 / 新規候補{len(fresh)}件",
        html=html,
        text=(f"リライト候補: {len(rewrites)}件\n"
              f"新規記事候補: {len(fresh)}件\n"
              "詳細はHTML版をご覧ください。"),
        config=config,
    )


if __name__ == "__main__":
    main()
