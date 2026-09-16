"""共通処理：設定の読み込み、パス解決、ドラフトの読み書き。"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 日本時間。GitHub Actions は UTC で動くので、日付を出すときは必ずこれを使う。
JST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DRAFTS = CONTENT / "drafts"
POSTS = CONTENT / "posts"
SITE = ROOT / "site"

CONFIG_PATH = ROOT / "config.json"
KEYWORDS_PATH = ROOT / "keywords.json"

# 記事に必ず含める「あなたが書く欄」。ここが未記入のまま公開されるのを防ぐ。
PLACEHOLDER_RE = re.compile(r"\{\{\s*(実体験|注意点|結論)\s*\}\}")


def now_jst() -> datetime:
    return datetime.now(JST)


def today_str() -> str:
    return now_jst().strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# 設定
# --------------------------------------------------------------------------

def load_json(path: Path, required: bool = True) -> dict:
    if not path.exists():
        if required:
            sys.exit(f"[エラー] {path.name} が見つかりません。README の手順を確認してください。")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"[エラー] {path.name} のJSONが壊れています: {exc}")


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def load_config() -> dict:
    return load_json(CONFIG_PATH)


def env(name: str, required: bool = True, default: str = "") -> str:
    """環境変数（GitHub Secrets）を読む。

    APIキーの類はすべてここ経由。設定ファイルには絶対に書かない。
    """
    value = os.environ.get(name, "").strip()
    if not value:
        if required:
            sys.exit(
                f"[エラー] 環境変数 {name} が設定されていません。\n"
                f"  GitHub の Settings > Secrets and variables > Actions で登録してください。"
            )
        return default
    return value


# --------------------------------------------------------------------------
# キーワード管理
# --------------------------------------------------------------------------

def next_keyword() -> tuple[dict, dict] | tuple[None, None]:
    """未着手のキーワードを1件返す。(該当エントリ, 全体データ) を返す。"""
    data = load_json(KEYWORDS_PATH)
    for entry in data.get("keywords", []):
        if entry.get("status", "pending") == "pending":
            return entry, data
    return None, None


def mark_keyword(data: dict, keyword: str, status: str) -> None:
    for entry in data.get("keywords", []):
        if entry.get("keyword") == keyword:
            entry["status"] = status
            entry["updated_at"] = today_str()
    save_json(KEYWORDS_PATH, data)


# --------------------------------------------------------------------------
# ドラフト（front matter 付き Markdown）
# --------------------------------------------------------------------------

@dataclass
class Draft:
    """1記事ぶんのドラフト。front matter は JSON で持つ（YAML依存を避けるため）。"""

    id: str
    title: str
    keyword: str
    slug: str
    body: str                       # Markdown 本文
    category: str = ""              # config.json の categories の slug
    description: str = ""
    created_at: str = field(default_factory=today_str)
    published_at: str = ""
    table_html: str = ""            # サイト用の比較表HTML（本文中の <!--TABLE--> に差し込む）
    email_table_html: str = ""      # 承認メール用（インラインCSS版）

    # ---- 保存形式 ----
    # front matter を <!--META ... --> で囲む。Markdownとして壊れず、パースも単純。
    META_OPEN = "<!--META"
    META_CLOSE = "-->"

    def to_text(self) -> str:
        meta = {
            "id": self.id, "title": self.title, "keyword": self.keyword,
            "slug": self.slug, "category": self.category,
            "description": self.description,
            "created_at": self.created_at, "published_at": self.published_at,
        }
        return (
            f"{self.META_OPEN}\n"
            f"{json.dumps(meta, ensure_ascii=False, indent=2)}\n"
            f"{self.META_CLOSE}\n\n"
            f"{self.body.strip()}\n"
        )

    @classmethod
    def from_text(cls, text: str, table_html: str = "",
                  email_table_html: str = "") -> "Draft":
        if not text.startswith(cls.META_OPEN):
            raise ValueError("ドラフトのメタ情報が見つかりません")
        end = text.index(cls.META_CLOSE)
        meta = json.loads(text[len(cls.META_OPEN):end].strip())
        body = text[end + len(cls.META_CLOSE):].strip()
        return cls(
            id=meta["id"], title=meta["title"], keyword=meta["keyword"],
            slug=meta["slug"], body=body,
            category=meta.get("category", ""),
            description=meta.get("description", ""),
            created_at=meta.get("created_at", ""),
            published_at=meta.get("published_at", ""),
            table_html=table_html,
            email_table_html=email_table_html,
        )

    # ---- プレースホルダ検査 ----
    def placeholders(self) -> list[str]:
        """未記入の {{実体験}} などを列挙する。"""
        return [m.group(1) for m in PLACEHOLDER_RE.finditer(self.body)]

    def path(self, directory: Path) -> Path:
        return directory / f"{self.id}.md"


def read_draft(draft_id: str, directory: Path = DRAFTS) -> Draft:
    path = directory / f"{draft_id}.md"
    if not path.exists():
        sys.exit(f"[エラー] ドラフトが見つかりません: {path}")
    def read_side(suffix: str) -> str:
        side = directory / f"{draft_id}{suffix}"
        return side.read_text(encoding="utf-8") if side.exists() else ""

    return Draft.from_text(
        path.read_text(encoding="utf-8"),
        read_side(".table.html"),
        read_side(".email.html"),
    )


def write_draft(draft: Draft, directory: Path = DRAFTS) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = draft.path(directory)
    path.write_text(draft.to_text(), encoding="utf-8")
    for suffix, content in ((".table.html", draft.table_html),
                            (".email.html", draft.email_table_html)):
        if content:
            (directory / f"{draft.id}{suffix}").write_text(content, encoding="utf-8")
    return path


def slugify(text: str, fallback_seed: str = "") -> str:
    """URL用のスラッグを作る。日本語しかない場合はハッシュで代用する。"""
    import hashlib
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if len(ascii_part) >= 3:
        return ascii_part[:60]
    digest = hashlib.sha1((text + fallback_seed).encode("utf-8")).hexdigest()
    return f"post-{digest[:8]}"
