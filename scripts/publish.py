"""承認された記事の公開 / 却下。

Cloudflare Worker から repository_dispatch で起動された GitHub Actions が呼ぶ。

公開の条件:
  config.json の require_placeholders_filled が true のとき、
  {{実体験}} などの未記入欄が残っていると公開を中止する。
  これは「承認ボタンを読まずに押す」運用を防ぐための歯止めであり、
  中身のない記事を量産してサイト全体の評価を落とすリスクを避けるためのもの。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import build_site, common

REJECTED = common.CONTENT / "rejected"


def move_files(draft_id: str, src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for suffix in (".md", ".table.html"):
        source = src / f"{draft_id}{suffix}"
        if source.exists():
            shutil.move(str(source), str(dst / f"{draft_id}{suffix}"))


def approve(draft_id: str, config: dict) -> None:
    draft = common.read_draft(draft_id)

    missing = draft.placeholders()
    if missing and config.get("require_placeholders_filled", True):
        repo = common.env("GITHUB_REPOSITORY", required=False)
        branch = config.get("branch", "main")
        edit = (f"https://github.com/{repo}/edit/{branch}/content/drafts/{draft_id}.md"
                if repo else "（リポジトリのドラフトファイル）")
        sys.exit(
            f"[公開を中止しました] 未記入の欄が{len(missing)}箇所あります: {missing}\n\n"
            f"  この欄はあなたの実体験を書く場所です。ここが空のまま公開すると、\n"
            f"  他サイトと差がない記事になり、検索評価を落とすおそれがあります。\n\n"
            f"  編集する: {edit}\n"
            f"  編集後、承認メールのボタンをもう一度押してください。\n\n"
            f"  （この歯止めを外すには config.json の\n"
            f"    require_placeholders_filled を false にします）"
        )

    draft.published_at = common.today_str()
    # 本文はそのまま、メタ情報だけ更新して posts/ へ書き出す
    common.write_draft(draft, common.POSTS)
    for suffix in (".md", ".table.html"):
        stale = common.DRAFTS / f"{draft_id}{suffix}"
        if stale.exists():
            stale.unlink()

    keywords = common.load_json(common.KEYWORDS_PATH, required=False)
    if keywords:
        common.mark_keyword(keywords, draft.keyword, "published")

    print(f"公開しました: {draft.title}")
    build_site.main()


def reject(draft_id: str, config: dict) -> None:
    draft = common.read_draft(draft_id)
    move_files(draft_id, common.DRAFTS, REJECTED)

    keywords = common.load_json(common.KEYWORDS_PATH, required=False)
    if keywords:
        # 却下したキーワードは pending に戻し、次回また書き直せるようにする
        common.mark_keyword(keywords, draft.keyword, "pending")

    print(f"却下しました: {draft.title}")
    print(f"  ドラフトは {REJECTED.relative_to(common.ROOT)}/ に保管されています。")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ドラフトを公開または却下します")
    parser.add_argument("--draft-id", required=True)
    parser.add_argument("--action", choices=["approve", "reject"], required=True)
    args = parser.parse_args(argv)

    config = common.load_config()
    if args.action == "approve":
        approve(args.draft_id, config)
    else:
        reject(args.draft_id, config)


if __name__ == "__main__":
    main()
