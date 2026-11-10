"""検索の表示回数が目標を超えたら、一度だけメールで知らせる。

Search Console の直近28日の表示回数を毎朝確かめ、目標（初期値は月100回）を
初めて超えた日に運営者へメールを送る。送った目標は content/milestones.json に
記録し、同じ知らせを二度送らない。

    python -m scripts.milestone              # 確かめて、超えていれば知らせる
    python -m scripts.milestone --dry-run    # 数字を表示するだけ（メールも記録もしない）
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import quote

from . import common

STATE_PATH = common.CONTENT / "milestones.json"
DAYS = 28
# 知らせる目標。上から順に、まだ知らせていないものだけを見る
TARGETS = [100, 300, 1000]


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"notified": {}}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="表示回数の目標達成を知らせる")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from .kw import gsc
    config = common.load_config()
    credentials = common.env("GSC_CREDENTIALS", required=False)
    site = config.get("search_console_site", "")
    if not credentials or not site:
        print("GSC_CREDENTIALS か search_console_site が未設定のため、確認しません。")
        return

    try:
        pages = gsc.query(site, credentials, ["page"], days=DAYS)
    except Exception as exc:                        # noqa: BLE001
        # 確認できない日があっても、翌日また確かめればよい
        print(f"[注意] Search Console から数字を取得できませんでした: {exc}")
        return
    impressions = sum(r.impressions for r in pages)
    clicks = sum(r.clicks for r in pages)
    print(f"直近{DAYS}日：表示 {impressions}回 / クリック {clicks}回")

    state = load_state()
    notified = state.setdefault("notified", {})
    reached = [t for t in TARGETS if impressions >= t and str(t) not in notified]
    if not reached:
        print("新しく達成した目標はありません。")
        return
    target = max(reached)
    if args.dry_run:
        print(f"[確認のみ] 目標 {target}回 を達成しています（メールは送りません）。")
        return

    from . import notify
    top = sorted(pages, key=lambda r: -r.impressions)[:5]
    rows = "".join(
        f"<li style=\"margin:0 0 4px;\">{notify.escape(r.key.replace(config.get('base_url', ''), '') or '/')}"
        f"：表示{r.impressions}回・クリック{r.clicks}回・{r.position}位</li>" for r in top)
    site_title = config.get("site_title", "")
    html = notify.simple_email(
        f"{site_title}／目標達成", f"検索の表示回数が月{target}回を超えました",
        [f"直近{DAYS}日の表示回数が <strong>{impressions}回</strong>（クリック {clicks}回）になり、"
         f"目標の月{target}回を超えました。",
         "表示の多い記事：",
         f'<ul style="margin:0;padding-left:20px;font-size:14px;color:#57606a;">{rows}</ul>',
         "次の段階（アクセス解析の導入・アドセンスの申請準備）に進む目安です。"],
        [("Search Console を開く",
          "https://search.google.com/search-console/performance/search-analytics"
          f"?resource_id={quote(site, safe='')}", "#0f5e5b")],
        "このお知らせは目標ごとに一度だけ届きます。")
    notify.send_html(subject=f"[{site_title}] 検索の表示回数が月{target}回を超えました",
                     html=html,
                     text=f"直近{DAYS}日の表示回数が{impressions}回になり、月{target}回を超えました。\n",
                     config=config)
    for t in reached:                                # 小さい目標はまとめて達成扱い
        notified[str(t)] = {"date": common.today_str(), "impressions": impressions}
    common.save_json(STATE_PATH, state)
    print(f"目標 {target}回 の達成を知らせました。")


if __name__ == "__main__":
    main(sys.argv[1:])
