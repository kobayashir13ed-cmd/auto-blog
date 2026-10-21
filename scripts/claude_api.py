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


# 出力の上限をこれ以上には広げない（費用と待ち時間の歯止め）
MAX_TOKENS_CEILING = 64000


def complete(
    prompt: str,
    api_key: str,
    model: str,
    max_tokens: int = 8000,
    system: str = "",
    retries: int = 3,
    timeout: int = 180,
    thinking: bool | None = None,
) -> str:
    """プロンプトを投げて本文テキストを返す。

    thinking について:
      新しいモデル（Sonnet 5 以降など）は、指定しなくても「考える」処理が既定で動く。
      考えた分のトークンも max_tokens に含まれるため、上限が小さいと
      考えるだけで使い切り、本文が空のまま返ってくることがある。
      False を渡すと考える処理を止める（長い文章を書かせるだけの担当向け）。
      None なら既定のまま（モデルに任せる）。
    """
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    if thinking is False:
        payload["thinking"] = {"type": "disabled"}

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
            stop = body.get("stop_reason", "")
            cut_off = stop in ("max_tokens", "model_context_window_exceeded")
            # 上限に達して途中で切れた場合（考える処理で使い切って本文が空、または本文が途中まで）は、
            # 上限を広げてもう一度だけ頼む。途中で切れた記事を使うと、末尾の見出しや差し込み記号が欠ける
            if cut_off and payload["max_tokens"] < MAX_TOKENS_CEILING:
                payload["max_tokens"] = min(payload["max_tokens"] * 2, MAX_TOKENS_CEILING)
                last_error = f"上限に達しました（{stop}）"
                print(f"  [再試行] 出力が上限に達しました（{stop}）。"
                      f"上限を{payload['max_tokens']}に広げて再試行します")
                request = urllib.request.Request(
                    ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=dict(request.headers), method="POST")
                continue
            if text.strip():
                if cut_off:
                    print(f"  [注意] 出力が上限で途中まで返っています（{stop}）")
                return text
            kinds = ",".join(sorted({b.get("type", "?") for b in blocks})) or "なし"
            raise RuntimeError(
                f"APIが本文のない応答を返しました（終了理由: {stop or '不明'} / 含まれていた部品: {kinds}）")
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


# --------------------------------------------------------------------------
# ウェブ検索つきの呼び出し（メーカー公式サイトの仕様確認に使う）
# --------------------------------------------------------------------------

def complete_with_web(
    prompt: str,
    api_key: str,
    model: str,
    tools: list[dict],
    betas: list[str] | None = None,
    max_tokens: int = 16000,
    system: str = "",
    timeout: int = 600,
    max_turns: int = 4,
) -> tuple[str, dict]:
    """Claude にウェブ検索・ページ取得の道具を持たせて答えさせる。

    検索と取得は Anthropic のサーバー側で行われる（このプログラムが直接サイトを読むのではない）。
    返り値は (最後の本文テキスト, 実際に取得したページ {URL: 本文テキスト})。
    取得したページの一覧は、AIが「見ていないページを出典に書く」ことを防ぐ照合に使う。

    検索が長引くと stop_reason が pause_turn で返るので、そのまま続きを頼む。
    """
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    }
    if betas:
        headers["anthropic-beta"] = ",".join(betas)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    fetched: dict[str, str] = {}
    so_far: list[dict] = []          # 途中で止まった場合に、ここまでの応答を渡して続けてもらう
    for _ in range(max_turns):
        payload: dict = {"model": model, "max_tokens": max_tokens,
                         "messages": messages, "tools": tools}
        if system:
            payload["system"] = system
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"ウェブ検索つきの呼び出しに失敗しました（HTTP {exc.code}）: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Claude APIに接続できません: {exc.reason}") from exc

        blocks = body.get("content", [])
        so_far += blocks
        for b in blocks:
            if b.get("type") != "web_fetch_tool_result":
                continue
            result = b.get("content") or {}
            url = result.get("url")
            if result.get("type") != "web_fetch_result" or not url:
                continue
            source = ((result.get("content") or {}).get("source") or {})
            fetched[url] = source.get("data", "") if source.get("type") == "text" else ""
        if body.get("stop_reason") != "pause_turn":
            break
        messages = messages[:1] + [{"role": "assistant", "content": so_far}]
    text = "".join(b.get("text", "") for b in so_far if b.get("type") == "text")
    return text, fetched
