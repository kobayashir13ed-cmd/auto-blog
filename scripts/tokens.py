"""承認リンク用のHMAC署名トークン。

メールに埋め込むURLには「どの記事を」「承認するのか却下するのか」しか入れない。
GitHubのアクセストークンのような秘密情報はメールに載せず、Cloudflare Worker側に置く。

トークンは次を保証する:
  - 第三者がURLを推測して勝手に公開できない（署名鍵を知らないと作れない）
  - 古いメールのリンクが永久に有効ではない（有効期限を署名対象に含める）

同じ実装を worker/index.js 側にも書いてあるので、片方を変えたら両方直すこと。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def make_token(secret: str, draft_id: str, action: str, ttl_days: int = 14) -> str:
    """`<有効期限>.<署名>` 形式のトークンを作る。"""
    expires = int(time.time()) + ttl_days * 86400
    message = f"{draft_id}:{action}:{expires}"
    signature = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).digest()
    return f"{expires}.{_b64url(signature)}"


def verify_token(secret: str, draft_id: str, action: str, token: str) -> tuple[bool, str]:
    """検証結果と、失敗理由（日本語）を返す。"""
    try:
        expires_str, signature = token.split(".", 1)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        return False, "トークンの形式が不正です"

    if expires < time.time():
        return False, "この承認リンクは期限切れです"

    message = f"{draft_id}:{action}:{expires}"
    expected = _b64url(
        hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    )
    # タイミング攻撃を避けるため == ではなく compare_digest を使う
    if not hmac.compare_digest(expected, signature):
        return False, "トークンが一致しません"
    return True, ""


def approval_urls(worker_base: str, secret: str, draft_id: str) -> dict[str, str]:
    """承認メールに載せる2つのURLを組み立てる。"""
    base = worker_base.rstrip("/")
    return {
        "approve": (
            f"{base}/approve?id={draft_id}"
            f"&t={make_token(secret, draft_id, 'approve')}"
        ),
        "reject": (
            f"{base}/reject?id={draft_id}"
            f"&t={make_token(secret, draft_id, 'reject')}"
        ),
    }
