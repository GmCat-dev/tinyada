/* TinyADA link page, part 2: sharing, Privacy Plus upgrades (no account), and the owner's tools.
   tiny-view.js fires "tiny:loaded" with the link once it's shown. The owner key lives in this browser ("tiny-mine"). */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$, link = null, up = null, ed = null, stopPay = null;

  document.addEventListener("tiny:loaded", function (ev) {
    link = ev.detail;
    share();
    kept();
    owner();
    upgrades();
  });

  /* ---------- Share this page (its own QR: opens the page, it isn't for paying) ---------- */
  function share() {
    $("t-share-btn").hidden = false;
    $("t-share-btn").onclick = function () {
      $("t-share-qr").innerHTML = T.qrSvg(link.link);
      $("t-share-link").textContent = link.link.replace(/^https?:\/\//, "");
      $("t-share-native").hidden = !navigator.share;
      $("t-share-dlg").showModal();
    };
    $("t-share-copy").onclick = function () { var b = this; T.copy(link.link).then(function () { T.flash(b, "Copied ✓"); }); };
    $("t-share-native").onclick = function () { navigator.share({ title: document.title, url: link.link }).catch(function () {}); };
    $("t-share-dl").onclick = function () {
      var c = document.createElement("canvas"); c.width = 900;
      T.download(T.drawQr(c, { text: link.link, caption: link.link.replace(/^https?:\/\//, "") }), "tinyada-" + link.code.replace("@", "") + "-share.png");
    };
    $("t-share-dlg").addEventListener("click", function (ev) { if (ev.target === this) this.close(); });
  }

  function kept() {
    var p = $("t-kept"), bits = [];
    if (link.kept_until) bits.push("Kept up until " + T.fmtDate(link.kept_until));
    if (link.supporters) bits.push("thanks to " + link.supporters + " supporter" + (link.supporters === 1 ? "" : "s") + " 🧡");
    p.hidden = !bits.length;
    p.textContent = bits.join(", ");
  }

  /* ---------- owner key in this browser ---------- */
  function store() { try { return JSON.parse(localStorage.getItem("tiny-mine") || "[]"); } catch (e) { return []; } }
  T.ownerKey = function (code) { var x = store().find(function (i) { return i.code === code; }); return x ? x.token : ""; };
  function saveKey(code, key) {
    var list = store().filter(function (x) { return x.code !== code; });
    var it = link.items[0];
    list.unshift({ code: code, token: key, coin: it.coin, end: it.address.slice(-6), handle: it.handle || "", mode: link.mode, expires: link.expires, amount: it.amount || "" });
    try { localStorage.setItem("tiny-mine", JSON.stringify(list.slice(0, 100))); } catch (e) { /* private mode */ }
  }
  function keyHdr() { var k = T.ownerKey(link.code); return k ? { "X-Owner-Key": k } : {}; }

  /* ---------- the owner's tools ---------- */
  function owner() {
    var box = $("t-owner");
    if (!link.owner || link.plus) { box.hidden = true; $("t-iown").hidden = !!link.plus; return; }
    $("t-iown").hidden = true;
    var f = link.features || {}, now = Date.now() / 1000;
    box.hidden = false;
    box.innerHTML = '<p class="t-owner-h"><b>🔑 You own this link</b> <span class="muted">(this browser has its owner key)</span></p><div class="t-item-btns">' +
      (link.page ? '<button class="btn" type="button" data-own="edit">Edit page</button>' : "") +
      ((f.stats || 0) > now ? '<button class="btn" type="button" data-own="stats">Visits</button>' : "") +
      '<button class="btn" type="button" data-own="card">Download owner card</button><button class="btn" type="button" data-own="rekey">New owner key</button>' +
      '<button class="btn" type="button" data-own="delete">Delete link</button></div>' +
      ((link.names || []).length ? '<p class="small-print muted">Also opens at ' + link.names.map(function (n) { return "<b>tiny.gmcat.io/@" + T.esc(n.name) + "</b> (until " + T.fmtDate(n.until) + ")"; }).join(", ") + "</p>" : "") +
      '<p class="small-print muted" id="t-own-hint" hidden>Want to edit it, add more coins, a picture or a bio? That\'s the <b>Tip page</b> upgrade below.</p>';
    box.onclick = function (ev) {
      var b = ev.target.closest("[data-own]"); if (!b) return;
      var act = b.dataset.own;
      if (act === "card") return T.ownerCard(link.code, T.ownerKey(link.code));
      if (act === "edit") return edit();
      if (act === "stats") return stats();
      if (act === "rekey") return T.ask({ title: "Make a new owner key?", text: "The old key stops working everywhere, including on other devices. Download the new owner card afterwards.", ok: "New key" }).then(function (y) {
        if (!y) return;
        T.api("POST", "/l/" + encodeURIComponent(link.code) + "/rekey", {}, keyHdr()).then(function (r) {
          if (!r.ok) return T.tell({ title: "Couldn't do that", text: r.data.error });
          saveKey(link.code, r.data.owner_key);
          T.ask({ title: "New owner key saved", text: "Saved in this browser. Download the owner card to keep a copy somewhere safe.", ok: "Download owner card", cancel: "Later" }).then(function (d) { if (d) T.ownerCard(link.code, r.data.owner_key); });
        });
      });
      if (act === "delete") return T.ask({ title: "Delete this link?", text: "It stops working for everyone right away, with any upgrades and custom names. This can't be undone.", ok: "Delete link", danger: true }).then(function (y) {
        if (!y) return;
        T.api("DELETE", "/l/" + encodeURIComponent(link.code), undefined, keyHdr()).then(function (r) {
          if (!r.ok) return T.tell({ title: "Couldn't delete it", text: r.data.error });
          location.href = "/";
        });
      });
    };
  }

  function edit() {
    T.api("GET", "/config").then(function (r) {
      if (!ed) ed = T.editor($("t-ed-box"), { avatars: r.data.avatars || [], maxItems: r.data.max_items || 8, names: false });
      ed.set(link);
      $("t-ed-err").textContent = "";
      $("t-ed-dlg").showModal();
    });
  }
  $("t-ed-cancel").addEventListener("click", function () { $("t-ed-dlg").close(); });
  $("t-ed-save").addEventListener("click", function () {
    var body = ed.get(), err = $("t-ed-err"); err.textContent = "";
    if (!body.items.length) { err.textContent = "Add at least one address."; return; }
    var go = function () {
      T.api("PUT", "/l/" + encodeURIComponent(link.code), body, keyHdr()).then(function (r) {
        if (!r.ok) { err.textContent = r.data.error || "Couldn't save. Please try again."; return; }
        location.reload();
      });
    };
    if (T.removesAddress(link, body)) return T.ask({ title: "Change an address?", text: "Visitors will see a notice for 30 days that an address changed (with the old ending), so nobody is caught out.", ok: "Save the change" }).then(function (y) { if (y) go(); });
    go();
  });

  function stats() {
    var dlg = $("t-stats-dlg"), body = $("t-stats-body");
    body.innerHTML = '<p class="muted">Loading…</p>';
    dlg.showModal();
    T.api("GET", "/l/" + encodeURIComponent(link.code) + "/stats", undefined, keyHdr()).then(function (r) {
      if (!r.ok) { body.innerHTML = '<p class="t-err">' + T.esc(r.data.error) + "</p>"; return; }
      T.visitsChart(body, r.data);
    });
  }

  /* ---------- "I own this link": paste the owner key, or prove it with the wallet (the wallet always wins) ---------- */
  $("t-iown").addEventListener("click", function () {
    var claim = (up && up.claimable) || [];
    var d = $("t-iown-dlg");
    $("t-iown-msg").textContent = "";
    $("t-iown-wallets").innerHTML = claim.map(function (a) {
      var sol = !/^addr1/.test(a);
      return '<button class="btn" type="button" data-claim="' + T.esc(a) + '">Sign with the ' + (sol ? "Solana" : "Cardano") + " wallet holding …" + T.esc(a.slice(-6)) + "</button>";
    }).join("");
    $("t-iown-wsec").hidden = !claim.length;
    d.showModal();
  });
  $("t-iown-dlg").addEventListener("click", function (ev) { if (ev.target === this) this.close(); });
  $("t-iown-go").addEventListener("click", function () {
    var key = $("t-iown-key").value.trim(), msg = $("t-iown-msg");
    if (!key) { msg.textContent = "Paste the owner key first."; return; }
    T.api("GET", "/l/" + encodeURIComponent(link.code) + "/upgrades", undefined, { "X-Owner-Key": key }).then(function (r) {
      if (!r.ok || !r.data.owner) { msg.textContent = "That key doesn't match this link."; return; }
      saveKey(link.code, key);
      location.reload();
    });
  });
  $("t-iown-wallets").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-claim]"); if (!b) return;
    var addr = b.dataset.claim, msg = $("t-iown-msg");
    msg.textContent = "";
    T.api("POST", "/l/" + encodeURIComponent(link.code) + "/claim/challenge", { address: addr }).then(function (r) {
      if (!r.ok) { msg.textContent = r.data.error; return; }
      var ch = r.data, hex = function (bytes) { return Array.from(bytes, function (x) { return x.toString(16).padStart(2, "0"); }).join(""); };
      var signing = ch.kind === "solana" ? (function () {
        var w = T.solanaWallet();
        if (!w) return Promise.reject(new Error("No Solana wallet found in this browser (Phantom, Solflare or Backpack)."));
        return Promise.resolve(w.connect ? w.connect() : null).then(function () { return w.signMessage(new TextEncoder().encode(ch.message), "utf8"); })
          .then(function (res) { return { signature: hex(res.signature || res) }; });
      })() : T.pickWallet().then(function (pick) {
        if (!pick) throw new Error("");
        return pick.w.enable().then(function (api) { return api.signData(ch.address_hex, hex(new TextEncoder().encode(ch.message))); });
      });
      signing.then(function (sig) {
        return T.api("POST", "/l/" + encodeURIComponent(link.code) + "/claim", { nonce: ch.nonce, signature: sig.signature, key: sig.key });
      }).then(function (r2) {
        if (!r2.ok) { msg.textContent = r2.data.error; return; }
        saveKey(link.code, r2.data.owner_key);
        $("t-iown-dlg").close();
        T.ask({ title: "This link is yours ✓", text: "Your wallet proved it, so the address now has a Verified tick and this browser has a fresh owner key (any older key stopped working).", ok: "Download owner card", cancel: "Later" })
          .then(function (d) { if (d) T.ownerCard(link.code, r2.data.owner_key); location.reload(); });
      }).catch(function (e) { msg.textContent = e && e.message ? e.message : "The wallet didn't sign. Nothing was changed."; });
    });
  });

  /* ---------- Privacy Plus: upgrade this link ---------- */
  function upgrades() {
    T.api("GET", "/l/" + encodeURIComponent(link.code) + "/upgrades", undefined, keyHdr()).then(function (r) {
      if (!r.ok || !r.data.open) return;
      up = r.data;
      if ($("t-own-hint") && !link.page) $("t-own-hint").hidden = false;   // only when upgrades are actually offered
      var box = $("t-upgrade");
      box.hidden = false;
      var price = function (u) { return u.usd ? "$" + u.usd.toFixed(2) + " a year" : "Not on sale yet"; };
      $("t-up-body").innerHTML = '<p class="small-print muted">No account needed. ' + (up.can_buy ? "Pay with $GMGM and save " + up.discount + "%. More coins are coming." : "Upgrades aren't on sale yet.") + "</p>" +
        up.upgrades.map(function (u) {
          var locked = u.owner_only && !up.owner, active = u.until ? '<span class="chip live">On until ' + T.fmtDate(u.until) + "</span>" : "";
          var nameField = u.id === "name" && up.owner ? '<div class="t-input-row t-up-name"><span class="t-name-pre">@</span><input data-up-name maxlength="20" placeholder="yourname" autocapitalize="off" spellcheck="false" aria-label="Custom name"><button class="btn" type="button" data-up-check>Check</button></div><p class="small-print" data-up-name-res></p>' : "";
          var namePrices = [up.name_prices["5"], up.name_prices["4"], up.name_prices["3"]].filter(function (x) { return x > 0; });
          var priceTxt = u.id === "name" ? (namePrices.length ? "From $" + Math.min.apply(null, namePrices).toFixed(2) + " a year" : "Not on sale yet") : price(u);
          return '<div class="t-up" data-up="' + u.id + '"><div class="t-up-top"><b>' + T.esc(u.label) + "</b> " + active + '<span class="muted">' + T.esc(priceTxt) + "</span></div>" +
            '<p class="muted">' + T.esc(u.about) + "</p>" + nameField +
            (locked ? '<p class="small-print muted">Only the link\'s owner can buy this. <button class="linkbtn" type="button" data-up-iown>I own this link</button></p>' :
              (up.can_buy && (u.usd || u.id === "name") ? '<button class="btn' + (u.id === "keep" ? " primary" : "") + '" type="button" data-up-pay="' + u.id + '"' + (u.id === "name" ? " disabled" : "") + ">" + (u.until ? "Add a year" : u.id === "keep" ? "Keep this link alive" : "Get it") + "</button>" : "")) + "</div>";
        }).join("") + '<div id="t-up-pay"></div>';
    });
  }
  $("t-up-body").addEventListener("click", function (ev) {
    var t = ev.target;
    if (t.closest("[data-up-iown]")) return $("t-iown").click();
    var chk = t.closest("[data-up-check]");
    if (chk) {
      var row = chk.closest(".t-up"), name = row.querySelector("[data-up-name]").value.trim().toLowerCase(), res = row.querySelector("[data-up-name-res]"), pay = row.querySelector("[data-up-pay]");
      return T.api("GET", "/l/" + encodeURIComponent(link.code) + "/name-check?name=" + encodeURIComponent(name), undefined, keyHdr()).then(function (r) {
        var ok = r.ok && r.data.available;
        res.innerHTML = ok ? '<span class="t-ok">✓ @' + T.esc(name) + " is free: $" + r.data.usd.toFixed(2) + " a year.</span>" : '<span class="t-bad">' + T.esc(r.ok ? r.data.reason : r.data.error) + "</span>";
        if (pay) { pay.disabled = !ok || !r.data.usd; pay.dataset.name = ok ? name : ""; }
      });
    }
    var b = t.closest("[data-up-pay]");
    if (!b) return;
    var body = { upgrade: b.dataset.upPay };
    if (b.dataset.name) body.name = b.dataset.name;
    b.disabled = true;
    T.api("POST", "/l/" + encodeURIComponent(link.code) + "/upgrade", body, keyHdr()).then(function (r) {
      b.disabled = false;
      if (!r.ok) return T.tell({ title: "Couldn't start the payment", text: r.data.error || "Please try again." });
      var box = $("t-up-pay");
      box.innerHTML = '<h3 class="panel-h">Pay for: ' + T.esc(r.data.upgrade === "name" ? "@" + r.data.name : (up.upgrades.find(function (u) { return u.id === r.data.upgrade; }) || {}).label) + '</h3><div id="t-up-pay-box"></div>';
      if (stopPay) stopPay();
      stopPay = T.payPanel($("t-up-pay-box"), r.data, "/orders/" + encodeURIComponent(r.data.id), function (st) { if (st === "paid" || st === "paid-check") location.reload(); });
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
})();
