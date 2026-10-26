'use strict';
// "Sign in with Hugging Face" for the gated Stable Audio 3 checkpoints, as a native app does it (RFC 8252):
// the system browser opens Hugging Face's consent page, which sends the user back to a one-off server on
// 127.0.0.1 with a code, and the code plus a PKCE verifier buys an access token. No client secret: the app's
// client id is the URL of its metadata document on remiqora.com (.well-known/oauth-cimd in the site repo inikolax/remiqora-site), which lists the
// loopback redirect; Hugging Face accepts any port on it. The `gated-repos` scope reads public gated repos the
// user was granted, and nothing private. The licence of each model is still accepted on its page.
const http = require('node:http');
const crypto = require('node:crypto');

const CLIENT_ID = 'https://remiqora.com/.well-known/oauth-cimd';
const HF = 'https://huggingface.co';
const SCOPE = 'openid profile gated-repos';
const TIMEOUT_MS = 5 * 60 * 1000;

const b64url = (buf) => buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

const escHtml = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

/** The page the browser shows after the redirect: the user goes back to the app; a failure says why. */
function donePage(ok, reason = '') {
  const [en, ru] = ok
    ? ['Signed in. You can close this tab and go back to Remiqora.', 'Вход выполнен. Закройте вкладку и вернитесь в Remiqora.']
    : ['Sign-in did not finish. Go back to Remiqora and try again.', 'Вход не завершён. Вернитесь в Remiqora и попробуйте ещё раз.'];
  return `<!doctype html><meta charset="utf-8"><title>Remiqora</title>
<body style="font:16px/1.5 system-ui,sans-serif;background:#0f0f14;color:#ececf1;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:32rem;padding:24px"><p>${en}</p><p>${ru}</p>${reason ? `<p style="color:#9a9aab;font-size:14px">${escHtml(reason)}</p>` : ''}</div></body>`;
}

/**
 * Opens the browser and waits for the redirect. Resolves to an access token; rejects with an Error whose `code` is
 * 'denied' (the user said no), 'timeout', 'aborted' or 'network'. `openUrl` is shell.openExternal.
 */
function signInWithHuggingFace({ openUrl, signal } = {}) {
  return new Promise((resolve, reject) => {
    const verifier = b64url(crypto.randomBytes(32));
    const challenge = b64url(crypto.createHash('sha256').update(verifier).digest());
    const state = b64url(crypto.randomBytes(16));
    let redirectUri = '';
    let settled = false;

    const fail = (code, message) => { const e = new Error(message || code); e.code = code; finish(e); };
    const finish = (err, token) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      server.close();
      if (err) reject(err); else resolve(token);
    };
    const onAbort = () => fail('aborted');

    const server = http.createServer(async (req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      if (url.pathname !== '/callback') { res.writeHead(404).end(); return; }
      const params = url.searchParams;
      // a stale or forged redirect is ignored; the real one may still come
      if (params.get('state') !== state) { res.writeHead(400).end(); return; }
      const code = params.get('code');
      if (!code) {
        const why = params.get('error_description') || params.get('error') || 'no code in the redirect';
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(donePage(false, why));
        fail('denied', why);
        return;
      }
      // A code can be exchanged once. A browser may load the redirect twice (Hugging Face sends it back at once when
      // the app was authorized before), so every request waits for the one exchange and shows its outcome.
      if (!exchange) exchange = exchangeCode(code);
      const outcome = await exchange;
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(donePage(!!outcome.token, outcome.error));
      if (outcome.token) finish(null, outcome.token);
      else fail('network', `token exchange: ${outcome.error}`);
    });
    let exchange = null;
    const exchangeCode = async (code) => {
      try {
        const r = await fetch(`${HF}/oauth/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ grant_type: 'authorization_code', code, redirect_uri: redirectUri, client_id: CLIENT_ID, code_verifier: verifier }),
          signal: AbortSignal.timeout(20000),
        });
        const body = await r.json().catch(() => ({}));
        if (!r.ok || !body.access_token) return { error: body.error_description || body.error || `HTTP ${r.status}` };
        return { token: body.access_token };
      } catch (err) {
        return { error: err.message };
      }
    };
    const timer = setTimeout(() => fail('timeout'), TIMEOUT_MS);
    signal?.addEventListener('abort', onAbort, { once: true });
    server.on('error', (err) => fail('network', err.message));
    server.listen(0, '127.0.0.1', () => {
      redirectUri = `http://127.0.0.1:${server.address().port}/callback`;
      const q = new URLSearchParams({
        client_id: CLIENT_ID, redirect_uri: redirectUri, response_type: 'code', scope: SCOPE,
        state, code_challenge: challenge, code_challenge_method: 'S256',
      });
      Promise.resolve(openUrl(`${HF}/oauth/authorize?${q}`)).catch((err) => fail('network', err.message));
    });
  });
}

module.exports = { signInWithHuggingFace, CLIENT_ID, SCOPE };
