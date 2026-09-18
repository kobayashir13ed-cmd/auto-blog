"""承認メールの送信。

記事の全文プレビューと、承認 / 却下 / 編集 の3つのリンクを載せたHTMLメールを送る。

メールHTMLの制約:
  - <style> タグは多くのメールクライアントで削除されるため、すべてインラインstyleで書く
  - flexbox / grid は使えないため、レイアウトは <table> で組む
  - 画像は表示されない前提（既定でブロックされる）
"""

from __future__ import annotations

import argparse
import smtplib
import sys
from email.message import EmailMessage
from html import escape
from urllib.parse import quote

import markdown as md

from . import common, tokens

BTN = ("display:inline-block;padding:14px 28px;border-radius:6px;"
       "font-size:16px;font-weight:bold;text-decoration:none;font-family:sans-serif;")


def render_body(draft: common.Draft) -> str:
    """Markdown本文をHTMLにして、比較表とプレースホルダを差し込む。"""
    html = md.markdown(
        draft.body,
        extensions=["extra", "sane_lists"],
    )

    # 比較表は読者のブラウザが取得するため、メールの時点では中身が存在しない。
    # 代わりに「何が表示されるか」を確認できる楽天の検索リンクを置く。
    search_url = ("https://search.rakuten.co.jp/search/mall/"
                  + quote(draft.keyword) + "/?s=4")
    html = html.replace("<!--TABLE-->", f"""
<div style="padding:14px 16px;background:#f6f8fa;border:1px dashed #c3c9d0;
  border-radius:8px;font-size:13px;color:#57606a;">
  <strong>ここに比較表が入ります</strong><br>
  商品一覧は読者がページを開いた時点で楽天市場から自動取得されるため、
  この時点では中身がありません（価格が常に最新になります）。<br>
  <a href="{escape(search_url)}" style="color:#0969da;">
    どんな商品が並ぶかを楽天市場で確認する</a>
</div>""")

    # 未記入欄を赤く目立たせる
    for name in ("実体験", "注意点", "結論"):
        html = html.replace(
            "{{" + name + "}}",
            f'<p style="padding:12px 16px;background:#fdeef0;border-left:4px solid #c8102e;'
            f'color:#c8102e;font-weight:bold;margin:0;">未記入：{name}（ここはあなたが書く欄です）</p>',
        )
    return html


def build_email_html(draft: common.Draft, urls: dict[str, str],
                     edit_url: str, missing: list[str]) -> str:
    warning = ""
    if missing:
        items = "、".join(missing)
        warning = f"""
      <tr><td style="padding:0 0 20px;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff4e5;
          border:1px solid #ffb74d;border-radius:6px;">
          <tr><td style="padding:16px;font-family:sans-serif;font-size:14px;color:#7a4f01;">
            <strong>未記入の欄が{len(missing)}箇所あります（{items}）</strong><br>
            この欄はあなたの実体験を書く場所です。AIには書けません。<br>
            <a href="{escape(edit_url)}" style="color:#7a4f01;">GitHubで編集する</a>
            を押して埋めてから承認してください。
          </td></tr>
        </table>
      </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="ja"><body style="margin:0;padding:24px 12px;background:#f4f5f7;">
<table align="center" width="100%" cellpadding="0" cellspacing="0"
  style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:10px;">
  <tr><td style="padding:28px 28px 0;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="font-family:sans-serif;font-size:12px;color:#777;
        letter-spacing:.08em;padding:0 0 6px;">記事の承認依頼</td></tr>
      <tr><td style="font-family:sans-serif;font-size:21px;font-weight:bold;
        color:#1a1c1f;line-height:1.4;padding:0 0 4px;">{escape(draft.title)}</td></tr>
      <tr><td style="font-family:sans-serif;font-size:13px;color:#666;
        padding:0 0 20px;">キーワード：{escape(draft.keyword)}　/　{escape(draft.id)}</td></tr>
      {warning}
      <tr><td align="center" style="padding:0 0 12px;">
        <a href="{escape(urls['approve'])}"
           style="{BTN}background:#1a7f37;color:#ffffff;">内容を確認して公開する</a>
      </td></tr>
      <tr><td align="center" style="padding:0 0 20px;font-family:sans-serif;font-size:13px;">
        <a href="{escape(edit_url)}" style="color:#0969da;">GitHubで編集する</a>
        　|
        <a href="{escape(urls['reject'])}" style="color:#999;">この記事を却下する</a>
      </td></tr>
      <tr><td style="font-family:sans-serif;font-size:12px;color:#888;
        background:#f6f8fa;padding:12px 14px;border-radius:6px;">
        公開ボタンを押すと確認画面が開きます。そこでもう一度押すまで公開されません。
        このリンクは14日で失効します。
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="padding:24px 28px 32px;">
    <div style="border-top:1px solid #e2e5e9;padding-top:20px;font-family:sans-serif;
      font-size:15px;line-height:1.8;color:#24292f;">
      {render_body(draft)}
    </div>
  </td></tr>
</table>
</body></html>"""


def send_html(subject: str, html: str, text: str, config: dict) -> None:
    """HTMLメールを1通送る。承認メールと週次レポートで共用する。"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = common.env("SMTP_FROM")
    message["To"] = common.env("NOTIFY_TO")
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    host = config.get("smtp", {}).get("host", "smtp.gmail.com")
    port = int(config.get("smtp", {}).get("port", 587))

    try:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.starttls()
            server.login(common.env("SMTP_USER"), common.env("SMTP_PASSWORD"))
            server.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        sys.exit(
            "[エラー] SMTP認証に失敗しました。\n"
            "  Gmailの場合、通常のパスワードでは接続できません。\n"
            "  2段階認証を有効にしたうえで「アプリパスワード」を発行し、\n"
            "  それを SMTP_PASSWORD に設定してください。\n"
            f"  詳細: {exc}"
        )
    except OSError as exc:
        sys.exit(f"[エラー] メール送信に失敗しました: {exc}")

    print(f"メールを送信しました → {message['To']}")


def send(draft: common.Draft, config: dict) -> None:
    secret = common.env("APPROVAL_SECRET")
    worker_base = common.env("WORKER_BASE_URL")
    urls = tokens.approval_urls(worker_base, secret, draft.id)

    repo = common.env("GITHUB_REPOSITORY", required=False) or config.get("repository", "")
    branch = config.get("branch", "main")
    edit_url = (
        f"https://github.com/{repo}/edit/{branch}/content/drafts/{draft.id}.md"
        if repo else worker_base
    )

    missing = draft.placeholders()

    send_html(
        subject=f"[承認依頼] {draft.title}",
        html=build_email_html(draft, urls, edit_url, missing),
        text=(
            f"記事の承認依頼です。\n\n"
            f"タイトル: {draft.title}\n"
            f"未記入欄: {len(missing)}箇所\n\n"
            f"公開する: {urls['approve']}\n"
            f"編集する: {edit_url}\n"
            f"却下する: {urls['reject']}\n"
        ),
        config=config,
    )
    if missing:
        print(f"  未記入欄が{len(missing)}箇所あることを本文に明記しました。")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="承認メールを送信します")
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="送信せずHTMLをファイルに書き出す（確認用）")
    parser.add_argument("--out", default="preview-email.html")
    args = parser.parse_args(argv)

    config = common.load_config()
    draft = common.read_draft(args.draft_id)

    if args.dry_run:
        urls = {"approve": "https://example.workers.dev/approve?id=...&t=...",
                "reject": "https://example.workers.dev/reject?id=...&t=..."}
        html = build_email_html(
            draft, urls, "https://github.com/you/repo/edit/main/...",
            draft.placeholders(),
        )
        from pathlib import Path
        Path(args.out).write_text(html, encoding="utf-8")
        print(f"メールのプレビューを {args.out} に書き出しました。")
        return

    send(draft, config)


if __name__ == "__main__":
    main()
