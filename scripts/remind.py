"""監視リマインダーのメール送信。

公開直後のサイトでやることは「待つ」と「決まったタイミングで数字を見る」だけ。
ただしそのタイミングは忘れるので、週1でメールを送って思い出させる。

経過日数によって見るべき場所が変わるため、フェーズごとに内容を出し分ける。

    python -m scripts.remind            # 送信
    python -m scripts.remind --dry-run  # 送らずに標準出力で確認
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from . import common, notify
from .kw import gsc

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


# --------------------------------------------------------------------------
# Search Console の数字
# --------------------------------------------------------------------------

def article_urls(config: dict) -> list[tuple]:
    """公開済みの全記事と、そのURLを新しい順に返す。

    URLの組み立てはサイト生成（build_site）と同じ規則にする。
    ここがずれると、Search Console 側のURLと突き合わせられなくなる。
    """
    from . import build_site          # 重い依存を読み込むので、必要なときだけ
    base = config.get("base_url", "").rstrip("/")
    prefix = config.get("path_prefix", "/")
    return [(post, f"{base}{prefix}{post.slug}/") for post in build_site.load_posts()]


def fetch_numbers(config: dict) -> dict | None:
    """検索パフォーマンスと、全記事のインデックス状況を取る。

    ここで例外を握りつぶしているのは意図的。リマインダーの本体は
    「今週やること」を届けることであって、数字はおまけ。
    認証が未設定でもAPIが落ちていても、メールは必ず届くべきなので、
    数字の取得失敗でメール全体を失敗させない。

    取得は二段に分けている。インデックス状況（URL検査）だけ失敗した場合でも、
    表示回数などの数字は届けたいので、片方の失敗で両方を捨てない。
    """
    credentials = common.env("GSC_CREDENTIALS", required=False)
    if not credentials:
        return None
    site = config.get("search_console_site", "")
    if not site:
        return None

    try:
        data = {
            # 週次メールなので主役は「今週」。ただし今週だけだと数字が小さすぎて
            # 増減が偶然に見えるため、前週と過去28日も並べて文脈を持たせる。
            "this_week": gsc.query(site, credentials, ["query"], days=7),
            "last_week": gsc.query(site, credentials, ["query"], days=7, offset_days=7),
            "queries": gsc.query(site, credentials, ["query"], days=28),
            "pages": gsc.query(site, credentials, ["page"], days=28),
        }
    except Exception as exc:                        # noqa: BLE001 — 上のコメント参照
        print(f"[注意] Search Console から数字を取得できませんでした: {exc}")
        print("       メールは数字なしで送ります。")
        return None

    data["articles"] = article_urls(config)
    data["inspections"] = []
    try:
        data["inspections"] = gsc.inspect_urls(
            site, credentials, [url for _, url in data["articles"]])
        print(f"インデックス状況を{len(data['inspections'])}記事ぶん確認しました。")
    except Exception as exc:                        # noqa: BLE001 — 上のコメント参照
        print(f"[注意] インデックス状況を確認できませんでした: {exc}")
        print("       記事一覧は表示回数だけで送ります。")
        data["inspection_error"] = str(exc).split("\n")[0]
    return data


def totals(rows: list) -> tuple[int, int]:
    return sum(r.impressions for r in rows), sum(r.clicks for r in rows)


def delta(now: int, before: int) -> str:
    """前週との差を短い文字列にする。"""
    if now == before:
        return "先週と同じ"
    diff = now - before
    if before == 0:
        return f"先週0 → 今週{now}"
    pct = diff / before * 100
    sign = "+" if diff > 0 else ""
    return f"先週比 {sign}{diff}（{sign}{pct:.0f}%）"


def new_queries(data: dict) -> list:
    """今週はじめて表示された検索語。サイトが広がった方向が分かる。"""
    before = {r.key for r in data.get("last_week", [])}
    fresh = [r for r in data.get("this_week", []) if r.key not in before]
    return sorted(fresh, key=lambda r: -r.impressions)[:5]


INDEX_COLORS = {
    "登録済み": "#1a7f37",
    "未登録": "#9a6700",
    "エラー": "#cf222e",
}
INDEX_MARKS = {"登録済み": "✅", "未登録": "⏳", "エラー": "❌"}


def short_date(iso: str) -> str:
    """"2026-09-22" を "9/22" にする。"""
    try:
        _, m, d = iso.split("-")
        return f"{int(m)}/{int(d)}"
    except ValueError:
        return iso


def article_rows(data: dict) -> list[dict]:
    """記事ごとに、インデックス状況と表示回数を1行にまとめる。"""
    perf = {r.key: r for r in data.get("pages", [])}
    status = {s.url: s for s in data.get("inspections", [])}
    rows = []
    for post, url in data.get("articles", []):
        st = status.get(url)
        pf = perf.get(url)
        rows.append({
            "title": post.title,
            "url": url,
            "date": short_date(post.published_at or post.created_at),
            "label": st.label if st else "確認できず",
            # 未登録の理由（「検出 - インデックス未登録」など）は、登録済みのときは不要
            "detail": st.coverage if st and st.verdict != "PASS" else "",
            "impressions": pf.impressions if pf else 0,
            "clicks": pf.clicks if pf else 0,
            "position": pf.position if pf else None,
        })
    return rows


def article_summary(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    parts = [f"{label} {counts[label]}" for label in ("登録済み", "未登録", "エラー", "確認できず")
             if counts.get(label)]
    return f"全{len(rows)}記事：" + " ／ ".join(parts)


def article_table_html(data: dict) -> str:
    rows = article_rows(data)
    if not rows:
        return ""
    td = "padding:7px 6px;border-bottom:1px solid #e2e5e9;font-size:12px;vertical-align:top;"
    num = td + "text-align:right;white-space:nowrap;"
    body = ""
    for r in rows:
        title = r["title"] if len(r["title"]) <= 26 else r["title"][:25] + "…"
        color = INDEX_COLORS.get(r["label"], "#57606a")
        detail = (f'<div style="color:#57606a;font-size:11px;margin-top:2px;'
                  f'font-weight:normal;white-space:normal;">'
                  f'{escape(r["detail"])}</div>') if r["detail"] else ""
        pos = f'{r["position"]:.0f}位' if r["position"] else "–"
        body += (
            f'<tr><td style="{td}"><a href="{escape(r["url"])}" '
            f'style="color:#0969da;text-decoration:none;">{escape(title)}</a>'
            f'<div style="color:#57606a;font-size:11px;margin-top:2px;">'
            f'公開 {escape(r["date"])}</div></td>'
            f'<td style="{td}white-space:nowrap;color:{color};font-weight:bold;">'
            f'{escape(r["label"])}{detail}</td>'
            f'<td style="{num}">{r["impressions"]:,}</td>'
            f'<td style="{num}">{r["clicks"]:,}</td>'
            f'<td style="{num}color:#57606a;">{pos}</td></tr>'
        )
    head = ("padding:6px;font-size:11px;color:#57606a;border-bottom:1px solid #d0d7de;"
            "text-align:left;white-space:nowrap;")
    note = ""
    if data.get("inspection_error"):
        note = (f'<p style="font-size:11px;color:#9a6700;margin:6px 0 0;">'
                f'インデックス状況は確認できませんでした：{escape(data["inspection_error"])}</p>')
    return f"""
  <p style="font-size:13px;color:#24292f;margin:18px 0 6px;">
    <strong>全記事の状況</strong>　<span style="color:#57606a;">{escape(article_summary(rows))}</span>
  </p>
  <p style="font-size:11px;color:#57606a;margin:0 0 6px;">
    インデックスは今日時点、表示・クリック・順位は過去28日間
  </p>
  <table cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;">
    <tr><td style="{head}">記事</td><td style="{head}">インデックス</td>
        <td style="{head}text-align:right;">表示</td>
        <td style="{head}text-align:right;">クリック</td>
        <td style="{head}text-align:right;">順位</td></tr>
    {body}
  </table>{note}"""


def article_table_text(data: dict) -> list[str]:
    rows = article_rows(data)
    if not rows:
        return []
    lines = [article_summary(rows) + "（インデックスは今日時点、数字は過去28日）"]
    for r in rows:
        mark = INDEX_MARKS.get(r["label"], "？")
        pos = f'{r["position"]:.0f}位' if r["position"] else "–"
        lines.append(f'{mark} {r["title"]}（{r["date"]}） '
                     f'表示{r["impressions"]} クリック{r["clicks"]} {pos}')
    return lines + [""]


def verdict(impressions: int) -> str:
    """表示回数を、事前に決めた判断基準に照らして一文にする。"""
    if impressions == 0:
        return ("まだ表示されていません。インデックスされてから順位が付くまで"
                "1〜2ヶ月かかるので、この時期はこれで正常です。")
    if impressions < 100:
        return ("検索結果に出始めました。まだ少ないですが、ゼロと1桁では意味が違います。"
                "ここから増えるかを見ます。")
    if impressions < 1000:
        return ("事前に決めた基準（月100表示）を超えています。方向性は合っているので、"
                "記事を増やす段階です。")
    return ("十分な表示回数です。ここからはクリック率（CTR）と順位を見て、"
            "既存記事の改善に力を入れる段階です。")


def week_range() -> str:
    """今週ぶんの集計期間を「9/18〜9/24」の形で返す。

    Search Console は直近2日のデータが未確定なので、そこを終点にする。
    メールに期間を明記しないと「いつの数字か」が分からず、増減を誤読する。
    """
    end = common.now_jst().date() - timedelta(days=2)
    start = end - timedelta(days=6)
    return f"{start.month}/{start.day}〜{end.month}/{end.day}"


def numbers_html(data: dict) -> str:
    imp_now, clk_now = totals(data.get("this_week", []))
    imp_prev, clk_prev = totals(data.get("last_week", []))
    imp_28, clk_28 = totals(data.get("pages", []))

    def stat(value: int, label: str, note: str) -> str:
        return (f'<td style="font-family:sans-serif;padding:0 14px 0 0;">'
                f'<div style="font-size:28px;font-weight:bold;color:#1a1c1f;'
                f'line-height:1.2;">{value:,}</div>'
                f'<div style="font-size:12px;color:#57606a;">{escape(label)}</div>'
                f'<div style="font-size:12px;color:#57606a;margin-top:2px;">'
                f'{escape(note)}</div></td>')

    def rows(items: list, label: str, empty: str) -> str:
        if not items:
            return (f'<p style="font-size:13px;color:#57606a;margin:14px 0 0;">'
                    f'<strong>{escape(label)}</strong><br>{escape(empty)}</p>')
        cells = "".join(
            f'<tr><td style="padding:6px 8px;border-bottom:1px solid #e2e5e9;'
            f'font-size:13px;word-break:break-all;">{escape(str(r.key))}</td>'
            f'<td style="padding:6px 8px;border-bottom:1px solid #e2e5e9;'
            f'font-size:13px;text-align:right;white-space:nowrap;color:#57606a;">'
            f'{r.impressions:,}回 / {r.position:.0f}位</td></tr>'
            for r in items
        )
        return (f'<p style="font-size:13px;color:#57606a;margin:16px 0 6px;">'
                f'<strong>{escape(label)}</strong></p>'
                f'<table cellpadding="0" cellspacing="0" width="100%" '
                f'style="border-collapse:collapse;">{cells}</table>')

    fresh = new_queries(data)
    top_q = sorted(data.get("queries", []), key=lambda r: -r.impressions)[:5]

    return f"""
<div style="border:1px solid #e2e5e9;border-radius:8px;padding:16px;margin:0 0 20px;">
  <div style="font-family:sans-serif;font-size:13px;color:#57606a;margin:0 0 12px;">
    今週のサマリー（{escape(week_range())}）
  </div>
  <table cellpadding="0" cellspacing="0" style="margin:0 0 12px;">
    <tr>
      {stat(imp_now, "表示回数", delta(imp_now, imp_prev))}
      {stat(clk_now, "クリック", delta(clk_now, clk_prev))}
    </tr>
  </table>
  <div style="font-family:sans-serif;font-size:12px;color:#57606a;margin:0 0 12px;">
    過去28日の合計：表示 {imp_28:,}回 ／ クリック {clk_28:,}回
  </div>
  <div style="font-family:sans-serif;font-size:13px;line-height:1.8;color:#24292f;
    background:#f6f8fa;padding:10px 12px;border-radius:6px;">{escape(verdict(imp_28))}</div>
  <div style="font-family:sans-serif;">
    {article_table_html(data)}
    {rows(fresh, "今週はじめて表示された検索語",
          "今週は新しい検索語での表示はありませんでした。")}
    {rows(top_q, "よく表示されている検索語（過去28日）", "まだありません")}
  </div>
</div>"""


def build_html(info: dict, days: int, config: dict,
               data: dict | None = None) -> str:
    numbers = numbers_html(data) if data else ""
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
    {numbers}
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


def build_text(info: dict, data: dict | None = None) -> str:
    lines = [info["headline"], "", info["body"], ""]
    if data:
        imp_now, clk_now = totals(data.get("this_week", []))
        imp_28, _ = totals(data.get("pages", []))
        imp_prev, _ = totals(data.get("last_week", []))
        lines += [
            f"今週（{week_range()}）: 表示{imp_now:,}回 / クリック{clk_now:,}回"
            f"　{delta(imp_now, imp_prev)}",
            f"過去28日の合計: 表示{imp_28:,}回",
            verdict(imp_28), "",
        ]
        lines += article_table_text(data)
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

    data = fetch_numbers(config)
    subject = f"[{config.get('site_title','サイト')}] {info['headline']}"
    html = build_html(info, days, config, data)
    text = build_text(info, data)

    if args.dry_run:
        print(f"件名: {subject}\n")
        print(text)
        return

    notify.send_html(subject=subject, html=html, text=text, config=config)


if __name__ == "__main__":
    main()
