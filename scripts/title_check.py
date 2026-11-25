"""タイトルを変えた記事の効果を、変更から4週間後に自動で測ってメールで知らせる。

content/title_tests.json に記録した「変更前28日の成績」と、変更後28日の成績を比べる。
比べる基準として、タイトルを変えていない記事の成績の変化も一緒に出す
（季節やサイト全体の伸びによる変化と、タイトルの効果を見分けるため）。

毎週の分析（insights.yml）と一緒に動き、4週間たった変更だけを1回だけ知らせる。

    python -m scripts.title_check            # 4週間たっていれば測って知らせる
    python -m scripts.title_check --dry-run  # メールを送らず結果だけ表示する
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

from . import common

PATH = common.CONTENT / "title_tests.json"
DAYS = 28


def _ctr(clicks: int, impressions: int) -> float:
    return round(clicks / impressions * 100, 1) if impressions else 0.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="タイトル変更の効果を測る")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("タイトル変更の記録がありません。")
        return
    tests = [t for t in data.get("tests") or [] if not t.get("excluded")]
    today = common.now_jst().date()
    latest = today - timedelta(days=2)              # Search Console の確定データの最終日
    due = [t for t in tests if not t.get("after")
           and date.fromisoformat(t["changed_at"]) + timedelta(days=DAYS) <= latest]
    if not due:
        waiting = [t["changed_at"] for t in tests if not t.get("after")]
        print(f"まだ測る時期ではありません（変更日: {', '.join(sorted(set(waiting))) or 'なし'}）。")
        return

    from .kw import gsc
    config = common.load_config()
    credentials = common.env("GSC_CREDENTIALS", required=False)
    site = config.get("search_console_site", "")
    if not credentials or not site:
        print("GSC_CREDENTIALS か search_console_site が未設定のため、測れません。")
        return
    base = config.get("base_url", "").rstrip("/") + config.get("path_prefix", "/")

    # 変更日ごとにまとめて測る（同じ日に変えた記事は同じ期間で比べる）
    rows_html, lines = [], []
    for changed in sorted({t["changed_at"] for t in due}):
        group = [t for t in due if t["changed_at"] == changed]
        end = date.fromisoformat(changed) + timedelta(days=DAYS)
        offset = (latest - end).days
        before_end = date.fromisoformat(changed) - timedelta(days=2)
        before_offset = (latest - before_end).days
        try:
            after = {r.key: r for r in gsc.query(site, credentials, ["page"], days=DAYS, offset_days=offset)}
            before = {r.key: r for r in gsc.query(site, credentials, ["page"], days=DAYS,
                                                  offset_days=before_offset)}
        except Exception as exc:                    # noqa: BLE001
            print(f"[注意] Search Console から数字を取得できませんでした: {exc}")
            return

        changed_urls = {f"{base}{t['slug']}/" for t in group}

        def totals(rows: dict, urls) -> tuple[int, int]:
            sel = [r for k, r in rows.items() if k in urls]
            return sum(r.impressions for r in sel), sum(r.clicks for r in sel)

        others = (set(after) | set(before)) - changed_urls
        oi_b, oc_b = totals(before, others)
        oi_a, oc_a = totals(after, others)
        ci_b, cc_b = totals(before, changed_urls)
        ci_a, cc_a = totals(after, changed_urls)
        for t in group:
            url = f"{base}{t['slug']}/"
            a = after.get(url)
            t["after"] = {"period": f"{(end - timedelta(days=DAYS - 1)).isoformat()}〜{end.isoformat()}（28日）",
                          "impressions": a.impressions if a else 0, "clicks": a.clicks if a else 0,
                          "position": a.position if a else None}
            b = t["before"]
            line = (f"{t['new_title']}：クリック率 {_ctr(b['clicks'], b['impressions'])}% → "
                    f"{_ctr(t['after']['clicks'], t['after']['impressions'])}%"
                    f"（表示 {b['impressions']}→{t['after']['impressions']}、"
                    f"クリック {b['clicks']}→{t['after']['clicks']}）")
            lines.append(line)
            rows_html.append(f"<li style=\"margin:0 0 6px;\">{notify_escape(line)}</li>")
        summary = (f"タイトルを変えた{len(group)}記事：クリック率 {_ctr(cc_b, ci_b)}% → {_ctr(cc_a, ci_a)}%"
                   f"（表示 {ci_b}→{ci_a}、クリック {cc_b}→{cc_a}）／"
                   f"変えていない記事：クリック率 {_ctr(oc_b, oi_b)}% → {_ctr(oc_a, oi_a)}%"
                   f"（表示 {oi_b}→{oi_a}、クリック {oc_b}→{oc_a}）")
        lines.insert(0, summary)
        rows_html.insert(0, f"<li style=\"margin:0 0 10px;\"><strong>{notify_escape(summary)}</strong></li>")
        better = _ctr(cc_a, ci_a) - _ctr(cc_b, ci_b) > _ctr(oc_a, oi_a) - _ctr(oc_b, oi_b)
        verdict = ("タイトルを変えた記事のほうが、変えていない記事よりクリック率が伸びました。"
                   "残りの記事も同じ方針でタイトルを変えるのがおすすめです。" if better else
                   "タイトルを変えた記事のクリック率の伸びは、変えていない記事を上回りませんでした。"
                   "残りの記事は今のままにして、別の改善を考えるのがおすすめです。")
        if ci_a < 100:
            verdict += "（ただし表示回数が100回未満なので、偶然の差である可能性もあります）"
        lines.append(verdict)
        rows_html.append(f"<li style=\"margin:10px 0 0;\">{notify_escape(verdict)}</li>")

    print("\n".join(lines))
    if args.dry_run:
        return
    from . import notify
    site_title = config.get("site_title", "")
    html = notify.simple_email(
        f"{site_title}／タイトル変更の結果", "タイトルを変えた記事の4週間後の結果",
        ["タイトルと説明文を変えた記事について、変更前と変更後の28日間を比べました。",
         f'<ul style="margin:0;padding-left:20px;font-size:14px;color:#24292f;">{"".join(rows_html)}</ul>',
         "続け方は、このメールをClaudeに見せて相談してください。"],
        [], "このお知らせは、タイトルを変えた日ごとに一度だけ届きます。")
    notify.send_html(subject=f"[{site_title}] タイトル変更の結果（4週間後）", html=html,
                     text="\n".join(lines) + "\n", config=config)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("結果をメールで知らせ、記録を更新しました。")


def notify_escape(text: str) -> str:
    from html import escape
    return escape(text)


if __name__ == "__main__":
    main(sys.argv[1:])
