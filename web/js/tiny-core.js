/* TinyADA shared code (tiny.gmcat.io). The address checks here mirror gmcat-tinyada/coins.py on the server:
   the page checks as you type, the server checks again before storing anything. */
(function () {
  "use strict";
  var T = window.Tiny = {};

  T.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  };
  T.$ = function (id) { return document.getElementById(id); };

  /* "My links (n)" in the top bar, only when this browser has made links (they live in localStorage "tiny-mine") */
  T.mineNav = function () {
    var a = document.querySelector("[data-mine-nav]"), n = 0;
    try { n = JSON.parse(localStorage.getItem("tiny-mine") || "[]").filter(function (x) { return x.mode === "inuse" || x.expires > Date.now() / 1000; }).length; } catch (e) { n = 0; }
    if (!a) return;
    a.hidden = !n;
    a.textContent = "My links (" + n + ")";
  };
  document.addEventListener("DOMContentLoaded", T.mineNav);

  T.api = function (method, path, body, headers) {
    var h = { "Accept": "application/json" };
    if (body !== undefined) h["Content-Type"] = "application/json";
    for (var k in headers || {}) h[k] = headers[k];
    return fetch("/api/tiny" + path, { method: method, headers: h, body: body === undefined ? undefined : JSON.stringify(body), credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, status: r.status, data: d }; }); })
      .catch(function () { return { ok: false, status: 0, data: { error: "Couldn't reach TinyADA. Check your connection and try again." } }; });
  };

  T.fmtDate = function (ts) {
    return new Date(ts * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  };

  T.copy = function (text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(function () { return true; }, fallback);
    return Promise.resolve(fallback());
    function fallback() {
      var t = document.createElement("textarea");
      t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
      document.body.appendChild(t); t.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      t.remove();
      return ok;
    }
  };
  T.flash = function (btn, text) {
    var old = btn.dataset.label || btn.textContent;
    btn.dataset.label = old; btn.textContent = text;
    clearTimeout(btn._t); btn._t = setTimeout(function () { btn.textContent = old; }, 1600);
  };

  /* ---------- in-page dialogs (never the browser's own confirm/alert/prompt boxes) ----------
     T.ask({title, text, ok, cancel, danger, input, placeholder, html}) -> Promise (true/false, or the typed value / null)
     T.tell({title, text}) -> Promise */
  T.ask = function (o) {
    return new Promise(function (resolve) {
      var d = document.createElement("dialog");
      d.className = "t-dlg card t-ask";
      d.setAttribute("aria-labelledby", "t-ask-h");
      d.innerHTML = '<form method="dialog"><h2 class="panel-h" id="t-ask-h">' + T.esc(o.title || "Are you sure?") + "</h2>" +
        (o.text ? '<p class="t-ask-text">' + T.esc(o.text) + "</p>" : "") + (o.html || "") +
        (o.input ? '<input class="t-ask-input" type="' + (o.input === "password" ? "password" : "text") + '" autocomplete="off" aria-label="' + T.esc(o.placeholder || o.title || "") + '" placeholder="' + T.esc(o.placeholder || "") + '">' : "") +
        '<div class="tool-actions"><button class="btn ' + (o.danger ? "t-danger" : "primary") + '" value="ok">' + T.esc(o.ok || "OK") + "</button>" +
        (o.cancel === false ? "" : '<button class="btn" value="cancel" formnovalidate>' + T.esc(o.cancel || "Cancel") + "</button>") + "</div></form>";
      document.body.appendChild(d);
      var input = d.querySelector(".t-ask-input"), done = false;
      function finish(okd) {
        if (done) return; done = true;
        var v = input ? (okd ? input.value : null) : okd;
        if (d.open) d.close();
        d.remove();
        resolve(v);
      }
      d.addEventListener("close", function () { finish(d.returnValue === "ok"); });
      d.addEventListener("cancel", function (ev) { ev.preventDefault(); finish(false); });
      d.addEventListener("click", function (ev) { if (ev.target === d) finish(false); });
      d.showModal();
      (input || d.querySelector('button[value="' + (o.danger ? "cancel" : "ok") + '"]') || d.querySelector("button")).focus();
    });
  };
  T.tell = function (o) { return T.ask({ title: o.title || "Heads up", text: o.text, html: o.html, ok: "OK", cancel: false }); };
  document.addEventListener("click", function (ev) {   // [data-close] buttons in static dialogs
    var b = ev.target.closest && ev.target.closest("[data-close]");
    if (b) { var d = b.closest("dialog"); if (d) d.close(); }
  });

  /* ---------- QR codes (vendored qrcode-generator, MIT) ---------- */
  T.qrSvg = function (text) {
    if (!window.qrcode) return "";
    var q = qrcode(0, "M"); q.addData(text); q.make();
    return q.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
  };
  /* Draw a QR code onto a canvas. o: {text, fg, bg, logo (Image), caption, mark} */
  T.drawQr = function (canvas, o) {
    var q = qrcode(0, o.logo ? "H" : "M"); q.addData(o.text); q.make();
    var n = q.getModuleCount(), W = canvas.width, pad = Math.round(W * 0.07), cap = o.caption ? Math.round(W * 0.16) : 0;
    canvas.height = W + cap;
    var c = canvas.getContext("2d"), cell = (W - 2 * pad) / n;
    c.fillStyle = o.bg || "#ffffff"; c.fillRect(0, 0, W, canvas.height);
    c.fillStyle = o.fg || "#141a3a";
    for (var r = 0; r < n; r++) for (var col = 0; col < n; col++) if (q.isDark(r, col)) c.fillRect(Math.floor(pad + col * cell), Math.floor(pad + r * cell), Math.ceil(cell), Math.ceil(cell));
    if (o.logo) {
      var s = (W - 2 * pad) * 0.22, x = (W - s) / 2;
      c.fillStyle = o.bg || "#ffffff"; c.fillRect(x - cell, x - cell, s + 2 * cell, s + 2 * cell);
      var k = Math.min(s / o.logo.width, s / o.logo.height), lw = o.logo.width * k, lh = o.logo.height * k;
      c.drawImage(o.logo, (W - lw) / 2, (W - lh) / 2, lw, lh);
    }
    if (cap) {
      c.fillStyle = o.fg || "#141a3a"; c.textAlign = "center"; c.textBaseline = "middle";
      var size = Math.round(W * 0.055);
      c.font = "800 " + size + "px 'DM Sans', system-ui, sans-serif";
      while (c.measureText(o.caption).width > W - 2 * pad && size > 12) { size -= 2; c.font = "800 " + size + "px 'DM Sans', system-ui, sans-serif"; }
      c.fillText(o.caption, W / 2, W + cap * 0.32);
      if (o.mark !== false) { c.font = "600 " + Math.round(W * 0.03) + "px 'DM Sans', system-ui, sans-serif"; c.globalAlpha = 0.65; c.fillText("//TinyADA · tiny.gmcat.io", W / 2, W + cap * 0.72); c.globalAlpha = 1; }
    }
    return canvas;
  };
  T.download = function (canvas, name) {
    canvas.toBlob(function (b) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(b); a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
    }, "image/png");
  };

  /* ---------- address checks ---------- */
  var B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l", BECH32 = 1, BECH32M = 0x2bc830a3;
  function polymod(v) {
    var g = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3], c = 1;
    for (var i = 0; i < v.length; i++) {
      var b = c >>> 25;
      c = ((c & 0x1ffffff) << 5) ^ v[i];
      for (var j = 0; j < 5; j++) if ((b >>> j) & 1) c ^= g[j];
    }
    return c >>> 0;
  }
  function expand(h) { var a = [], i; for (i = 0; i < h.length; i++) a.push(h.charCodeAt(i) >> 5); a.push(0); for (i = 0; i < h.length; i++) a.push(h.charCodeAt(i) & 31); return a; }
  function convert(data, f, t, pad) {
    var acc = 0, bits = 0, out = [], m = (1 << t) - 1;
    for (var i = 0; i < data.length; i++) { acc = (acc << f) | data[i]; bits += f; while (bits >= t) { bits -= t; out.push((acc >> bits) & m); } acc &= (1 << bits) - 1; }
    if (pad) { if (bits) out.push((acc << (t - bits)) & m); }
    else if (bits >= f || ((acc << (t - bits)) & m)) return null;
    return out;
  }
  function bech32Parse(s) {
    if (s !== s.toLowerCase() && s !== s.toUpperCase()) return null;
    s = s.toLowerCase();
    var pos = s.lastIndexOf("1");
    if (pos < 1 || pos + 7 > s.length) return null;
    var hrp = s.slice(0, pos), data = [];
    for (var i = pos + 1; i < s.length; i++) { var d = B32.indexOf(s[i]); if (d < 0) return null; data.push(d); }
    var c = polymod(expand(hrp).concat(data)), spec = c === BECH32 ? BECH32 : c === BECH32M ? BECH32M : 0;
    return spec ? { hrp: hrp, data: data.slice(0, -6), spec: spec } : null;
  }
  function bech32Bytes(s) { var p = bech32Parse(s); if (!p || p.spec !== BECH32) return null; var b = convert(p.data, 5, 8, false); return b ? { hrp: p.hrp, bytes: b } : null; }
  function segwit(hrp, s) {
    var p = bech32Parse(s);
    if (!p || p.hrp !== hrp || !p.data.length) return false;
    var ver = p.data[0], prog = convert(p.data.slice(1), 5, 8, false);
    if (!prog || ver > 16 || prog.length < 2 || prog.length > 40) return false;
    if (ver === 0 && (p.spec !== BECH32 || (prog.length !== 20 && prog.length !== 32))) return false;
    if (ver !== 0 && p.spec !== BECH32M) return false;
    return s.length <= 90;
  }
  var B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  function b58decode(s) {
    var bytes = [0];
    for (var i = 0; i < s.length; i++) {
      var v = B58.indexOf(s[i]); if (v < 0) return null;
      for (var j = 0; j < bytes.length; j++) { v += bytes[j] * 58; bytes[j] = v & 255; v >>= 8; }
      while (v) { bytes.push(v & 255); v >>= 8; }
    }
    var zeros = 0; while (zeros < s.length && s[zeros] === "1") zeros++;
    var out = bytes.reverse(); while (out.length && out[0] === 0) out.shift();
    return new Array(zeros).fill(0).concat(s.length ? out : []);
  }
  // SHA-256 (small sync version; only used for base58 checks)
  var K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  function sha256(bytes) {
    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19], l = bytes.length, m = bytes.slice();
    m.push(0x80); while (m.length % 64 !== 56) m.push(0);
    for (var s = 7; s >= 0; s--) m.push(s >= 4 ? 0 : ((l * 8) >>> (s * 8)) & 255);
    var w = new Array(64);
    for (var o = 0; o < m.length; o += 64) {
      for (var i = 0; i < 16; i++) w[i] = (m[o + 4 * i] << 24) | (m[o + 4 * i + 1] << 16) | (m[o + 4 * i + 2] << 8) | m[o + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var a0 = w[i - 15], a1 = w[i - 2];
        var s0 = ((a0 >>> 7) | (a0 << 25)) ^ ((a0 >>> 18) | (a0 << 14)) ^ (a0 >>> 3), s1 = ((a1 >>> 17) | (a1 << 15)) ^ ((a1 >>> 19) | (a1 << 13)) ^ (a1 >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var A = h[0], B = h[1], C = h[2], D = h[3], E = h[4], F = h[5], G = h[6], H = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7)), ch = (E & F) ^ (~E & G), t1 = (H + S1 + ch + K[i] + w[i]) | 0;
        var S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10)), mj = (A & B) ^ (A & C) ^ (B & C), t2 = (S0 + mj) | 0;
        H = G; G = F; F = E; E = (D + t1) | 0; D = C; C = B; B = A; A = (t1 + t2) | 0;
      }
      h = [h[0] + A | 0, h[1] + B | 0, h[2] + C | 0, h[3] + D | 0, h[4] + E | 0, h[5] + F | 0, h[6] + G | 0, h[7] + H | 0];
    }
    var out = []; h.forEach(function (x) { out.push((x >>> 24) & 255, (x >>> 16) & 255, (x >>> 8) & 255, x & 255); });
    return out;
  }
  function b58check(s) {
    var b = b58decode(s);
    if (!b || b.length !== 25) return null;
    var h = sha256(sha256(b.slice(0, 21)));
    for (var i = 0; i < 4; i++) if (h[i] !== b[21 + i]) return null;
    return b[0];
  }
  // keccak-256 (Ethereum's EIP-55 capital-letter check)
  var RC = ["0x1", "0x8082", "0x800000000000808a", "0x8000000080008000", "0x808b", "0x80000001", "0x8000000080008081", "0x8000000000008009", "0x8a", "0x88", "0x80008009", "0x8000000a", "0x8000808b", "0x800000000000008b", "0x8000000000008089", "0x8000000000008003", "0x8000000000008002", "0x8000000000000080", "0x800a", "0x800000008000000a", "0x8000000080008081", "0x8000000000008080", "0x80000001", "0x8000000080008008"].map(BigInt);
  var ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]], M64 = (1n << 64n) - 1n;
  function rol(x, n) { n = BigInt(n); return n ? ((x << n) | (x >> (64n - n))) & M64 : x; }
  function keccak256(bytes) {
    var rate = 136, msg = bytes.slice(); msg.push(1); while (msg.length % rate) msg.push(0); msg[msg.length - 1] |= 0x80;
    var st = [], x, y, i;
    for (x = 0; x < 5; x++) st.push([0n, 0n, 0n, 0n, 0n]);
    for (var off = 0; off < msg.length; off += rate) {
      for (i = 0; i < rate / 8; i++) { var v = 0n; for (var k = 7; k >= 0; k--) v = (v << 8n) | BigInt(msg[off + 8 * i + k]); st[i % 5][Math.floor(i / 5)] ^= v; }
      for (var r = 0; r < 24; r++) {
        var c = [], d = [], b = [];
        for (x = 0; x < 5; x++) c[x] = st[x][0] ^ st[x][1] ^ st[x][2] ^ st[x][3] ^ st[x][4];
        for (x = 0; x < 5; x++) d[x] = c[(x + 4) % 5] ^ rol(c[(x + 1) % 5], 1);
        for (x = 0; x < 5; x++) { b.push([0n, 0n, 0n, 0n, 0n]); for (y = 0; y < 5; y++) st[x][y] ^= d[x]; }
        for (x = 0; x < 5; x++) for (y = 0; y < 5; y++) b[y][(2 * x + 3 * y) % 5] = rol(st[x][y], ROT[x][y]);
        for (x = 0; x < 5; x++) for (y = 0; y < 5; y++) st[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y] & M64) & b[(x + 2) % 5][y]);
        st[0][0] ^= RC[r];
      }
    }
    var out = "";
    for (i = 0; i < 4; i++) { var lane = st[i % 5][Math.floor(i / 5)]; for (k = 0; k < 8; k++) out += Number((lane >> BigInt(8 * k)) & 255n).toString(16).padStart(2, "0"); }
    return out;
  }
  function eip55(hex40) {
    var low = hex40.toLowerCase(), h = keccak256(Array.from(low, function (ch) { return ch.charCodeAt(0); })), out = "";
    for (var i = 0; i < 40; i++) out += /[a-f]/.test(low[i]) && parseInt(h[i], 16) >= 8 ? low[i].toUpperCase() : low[i];
    return out;
  }
  var CRC = (function () { var t = [], c; for (var n = 0; n < 256; n++) { c = n; for (var k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(b) { var c = 0xffffffff; for (var i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
  function cborHead(b, i) {
    var ib = b[i], major = ib >> 5, info = ib & 31; i++;
    if (info < 24) return [major, info, i];
    var n = { 24: 1, 25: 2, 26: 4, 27: 8 }[info]; if (!n || i + n > b.length) throw 0;
    var v = 0; for (var k = 0; k < n; k++) v = v * 256 + b[i + k];
    return [major, v, i + n];
  }
  function byronOk(s) {
    var b = b58decode(s); if (!b || b.length < 30) return false;
    try {
      var h = cborHead(b, 0); if (h[0] !== 4 || h[1] !== 2) return false;
      h = cborHead(b, h[2]); if (h[0] !== 6 || h[1] !== 24) return false;
      h = cborHead(b, h[2]); if (h[0] !== 2) return false;
      var payload = b.slice(h[2], h[2] + h[1]), ln = h[1]; h = cborHead(b, h[2] + ln);
      return h[0] === 0 && h[2] === b.length && payload.length === ln && crc32(payload) === h[1];
    } catch (e) { return false; }
  }
  var TYPO = function (name) { return "This " + name + " address has a typo: its built-in check doesn't match."; };
  var CHECKS = {
    ADA: function (s) {
      var low = s.toLowerCase();
      if (/^(addr_test1|stake_test1)/.test(low)) return [null, "That's a Cardano test-network address. People can't send real ADA to it."];
      if (low.indexOf("stake1") === 0) return [null, "That's a stake (rewards) address. Use a receiving address that starts with addr1."];
      if (low.indexOf("addr1") === 0) {
        var r = bech32Bytes(s);
        if (!r || r.hrp !== "addr") return [null, TYPO("Cardano")];
        var kind = r.bytes[0] >> 4, net = r.bytes[0] & 15;
        if (net !== 1 || kind > 7) return [null, "This isn't a main-network Cardano receiving address."];
        var want = kind === 6 || kind === 7 ? 29 : kind <= 3 ? 57 : 0;
        if ((want && r.bytes.length !== want) || ((kind === 4 || kind === 5) && r.bytes.length < 30)) return [null, "This Cardano address is the wrong length. Check you copied all of it."];
        return [low, null];
      }
      if (/^(Ae2|Ddz)/.test(s)) return byronOk(s) ? [s, null] : [null, "This older (Byron) Cardano address has a typo: its built-in check doesn't match."];
      return [null, "Cardano addresses start with addr1."];
    },
    BTC: function (s) {
      if (/^bc1/i.test(s)) return segwit("bc", s) ? [s.toLowerCase(), null] : [null, TYPO("Bitcoin")];
      if (/^(tb1|bcrt1)/i.test(s)) return [null, "That's a Bitcoin test-network address."];
      var v = b58check(s);
      if (v === 0 || v === 5) return [s, null];
      return [null, /^[13]/.test(s) ? TYPO("Bitcoin") : "Bitcoin addresses start with 1, 3 or bc1."];
    },
    ETH: function (s) {
      if (!/^0[xX][0-9a-fA-F]{40}$/.test(s)) return [null, "Ethereum addresses are 0x followed by 40 letters and numbers (0-9, a-f)."];
      var body = s.slice(2);
      if (body !== body.toLowerCase() && body !== body.toUpperCase() && eip55(body) !== body) return [null, "This Ethereum address has a typo: its capital letters don't match its built-in check."];
      return ["0x" + eip55(body), null];
    },
    SOL: function (s) {
      if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(s)) return [null, "Solana addresses are 32 to 44 letters and numbers."];
      var b = b58decode(s);
      return b && b.length === 32 ? [s, null] : [null, "This Solana address is the wrong length. Check you copied all of it."];
    },
    LTC: function (s) {
      if (/^ltc1/i.test(s)) return segwit("ltc", s) ? [s.toLowerCase(), null] : [null, TYPO("Litecoin")];
      var v = b58check(s);
      if (v === 0x30 || v === 0x32 || v === 5) return [s, null];
      return [null, /^[LM3]/.test(s) ? TYPO("Litecoin") : "Litecoin addresses start with L, M, 3 or ltc1."];
    },
    DOGE: function (s) {
      var v = b58check(s);
      if (v === 0x1e || v === 0x16) return [s, null];
      return [null, /^[DA9]/.test(s) ? TYPO("Dogecoin") : "Dogecoin addresses start with D, A or 9."];
    }
  };
  T.COINS = {
    ADA: { name: "Cardano", sym: "ADA", decimals: 6 }, BTC: { name: "Bitcoin", sym: "BTC", decimals: 8 }, ETH: { name: "Ethereum", sym: "ETH", decimals: 18 },
    SOL: { name: "Solana", sym: "SOL", decimals: 9 }, LTC: { name: "Litecoin", sym: "LTC", decimals: 8 }, DOGE: { name: "Dogecoin", sym: "DOGE", decimals: 8 }
  };
  T.ORDER = ["ADA", "BTC", "ETH", "SOL", "LTC", "DOGE"];
  T.clean = function (s) { return String(s || "").replace(/\s+/g, "").slice(0, 200); };
  T.isHandle = function (s) { return /^\$[a-z0-9_.-]{1,15}$/i.test(s); };
  T.check = function (coin, s) { s = T.clean(s); return CHECKS[coin] ? CHECKS[coin](s) : [null, "Pick a coin."]; };
  T.detect = function (s) {
    s = T.clean(s);
    return s ? T.ORDER.filter(function (c) { return CHECKS[c](s)[0]; }) : [];
  };
  /* The best hint for something that isn't valid for any coin */
  T.why = function (s) {
    s = T.clean(s);
    var guess = /^(addr|stake|Ae2|Ddz)/i.test(s) ? "ADA" : /^(bc1|tb1|[13])/i.test(s) && !/^3.{0,2}$/.test(s) ? "BTC" : /^0x/i.test(s) ? "ETH" : /^ltc1|^[LM]/.test(s) ? "LTC" : /^[DA9]/.test(s) && s.length < 40 ? "DOGE" : null;
    return guess ? CHECKS[guess](s)[1] : "That doesn't look like an address we know. TinyADA works with Cardano, Bitcoin, Ethereum, Solana, Litecoin and Dogecoin.";
  };
  T.addrBytesHex = function (addr) { var r = bech32Bytes(addr); return r ? r.bytes.map(function (b) { return b.toString(16).padStart(2, "0"); }).join("") : ""; };

  /* The address in groups of four, with the ending in bold (people compare the ending with their wallet). */
  T.addrHtml = function (a) {
    var end = a.slice(-6), head = a.slice(0, -6), pre = (head.match(/^(addr1|bc1|ltc1|0x)/i) || [""])[0], mid = head.slice(pre.length), groups = [];
    for (var k = mid.length; k > 0; k -= 4) groups.unshift(mid.slice(Math.max(0, k - 4), k));
    return T.esc((pre ? [pre] : []).concat(groups).join(" ")) + " <b>" + T.esc(end) + "</b>";
  };

  /* Wallet payment links: CIP-13 (Cardano), BIP-21 (Bitcoin family), EIP-681 (Ethereum), Solana Pay */
  function toUnits(amount, decimals) {
    var p = String(amount).split("."), frac = (p[1] || "").padEnd(decimals, "0").slice(0, decimals);
    return (BigInt(p[0] || "0") * (10n ** BigInt(decimals)) + BigInt(frac || "0")).toString();
  }
  T.payUri = function (it) {
    var q = [], a = it.address;
    if (it.coin === "ADA") return "web+cardano:" + a + (it.amount ? "?amount=" + it.amount : "");
    if (it.coin === "ETH") return "ethereum:" + a + (it.amount ? "?value=" + toUnits(it.amount, 18) : "");
    var scheme = { BTC: "bitcoin", LTC: "litecoin", DOGE: "dogecoin", SOL: "solana" }[it.coin];
    if (it.amount) q.push("amount=" + it.amount);
    if (it.memo) q.push((it.coin === "SOL" ? "message=" : "message=") + encodeURIComponent(it.memo));
    return scheme + ":" + a + (q.length ? "?" + q.join("&") : "");
  };
})();
