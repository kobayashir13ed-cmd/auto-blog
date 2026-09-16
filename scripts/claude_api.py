"""Claude API クライアント（記事本文の生成）。

外部SDKを使わず標準ライブラリだけで呼ぶ。CIでの依存を減らすため。
APIキーは環境変数 ANTHROPIC_API_KEY から読む。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def complete(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int = 8000,
    system: str = "",
    retries: int = 3,
    timeout: int = 180,
) -> str:
    """プロンプトを投げて本文テキストを返す。"""
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )

    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            blocks = body.get("content", [])
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if not text.strip():
                raise RuntimeError("APIが空の応答を返しました")
            return text
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            last_error = f"HTTP {exc.code}: {detail}"
            # 429（レート制限）と5xx（一時障害）は待って再試行する価値がある
            if exc.code in (429, 500, 502, 503, 529) and attempt < retries:
                wait = 2 ** attempt * 5
                print(f"  [再試行 {attempt}/{retries}] {wait}秒待機します（{last_error[:80]}）")
                time.sleep(wait)
                continue
            if exc.code == 401:
                raise RuntimeError(
                    "Claude APIキーが無効です。ANTHROPIC_API_KEY を確認してください。"
                ) from exc
            if exc.code == 404:
                raise RuntimeError(
                    f"モデル '{model}' が見つかりません。config.json の model を\n"
                    "  https://docs.claude.com/en/docs/about-claude/models で\n"
                    "  現行のモデルIDに更新してください。"
                ) from exc
            raise RuntimeError(f"Claude APIエラー: {last_error}") from exc
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            if attempt < retries:
                time.sleep(2 ** attempt * 5)
                continue
            raise RuntimeError(f"Claude APIに接続できません: {last_error}") from exc

    raise RuntimeError(f"Claude APIの呼び出しに失敗しました: {last_error}")
