/* TinyADA: the "make a link" page. */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$;
  var addr = $("t-addr"), detectEl = $("t-detect"), go = $("t-go"), err = $("t-err");
  var state = { coin: null, value: "", handle: null, ok: false }, timer = null, seq = 0;
  var KEEP_NOTE = { inuse: "Stays while people open it. Deleted after 6 months without a visit.", "30d": "Deleted 30 days from now.", "7d": "Deleted 7 days from now.", "1d": "Deleted 24 hours from now." };

  function keep() { return document.querySelector('input[name="t-keep"]:checked').value; }
  function setDetect(html) { detectEl.innerHTML = html; }
  function setCoin(c) {
    state.coin = c;
    $("t-amt-sym").textContent = c ? T.COINS[c].sym : "";
    detectEl.querySelectorAll(".t-coin-pick button").forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.coin === c ? "true" : "false"); });
    go.disabled = !state.ok || !c;
  }

  function check() {
    var raw = addr.value.trim(), my = ++seq;
    err.textContent = "";
    state = { coin: null, value: raw, handle: null, ok: false };
    go.disabled = true;
    if (!raw) { setDetect('<span class="muted">Works with Cardano, Bitcoin, Ethereum, Solana, Litecoin and Dogecoin.</span>'); return; }
    if (raw[0] === "$") {
      if (!T.isHandle(raw)) { setDetect('<span class="t-bad">A $handle is $ followed by up to 15 letters, numbers, dots, dashes or underscores.</span>'); return; }
      setDetect('<span class="muted">Looking up ' + T.esc(raw.toLowerCase()) + "…</span>");
      T.api("GET", "/handle/" + encodeURIComponent(raw.slice(1).toLowerCase())).then(function (r) {
        if (my !== seq) return;
        if (!r.ok) { setDetect('<span class="t-bad">' + T.esc(r.data.error || "We couldn't find that $handle.") + "</span>"); return; }
        state.handle = r.data.handle; state.ok = true;
        setDetect('<span class="t-ok">✓ Cardano $handle</span><span class="muted">' + T.esc(r.data.handle) + " → …" + T.esc(r.data.address.slice(-10)) + "</span>");
        setCoin("ADA");
      });
      return;
    }
    var coins = T.detect(raw);
    if (!coins.length) { setDetect('<span class="t-bad">' + T.esc(T.why(raw)) + "</span>"); return; }
    state.ok = true;
    if (coins.length === 1) {
      setDetect('<span class="t-ok">✓ ' + T.COINS[coins[0]].name + " address</span><span class=\"muted\">The built-in typo check matches.</span>");
    } else {
      setDetect('<span class="t-ok">✓ Valid address.</span><span class="muted">This could be</span><span class="t-coin-pick">' +
        coins.map(function (c) { return '<button type="button" data-coin="' + c + '" aria-pressed="false">' + T.COINS[c].name + "</button>"; }).join("") + "</span>");
    }
    setCoin(coins[0]);
  }

  addr.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(check, addr.value.trim()[0] === "$" ? 600 : 200); });
  addr.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && !go.disabled) { ev.preventDefault(); make(); } });
  detectEl.addEventListener("click", function (ev) { var b = ev.target.closest("button[data-coin]"); if (b) setCoin(b.dataset.coin); });
  document.querySelectorAll('input[name="t-keep"]').forEach(function (r) { r.addEventListener("change", function () { $("t-keep-note").textContent = KEEP_NOTE[keep()]; }); });
  if (navigator.clipboard && navigator.clipboard.readText) {
    $("t-paste").hidden = false;
    $("t-paste").addEventListener("click", function () {
      navigator.clipboard.readText().then(function (t) { addr.value = t.trim(); check(); }, function () { addr.focus(); });
    });
  }

  function keepText(d) {
    if (d.mode === "inuse") return "Kept while people use it. It's deleted after " + Math.round(d.inuse_days / 30) + " months without a visit, and each visit restarts the clock.";
    return "Deleted on " + T.fmtDate(d.expires) + ".";
  }

  function make() {
    if (go.disabled) return;
    err.textContent = "";
    var amount = $("t-amount").value.trim(), memo = $("t-memo").value.trim();
    if (amount && !/^\d+([.,]\d{1,8})?$/.test(amount)) { err.textContent = "The amount should be a number, like 5 or 0.25."; return; }
    go.disabled = true;
    var body = { coin: state.coin, keep: keep(), amount: amount.replace(",", "."), memo: memo };
    if (state.handle) body.handle = state.handle; else body.address = state.value;
    T.api("POST", "/links", body).then(function (r) {
      go.disabled = false;
      if (!r.ok) { err.textContent = r.data.error || "Something went wrong. Please try again."; return; }
      done(r.data, body);
    });
  }
  go.addEventListener("click", make);

  var last = null;
  function done(d, body) {
    last = d;
    $("t-make").hidden = true;
    var box = $("t-done");
    box.hidden = false;
    var short = d.link.replace(/^https?:\/\//, "");
    $("t-link").textContent = short; $("t-link").href = d.link; $("t-open").href = d.link;
    $("t-existing").hidden = !d.existing;
    $("t-done-keep").textContent = keepText(d);
    $("t-qr").innerHTML = T.qrSvg(d.link);
    $("t-share").hidden = !navigator.share;
    box.focus();
    remember(d, body);
    var key = d.owner_key || (mine().find(function (x) { return x.code === d.code; }) || {}).token || "";
    $("t-okey").hidden = !key;
    $("t-okey-val").textContent = key;
  }
  $("t-okey-copy").addEventListener("click", function () { var b = this; T.copy($("t-okey-val").textContent).then(function () { T.flash(b, "Copied ✓"); }); });
  $("t-okey-dl").addEventListener("click", function () { T.ownerCard(last.code, $("t-okey-val").textContent); });
  $("t-copy").addEventListener("click", function () { var b = this; T.copy(last.link).then(function (ok) { T.flash(b, ok ? "Copied ✓" : "Press and hold to copy"); }); });
  $("t-share").addEventListener("click", function () { navigator.share({ title: "My crypto address", url: last.link }).catch(function () {}); });
  $("t-qr-dl").addEventListener("click", function () {
    var c = document.createElement("canvas"); c.width = 900;
    T.download(T.drawQr(c, { text: last.link, caption: last.link.replace(/^https?:\/\//, "") }), "tinyada-" + last.code + ".png");
  });
  $("t-again").addEventListener("click", function () {
    $("t-done").hidden = true; $("t-make").hidden = false;
    addr.value = ""; $("t-amount").value = ""; $("t-memo").value = ""; check(); addr.focus();
  });

  /* ---------- "Your links on this device" (holds each link's owner key) ---------- */
  var KEY = "tiny-mine";
  function mine() { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { return []; } }
  function save(list) { try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, 100))); } catch (e) { /* private mode: fine */ } }
  function remember(d, body) {
    var list = mine().filter(function (x) { return x.code !== d.code; }), old = mine().find(function (x) { return x.code === d.code; });
    list.unshift({ code: d.code, token: d.delete_token || (old && old.token) || "", coin: body.coin, end: (body.handle || body.address).slice(-6), handle: body.handle || "",
                   mode: d.mode, expires: d.expires, amount: body.amount || "" });
    save(list); render();
  }
  function render() {
    var now = Date.now() / 1000, list = mine().filter(function (x) { return x.mode === "inuse" || x.expires > now; });
    save(list);
    $("t-mine-sec").hidden = !list.length;
    $("t-mine").innerHTML = list.map(function (x) {
      return '<li><span><a href="/' + T.esc(x.code) + '">tiny.gmcat.io/' + T.esc(x.code) + "</a> <small>" + T.esc(T.COINS[x.coin] ? T.COINS[x.coin].name : x.coin) + " · " +
        (x.handle ? T.esc(x.handle) : "…" + T.esc(x.end)) + (x.amount ? " · " + T.esc(x.amount) + " " + T.esc(T.COINS[x.coin].sym) : "") + " · " +
        (x.mode === "inuse" ? "kept while in use" : "until " + T.esc(T.fmtDate(x.expires))) + "</small></span>" +
        (x.token ? '<button class="linkbtn" type="button" data-del="' + T.esc(x.code) + '">Delete</button>' : "") + "</li>";
    }).join("");
  }
  $("t-mine").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-del]"); if (!b) return;
    var code = b.dataset.del, item = mine().find(function (x) { return x.code === code; });
    T.ask({ title: "Delete this link?", text: "tiny.gmcat.io/" + code + " will stop working for everyone, right away. This can't be undone.", ok: "Delete link", danger: true }).then(function (yes) {
      if (!yes) return;
      T.api("DELETE", "/l/" + code, undefined, { "X-Delete-Token": item.token }).then(function (r) {
        if (!r.ok && r.status !== 404) { T.tell({ title: "Couldn't delete it", text: r.data.error || "Please try again." }); return; }
        save(mine().filter(function (x) { return x.code !== code; })); render();
      });
    });
  });
  $("t-mine-clear").addEventListener("click", function () {
    T.ask({ title: "Forget the list?", text: "This browser forgets your links and their owner keys. The links keep working, but you won't be able to manage them from here unless you saved the owner cards.", ok: "Forget the list", danger: true })
      .then(function (yes) { if (yes) { save([]); render(); } });
  });
  render();

  /* ---------- TinyADA Plus card (switched in GmCat HQ) ---------- */
  T.api("GET", "/config").then(function (r) {
    if (!r.ok) return;
    var c = r.data;
    if (c.free === "off") {   // the Free tier is paused in GmCat HQ: existing links keep working
      var note = document.createElement("p");
      note.className = "t-banner warn"; note.id = "t-paused";
      note.textContent = "Making new links is paused for a little while. Links that already exist still work. Please check back soon.";
      $("t-make").insertBefore(note, $("t-make").firstChild);
      ["t-addr", "t-amount", "t-memo", "t-go", "t-paste"].forEach(function (id) { if ($(id)) $(id).disabled = true; });
    }
    if (c.privacy && c.privacy !== "off") $("t-faq-pp").hidden = false;
    if (c.premium === "on" || c.teaser) {
      $("t-plus-teaser").hidden = false;
      if (c.premium === "on") { $("t-plus-chip").textContent = "New"; $("t-plus-cta").hidden = false; }
    }
  });
  if (addr.value) check();
})();
