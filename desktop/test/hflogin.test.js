'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { signInWithHuggingFace, CLIENT_ID } = require('../src/hfLogin');

/** Plays Hugging Face: takes the authorize URL the app opens and loads the redirect the way a browser would. */
function fakeHuggingFace(t, { token = 'hf_oauth_test', redirects = 1, query = null } = {}) {
  const exchanges = [];
  const realFetch = global.fetch;
  t.after(() => { global.fetch = realFetch; });
  global.fetch = async (url, opts) => {
    if (String(url).endsWith('/oauth/token')) {
      exchanges.push(Object.fromEntries(new URLSearchParams(opts.body)));
      // a code is good once, as on the real server
      const ok = exchanges.length === 1;
      return new Response(JSON.stringify(ok ? { access_token: token } : { error: 'invalid_grant' }), { status: ok ? 200 : 400 });
    }
    return realFetch(url, opts);
  };
  const pages = [];
  const openUrl = async (authorize) => {
    const a = new URL(authorize);
    const back = new URL(a.searchParams.get('redirect_uri'));
    for (const [k, v] of Object.entries(query || { code: 'the-code', state: a.searchParams.get('state') })) back.searchParams.set(k, v);
    // the browser loads the redirect, some browsers twice at once
    const loads = Array.from({ length: redirects }, () => realFetch(back).then((r) => r.text()));
    pages.push(...(await Promise.all(loads)));
  };
  return { openUrl, exchanges, pages };
}

test('the browser sign-in gets a token with PKCE and no secret', async (t) => {
  const hf = fakeHuggingFace(t);
  assert.equal(await signInWithHuggingFace({ openUrl: hf.openUrl }), 'hf_oauth_test');
  assert.equal(hf.exchanges.length, 1);
  const ex = hf.exchanges[0];
  assert.equal(ex.client_id, CLIENT_ID);
  assert.equal(ex.grant_type, 'authorization_code');
  assert.match(ex.redirect_uri, /^http:\/\/127\.0\.0\.1:\d+\/callback$/);
  assert.ok(ex.code_verifier.length >= 43);
  assert.equal(ex.client_secret, undefined);
});

test('a redirect loaded twice exchanges the code once and still signs in', async (t) => {
  const hf = fakeHuggingFace(t, { redirects: 2 });
  assert.equal(await signInWithHuggingFace({ openUrl: hf.openUrl }), 'hf_oauth_test');
  assert.equal(hf.exchanges.length, 1);
  assert.ok(hf.pages.every((p) => p.includes('Signed in')));
});

test('a refusal on Hugging Face ends the sign-in and the page says why', async (t) => {
  let state = '';
  let page = null;
  const hf = fakeHuggingFace(t);
  const openUrl = async (authorize) => {
    const a = new URL(authorize);
    state = a.searchParams.get('state');
    const back = new URL(a.searchParams.get('redirect_uri'));
    back.searchParams.set('error', 'access_denied');
    back.searchParams.set('error_description', 'The user denied the request');
    back.searchParams.set('state', state);
    page = fetch(back).then((r) => r.text());
  };
  await assert.rejects(signInWithHuggingFace({ openUrl }), (err) => err.code === 'denied' && /denied the request/.test(err.message));
  // the page is answered as the sign-in ends
  assert.match(await page, /The user denied the request/);
  assert.equal(hf.exchanges.length, 0);
});
