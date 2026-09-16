/**
 * 承認ボタンの受け口（Cloudflare Worker）。
 *
 * なぜこれが必要か:
 *   メールのボタンは単なるリンクなので、クリック先で処理を実行する場所がいる。
 *   GitHubのアクセストークンをメールに載せるわけにはいかないため、
 *   トークンはこのWorkerの秘密変数に置き、メールには署名付きの短いリンクだけを載せる。
 *
 * なぜ2段階にするか:
 *   メールのセキュリティスキャナやプレビュー機能が、リンクを勝手に先読みすることがある。
 *   GETで即公開する作りだと、読む前に公開される事故が起きる。
 *   そこで GET は確認画面を返すだけにして、POST されて初めて公開する。
 *
 * 必要な秘密変数（wrangler secret put で設定）:
 *   APPROVAL_SECRET … scripts/tokens.py と同じ文字列
 *   GITHUB_TOKEN    … repo スコープの Personal Access Token
 *   GITHUB_REPO     … "ユーザー名/リポジトリ名"
 */

const ACTIONS = {
  approve: { label: "公開する", color: "#1a7f37", done: "公開処理を開始しました" },
  reject: { label: "却下する", color: "#6e7781", done: "この記事を却下しました" },
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const action = url.pathname.replace(/^\//, "");

    if (!ACTIONS[action]) {
      return page("ページが見つかりません", "URLを確認してください。", 404);
    }

    const draftId = url.searchParams.get("id");
    const token = url.searchParams.get("t");
    if (!draftId || !token) {
      return page("リンクが不正です", "IDまたはトークンがありません。", 400);
    }

    const check = await verifyToken(env.APPROVAL_SECRET, draftId, action, token);
    if (!check.ok) {
      return page("承認できません", check.reason, 403);
    }

    // --- GET: 確認画面を出すだけ。ここでは何も実行しない ---
    if (request.method === "GET") {
      return confirmPage(action, draftId, token);
    }

    // --- POST: 実際にGitHubへ通知する ---
    if (request.method === "POST") {
      try {
        await dispatchToGitHub(env, draftId, action);
      } catch (err) {
        return page("エラーが発生しました", String(err.message || err), 502);
      }
      return page(
        ACTIONS[action].done,
        action === "approve"
          ? "GitHub Actions がサイトを更新します。反映まで1〜2分ほどお待ちください。"
          : "ドラフトは公開されずに保管されます。",
        200
      );
    }

    return page("非対応のリクエストです", "", 405);
  },
};

/* -------------------------------------------------------------------------
 * トークン検証（scripts/tokens.py と同じ方式）
 * ---------------------------------------------------------------------- */

async function verifyToken(secret, draftId, action, token) {
  if (!secret) return { ok: false, reason: "サーバー側の設定が不足しています。" };

  const dot = token.indexOf(".");
  if (dot < 0) return { ok: false, reason: "トークンの形式が不正です。" };

  const expires = parseInt(token.slice(0, dot), 10);
  const signature = token.slice(dot + 1);
  if (!Number.isFinite(expires)) {
    return { ok: false, reason: "トークンの形式が不正です。" };
  }
  if (expires < Math.floor(Date.now() / 1000)) {
    return { ok: false, reason: "この承認リンクは期限切れです。新しい記事の生成をお待ちください。" };
  }

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const mac = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${draftId}:${action}:${expires}`)
  );

  const expected = base64url(new Uint8Array(mac));
  if (!timingSafeEqual(expected, signature)) {
    return { ok: false, reason: "トークンが一致しません。リンクが改変された可能性があります。" };
  }
  return { ok: true };
}

function base64url(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/* -------------------------------------------------------------------------
 * GitHub への通知
 * ---------------------------------------------------------------------- */

async function dispatchToGitHub(env, draftId, action) {
  const response = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        // GitHub API は User-Agent を必須にしている
        "User-Agent": "auto-blog-approver",
      },
      body: JSON.stringify({
        event_type: "publish-draft",
        client_payload: { draft_id: draftId, action },
      }),
    }
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `GitHubへの通知に失敗しました (HTTP ${response.status}): ${detail.slice(0, 200)}`
    );
  }
}

/* -------------------------------------------------------------------------
 * 画面
 * ---------------------------------------------------------------------- */

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

const BASE_STYLE = `
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans",
    "Noto Sans JP",sans-serif;padding:20px;color:#1a1c1f}
  .card{background:#fff;border-radius:12px;padding:32px;max-width:460px;width:100%;
    box-shadow:0 2px 8px rgba(0,0,0,.08);text-align:center}
  h1{font-size:19px;margin:0 0 12px}
  p{font-size:14px;line-height:1.8;color:#57606a;margin:0 0 20px}
  code{background:#f6f8fa;padding:2px 6px;border-radius:4px;font-size:12px;color:#57606a}
  button{border:0;border-radius:8px;padding:14px 32px;font-size:16px;font-weight:700;
    color:#fff;cursor:pointer;width:100%}
  @media (prefers-color-scheme:dark){
    body{background:#16181c;color:#e8eaed}
    .card{background:#1e2126;box-shadow:none}
    p{color:#9aa3ad}
    code{background:#24282e;color:#9aa3ad}}
`;

function page(title, message, status) {
  return new Response(
    `<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>${escapeHtml(title)}</title>
<style>${BASE_STYLE}</style></head>
<body><div class="card"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(message)}</p></div></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8" } }
  );
}

function confirmPage(action, draftId, token) {
  const meta = ACTIONS[action];
  return new Response(
    `<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>確認</title>
<style>${BASE_STYLE}</style></head>
<body><div class="card">
  <h1>本当に${escapeHtml(meta.label)}？</h1>
  <p>対象の記事<br><code>${escapeHtml(draftId)}</code></p>
  <form method="POST">
    <button type="submit" style="background:${meta.color}">${escapeHtml(meta.label)}</button>
  </form>
</div></body></html>`,
    { status: 200, headers: { "content-type": "text/html; charset=utf-8" } }
  );
}
