/* ReWatch(Iot) — shared helpers + passkey lock screen.
   Loaded on index.html before live.js. No dependencies, no CDN. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);

  // ── base64url <-> ArrayBuffer (WebAuthn) ──────────────────────────────────
  const b64 = {
    enc(buf) {
      const b = new Uint8Array(buf); let s = "";
      for (const x of b) s += String.fromCharCode(x);
      return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    },
    dec(str) {
      const s = str.replace(/-/g, "+").replace(/_/g, "/");
      const pad = s.length % 4 ? "=".repeat(4 - (s.length % 4)) : "";
      const raw = atob(s + pad); const buf = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
      return buf.buffer;
    },
  };

  async function post(url, body) {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.status === 204 ? {} : r.json();
  }

  // ── passkey ceremonies ────────────────────────────────────────────────────
  async function register(token) {
    const opt = await post("/auth/setup", { token });
    opt.challenge = b64.dec(opt.challenge);
    opt.user.id = b64.dec(opt.user.id);
    if (opt.excludeCredentials) for (const c of opt.excludeCredentials) c.id = b64.dec(c.id);
    const cred = await navigator.credentials.create({ publicKey: opt });
    const r = cred.response;
    await post("/auth/setup/complete", {
      id: cred.id, rawId: b64.enc(cred.rawId), type: cred.type,
      response: { attestationObject: b64.enc(r.attestationObject), clientDataJSON: b64.enc(r.clientDataJSON) },
      clientExtensionResults: cred.getClientExtensionResults(),
    });
  }

  async function login() {
    const opt = await post("/auth/login/begin", {});
    opt.challenge = b64.dec(opt.challenge);
    if (opt.allowCredentials) for (const c of opt.allowCredentials) c.id = b64.dec(c.id);
    const cred = await navigator.credentials.get({ publicKey: opt });
    const r = cred.response;
    await post("/auth/login/complete", {
      id: cred.id, rawId: b64.enc(cred.rawId), type: cred.type,
      response: {
        authenticatorData: b64.enc(r.authenticatorData), clientDataJSON: b64.enc(r.clientDataJSON),
        signature: b64.enc(r.signature), userHandle: r.userHandle ? b64.enc(r.userHandle) : null,
      },
      clientExtensionResults: cred.getClientExtensionResults(),
    });
  }

  // ── lock screen wiring ────────────────────────────────────────────────────
  const lock = $("#lock"), app = $("#app"), msg = $("#lk-msg");
  let demoPreview = false;
  function say(t, err) { if (msg) { msg.textContent = t || ""; msg.classList.toggle("err", !!err); } }

  function enter() {
    if (lock) lock.hidden = true;
    if (app) app.hidden = false;
    window.ReWatch && window.ReWatch.start && window.ReWatch.start();
  }

  async function status() {
    try { return await (await fetch("/auth/status", { cache: "no-store" })).json(); }
    catch { return { authenticated: false, has_owner: false }; }
  }

  async function boot() {
    try {
      const config = await (await fetch("/api/demo-options", { cache: "no-store" })).json();
      demoPreview = config.passkey_preview === true;
    } catch { /* Ordinary production authentication remains unchanged. */ }
    const st = await status();
    if (st.authenticated) { enter(); return; }
    if (!window.PublicKeyCredential) say("This browser has no passkey support — use the access code.", false);
    const label = $("#lk-label");
    if (label && !st.has_owner) label.textContent = "NO PASSKEY YET — REGISTER";
  }

  $("#lk-unlock")?.addEventListener("click", async () => {
    if (demoPreview) {
      const button = $("#lk-unlock"); button.disabled = true;
      try {
        const opt = await post("/auth/demo-preview/begin", {});
        opt.challenge = b64.dec(opt.challenge);
        try { await navigator.credentials.get({ publicKey: opt }); }
        catch { /* Optional passkey prompt */ }
        await post("/auth/demo-preview/complete", {});
        enter();
      } catch (e) { say(huma(e), true); }
      finally { button.disabled = false; }
      return;
    }
    say("Waiting for your passkey…");
    try { await login(); enter(); }
    catch (e) { say(huma(e), true); }
  });
  $("#lk-show-reg")?.addEventListener("click", () => {
    $("#lk-reg").hidden = !$("#lk-reg").hidden; $("#lk-code").hidden = true; $("#lk-token")?.focus();
  });
  $("#lk-show-code")?.addEventListener("click", () => {
    $("#lk-code").hidden = !$("#lk-code").hidden; $("#lk-reg").hidden = true; $("#lk-code-in")?.focus();
  });
  $("#lk-reg")?.addEventListener("submit", async (e) => {
    e.preventDefault(); say("Creating a passkey on this device…");
    try { await register($("#lk-token").value.trim()); enter(); }
    catch (err) { say(huma(err), true); }
  });
  $("#lk-code")?.addEventListener("submit", async (e) => {
    e.preventDefault(); say("Checking the access code…");
    try { await post("/auth/demo", { code: $("#lk-code-in").value.trim() }); enter(); }
    catch (err) { say(huma(err), true); }
  });

  function huma(e) {
    const m = String(e && e.message || e);
    if (/NotAllowed|timed out|abort/i.test(m)) return "Passkey cancelled or timed out.";
    if (/No credentials/i.test(m)) return "No passkey registered yet — register this device first.";
    return m.slice(0, 160) || "Something went wrong.";
  }

  window.ReWatchAuth = { register, login, logout: () => post("/auth/logout").catch(() => {}), b64, post };
  if (lock) boot();
})();
