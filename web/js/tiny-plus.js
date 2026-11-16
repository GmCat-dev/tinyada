/* TinyADA Plus (tiny.gmcat.io/plus/): sign-in, your links and tip pages, Verified owner, custom names, $GMGM payments,
   QR studio, print sheets, stream overlay and visit counts. Whether any of this is open is decided in GmCat HQ. */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$;
  var cfg = null, me = null, editing = null, logoImg = null, payTimer = null;
  var hexOf = function (s) { return Array.from(new TextEncoder().encode(s), function (b) { return b.toString(16).padStart(2, "0"); }).join(""); };

  function status(html) { $("t-plus").innerHTML = '<div class="card t-state">' + html + "</div>"; $("t-plus").hidden = false; }

  Promise.all([T.api("GET", "/config"), T.api("GET", "/me")]).then(function (r) {
    cfg = r[0].data; me = r[1].data;
    if (!r[0].ok) return status("<p>TinyADA can't be reached right now. Please try again in a moment.</p>");
    if (cfg.premium === "off") return status('<h2 class="panel-h">TinyADA Plus isn\'t open yet</h2><p class="muted">Free tiny links work as always. <a href="/">Make one</a></p>');
    var m = location.hash.match(/signin-error=([a-z_]+)/);
    if (m) {
      history.replaceState(null, "", location.pathname);
      $("t-si-err").textContent = { cancelled: "Sign-in was cancelled.", expired: "That sign-in took too long. Please try again.", unreachable: "GmCat accounts can't be reached right now. Please try again soon.",
        off: "Signing in isn't open yet." }[m[1]] || "Sign-in didn't work. Please try again.";
    }
    if (me.signed_in) dash(); else signin();
  });

  /* ---------- sign-in (all methods go through account.gmcat.io) ---------- */
  function signin() {
    $("t-plus").hidden = true;
    $("t-signin").hidden = false;
    var on = cfg.sign_in || {};
    if (!on.gmcat) { ["t-si-gmcat", "t-si-email", "t-si-wallet"].forEach(function (id) { $(id).hidden = true; }); $("t-si-err").textContent = "Signing in isn't connected yet."; }
  }
  var pickWallet = T.pickWallet;
  $("t-si-wallet").addEventListener("click", function () {
    var err = $("t-si-err"); err.textContent = "";
    pickWallet().then(function (pick) {
      if (!pick) return;
      var api;
      return pick.w.enable().then(function (a) { api = a; return api.getRewardAddresses(); }).then(function (rew) {
        if (!rew || !rew.length) throw new Error("This wallet has no stake address to sign with.");
        return T.api("GET", "/wallet/challenge").then(function (r) {
          if (!r.ok) throw new Error(r.data.error);
          return api.signData(rew[0], hexOf(r.data.message)).then(function (sig) {
            return T.api("POST", "/wallet/verify", { nonce: r.data.nonce, address: rew[0], signature: sig.signature, key: sig.key, provider: pick.id });
          });
        });
      }).then(function (r) {
        if (!r.ok) throw new Error(r.data.error);
        location.reload();
      });
    }).catch(function (e) { err.textContent = (e && e.message && !/user|declin|cancel/i.test(e.message)) ? e.message : "The wallet didn't sign. Nothing was changed."; });
  });

  /* ---------- dashboard ---------- */
  function dash() {
    $("t-plus").hidden = true; $("t-signin").hidden = true; $("t-dash").hidden = false;
    $("t-acct-name").textContent = me.label ? me.label : me.via === "wallet" ? "Wallet sign-in" : "Your GmCat account";
    $("t-acct-plan").textContent = me.plus ? "TinyADA Plus until " + T.fmtDate(me.plus_until) : "Free (no Plus yet)";
    if (cfg.manage) $("t-acct-manage").href = cfg.manage;
    buyCard();
    var plus = me.plus;
    $("t-links-sec").hidden = !plus; $("t-names-sec").hidden = !plus; $("t-studio").hidden = !plus || !me.links.length;
    if (plus) { links(); names(); studio(); }
    if (me.open_quotes && me.open_quotes.length) pay(me.open_quotes[0]);
  }
  function reload() { return T.api("GET", "/me").then(function (r) { me = r.data; if (!me.signed_in) location.reload(); else dash(); }); }

  $("t-signout").addEventListener("click", function () {
    T.ask({ title: "Sign out of TinyADA?", html: '<p class="t-ask-text">You stay signed in to your GmCat account and other GmCat sites. To sign out everywhere, use your <a href="' + T.esc(cfg.manage || "https://account.gmcat.io/profile/") + '">GmCat account page</a>.</p>', ok: "Sign out" })
      .then(function (yes) { if (yes) T.api("DELETE", "/session").then(function () { location.reload(); }); });
  });

  function buyCard() {
    var box = $("t-buy"), p = cfg.prices || {}, days = me.plus ? Math.ceil((me.plus_until - Date.now() / 1000) / 86400) : 0;
    if (me.plus && days > 30 && !(me.open_quotes || []).length) { box.hidden = true; return; }
    box.hidden = false;
    var price = p.plus ? "$" + p.plus.toFixed(2) + " a year, paid in $GMGM" : "";
    if (me.plus) {
      box.innerHTML = '<h2 class="panel-h">Your Plus ends in ' + days + " day" + (days === 1 ? "" : "s") + "</h2>" +
        '<p class="muted">After that your links stay up while people use them (deleted after ' + Math.round(me.inuse_days / 30) + " months without a visit), and custom names are kept for " + me.name_grace_days + " more days.</p>" +
        (cfg.can_buy ? '<div class="tool-actions"><button class="btn primary" type="button" data-buy="plus">Add a year (' + T.esc(price) + ")</button></div>" : "");
    } else {
      box.innerHTML = '<h2 class="panel-h">TinyADA Plus</h2><ul class="t-plus-list">' +
        [["@", "Custom names", "tiny.gmcat.io/@yourname"], ["🫙", "Tip pages", "all your coins on one link, with a picture, bio and social links"], ["✓", "Verified owner", "a green tick once you sign with your wallet"],
         ["✏️", "Editable links", "visitors see when an address changed"], ["🎨", "QR studio", "your colours and logo, sticker and card sheets"], ["📈", "Visit counts", "per day, no personal tracking"],
         ["📺", "Stream overlay", "for OBS, Twitch and YouTube"], ["♾", "Permanent links", "kept while you have Plus"]]
          .map(function (f) { return '<li><span aria-hidden="true">' + f[0] + "</span><b>" + T.esc(f[1]) + "</b> " + T.esc(f[2]) + "</li>"; }).join("") + "</ul>" +
        (cfg.can_buy ? '<div class="tool-actions"><button class="btn primary" type="button" data-buy="plus">Get Plus: ' + T.esc(price) + "</button></div>" +
          '<p class="small-print muted">Paid once in $GMGM for a year. It never renews by itself.</p>'
          : '<p class="muted">' + (cfg.premium === "testing" ? "Plus is being tested and isn't on sale yet. Test accounts get Plus from GmCat." : "Plus isn't on sale yet. Check back soon.") + "</p>");
    }
  }
  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-buy]");
    if (!b) return;
    var body = { product: b.dataset.buy };
    if (b.dataset.name) body.name = b.dataset.name;
    b.disabled = true;
    T.api("POST", "/plus/buy", body).then(function (r) {
      b.disabled = false;
      if (!r.ok) return T.tell({ title: "Couldn't start the payment", text: r.data.error || "Please try again." });
      pay(r.data);
    });
  });

  function pay(q) {
    var box = $("t-buy"), what = q.product === "plus" ? "a year of TinyADA Plus" : "@" + q.name + " for a year";
    if (!q.options) q.options = [{ label: "$GMGM", amount: String(q.amount), address: q.address, discount: cfg.gmgm_discount || 0, note: "Send exactly this amount of $GMGM (a Cardano token). The exact amount is how we know it's you." }];
    box.hidden = false;
    box.innerHTML = '<h2 class="panel-h">Pay for ' + T.esc(what) + '</h2><div id="t-pay-box"></div>';
    if (payTimer) payTimer();
    payTimer = T.payPanel($("t-pay-box"), q, "/plus/buy/" + encodeURIComponent(q.id), function (st) { if (st === "paid" || st === "paid-check") reload(); });
  }

  /* ---------- your links ---------- */
  function links() {
    $("t-mylinks").innerHTML = me.links.length ? me.links.map(function (l) {
      var coins = l.items.map(function (it) { return T.COINS[it.coin] ? T.COINS[it.coin].sym : it.coin; }).join(" · ");
      var unverified = l.items.filter(function (it) { return it.coin === "ADA" && /^addr1/.test(it.address) && !it.verified; });
      return '<li class="t-mylink"><div><a class="t-ml-link" href="/' + T.esc(l.code) + '">tiny.gmcat.io/' + T.esc(l.code) + "</a>" +
        "<small>" + T.esc(l.title || "No title") + " · " + T.esc(coins) + " · " + l.visits + " visit" + (l.visits === 1 ? "" : "s") + (l.held ? " · hidden after reports" : "") +
        (l.mode !== "forever" ? " · kept while in use" : "") + "</small>" +
        '<svg class="t-spark" id="t-spark-' + T.esc(l.code) + '" viewBox="0 0 360 40" role="img" aria-label="Visits in the last 60 days"></svg></div>' +
        '<div class="t-ml-btns"><button class="btn" type="button" data-act="edit" data-code="' + T.esc(l.code) + '">Edit</button>' +
        unverified.map(function (it) { return '<button class="btn" type="button" data-act="verify" data-code="' + T.esc(l.code) + '" data-addr="' + T.esc(it.address) + '">Verify …' + T.esc(it.address.slice(-6)) + "</button>"; }).join("") +
        '<button class="btn" type="button" data-act="stats" data-code="' + T.esc(l.code) + '">Visits</button>' +
        '<button class="btn" type="button" data-act="copy" data-code="' + T.esc(l.code) + '">Copy link</button>' +
        '<button class="btn" type="button" data-act="del" data-code="' + T.esc(l.code) + '">Delete</button></div></li>';
    }).join("") : '<li class="muted">No links yet. Make your first one: a single address, or a tip page with all your coins.</li>';
    me.links.slice(0, 30).forEach(function (l) {
      T.api("GET", "/plus/links/" + encodeURIComponent(l.code) + "/stats").then(function (r) { if (r.ok) spark($("t-spark-" + l.code), r.data.days); });
    });
  }
  function spark(svg, days) {
    if (!svg) return;
    var max = Math.max(1, Math.max.apply(null, days.map(function (d) { return d.n; }))), w = 360 / days.length;
    svg.innerHTML = days.map(function (d, i) {
      var h = Math.max(d.n ? 3 : 0, Math.round(36 * d.n / max));
      return h ? '<rect x="' + (i * w + 1).toFixed(1) + '" y="' + (38 - h) + '" width="' + Math.max(1, w - 2).toFixed(1) + '" height="' + h + '" rx="1.5" fill="var(--orange)"></rect>' : "";
    }).join("") + '<line x1="0" x2="360" y1="38.5" y2="38.5" stroke="var(--line)"></line>';
  }
  $("t-mylinks").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-act]"); if (!b) return;
    var code = b.dataset.code, l = me.links.find(function (x) { return x.code === code; });
    if (b.dataset.act === "edit") return openEditor(l);
    if (b.dataset.act === "copy") return T.copy(l.link).then(function () { T.flash(b, "Copied ✓"); });
    if (b.dataset.act === "stats") return stats(code);
    if (b.dataset.act === "verify") return verify(code, b.dataset.addr);
    if (b.dataset.act === "del") {
      T.ask({ title: "Delete tiny.gmcat.io/" + code + "?", text: "The link stops working for everyone right away." + (code[0] === "@" ? " You keep the name and can make a new page with it." : "") + " This can't be undone.", ok: "Delete", danger: true })
        .then(function (yes) { if (yes) T.api("DELETE", "/plus/links/" + encodeURIComponent(code)).then(reload); });
    }
  });

  /* Visits chart: one series, thin bars anchored to the baseline with rounded tops, hover tooltips, a table for screen readers. */
  function stats(code) {
    var dlg = $("t-stats-dlg"), body = $("t-stats-body");
    $("t-stats-h").textContent = "Visits to tiny.gmcat.io/" + code;
    body.innerHTML = '<p class="muted">Loading…</p>';
    dlg.showModal();
    T.api("GET", "/plus/links/" + encodeURIComponent(code) + "/stats").then(function (r) {
      if (!r.ok) { body.innerHTML = '<p class="t-err">' + T.esc(r.data.error) + "</p>"; return; }
      T.visitsChart(body, r.data);
    });
  }

  /* Verified owner: the wallet holding the address signs a message with that address (CIP-30 signData). */
  function verify(code, address) {
    T.api("POST", "/plus/verify/challenge", { code: code, address: address }).then(function (r) {
      if (!r.ok) return T.tell({ title: "Can't verify this one", text: r.data.error });
      var ch = r.data;
      T.ask({ title: "Verify …" + address.slice(-6), text: "Your wallet will ask you to sign a short message with this address. It's not a transaction: nothing is sent and it costs nothing.", ok: "Open my wallet" }).then(function (yes) {
        if (!yes) return;
        pickWallet().then(function (pick) {
          if (!pick) return;
          pick.w.enable().then(function (api) { return api.signData(ch.address_hex, hexOf(ch.message)); })
            .then(function (sig) { return T.api("POST", "/plus/verify", { nonce: ch.nonce, signature: sig.signature, key: sig.key }); })
            .then(function (r2) {
              if (!r2.ok) return T.tell({ title: "Not verified", text: r2.data.error });
              T.tell({ title: "Verified ✓", text: "Visitors now see a green tick next to …" + address.slice(-6) + "." }).then(reload);
            }).catch(function (e) {
              T.tell({ title: "Not verified", text: e && e.code === 3 || /account|address/i.test(e && e.info || "") ? "This wallet doesn't hold that address. Switch to the wallet (and account) that does, then try again." : "The wallet didn't sign. Nothing was changed." });
            });
        });
      });
    });
  }

  /* ---------- editor (shared with Privacy Plus: tiny-editor.js) ---------- */
  var ed = null;
  function openEditor(l) {
    editing = l || null;
    if (!ed) ed = T.editor($("t-ed-box"), { avatars: cfg.avatars, maxItems: cfg.max_items, names: true });
    $("t-ed-h").textContent = l ? "Edit tiny.gmcat.io/" + l.code : "New link or tip page";
    ed.set(l, me.names.filter(function (n) { return !n.used; }).map(function (n) { return n.name; }));
    $("t-ed-err").textContent = "";
    $("t-editor").hidden = false;
    $("t-editor").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  $("t-new").addEventListener("click", function () { openEditor(null); });
  $("t-ed-cancel").addEventListener("click", function () { $("t-editor").hidden = true; });
  $("t-ed-save").addEventListener("click", function () {
    var err = $("t-ed-err"), body = ed.get(); err.textContent = "";
    if (!body.items.length) { err.textContent = "Add at least one address."; return; }
    var go = function () {
      $("t-ed-save").disabled = true;
      (editing ? T.api("PUT", "/plus/links/" + encodeURIComponent(editing.code), body) : T.api("POST", "/plus/links", Object.assign({ name: ed.nameValue() }, body))).then(function (r) {
        $("t-ed-save").disabled = false;
        if (!r.ok) { err.textContent = r.data.error || "Couldn't save. Please try again."; return; }
        $("t-editor").hidden = true;
        reload();
      });
    };
    if (editing && T.removesAddress(editing, body)) {
      return T.ask({ title: "Change an address?", text: "Visitors will see a notice for 30 days that an address on this page changed (with the old ending), so nobody is caught out. A Verified tick on a removed address goes away.", ok: "Save the change" })
        .then(function (yes) { if (yes) go(); });
    }
    go();
  });

  /* ---------- custom names ---------- */
  function names() {
    var p = cfg.prices || {}, now = Date.now() / 1000;
    $("t-names").innerHTML = me.names.map(function (n) {
      var lapsed = n.until < now;
      return "<li><span><b>@" + T.esc(n.name) + "</b> <small class=\"muted\">" + (lapsed ? "ended " + T.fmtDate(n.until) + " · removed on " + T.fmtDate(n.grace_until) : "until " + T.fmtDate(n.until)) + (n.used ? " · has a page" : " · no page yet") + "</small></span>" +
        (cfg.can_buy ? '<button class="btn" type="button" data-buy="name" data-name="' + T.esc(n.name) + '">Renew a year</button>' : "") + "</li>";
    }).join("");
    $("t-names").hidden = !me.names.length;
    void p;
  }
  function priceFor(name) { var p = cfg.prices || {}; return name.length === 3 ? p.name3 : name.length === 4 ? p.name4 : p.name5; }
  $("t-name-check").addEventListener("click", checkName);
  $("t-name-q").addEventListener("keydown", function (ev) { if (ev.key === "Enter") checkName(); });
  function checkName() {
    var q = $("t-name-q").value.trim().toLowerCase().replace(/^@/, ""), res = $("t-name-res");
    if (!q) return;
    T.api("GET", "/plus/names/check?name=" + encodeURIComponent(q)).then(function (r) {
      if (!r.ok) { res.innerHTML = '<span class="t-bad">' + T.esc(r.data.error) + "</span>"; return; }
      if (!r.data.available) { res.innerHTML = '<span class="t-bad">' + T.esc(r.data.reason) + "</span>"; return; }
      var usd = r.data.usd || priceFor(q);
      res.innerHTML = '<span class="t-ok">✓ @' + T.esc(q) + " is free.</span> " + (cfg.can_buy && usd ? '<button class="btn primary" type="button" data-buy="name" data-name="' + T.esc(q) + '">Get it: $' + usd.toFixed(2) + " a year in $GMGM</button>" :
        '<span class="muted">Names can\'t be bought yet.</span>');
    });
  }

  /* ---------- QR studio, print sheets, overlay ---------- */
  function studio() {
    var sel = $("t-st-link");
    sel.innerHTML = me.links.map(function (l) { return '<option value="' + T.esc(l.code) + '">tiny.gmcat.io/' + T.esc(l.code) + (l.title ? " · " + T.esc(l.title) : "") + "</option>"; }).join("");
    draw();
  }
  function curLink() { var code = $("t-st-link").value; return me.links.find(function (l) { return l.code === code; }); }
  function draw() {
    var l = curLink(); if (!l) return;
    T.drawQr($("t-st-canvas"), { text: l.link, fg: $("t-st-fg").value, bg: $("t-st-bg").value, logo: logoImg, caption: $("t-st-text").checked ? l.link.replace(/^https?:\/\//, "") : "" });
    $("t-st-ov").value = l.link + "/overlay";
  }
  ["t-st-link", "t-st-fg", "t-st-bg", "t-st-text"].forEach(function (id) { $(id).addEventListener("input", draw); });
  $("t-st-logo").addEventListener("change", function () {
    var f = this.files[0];
    if (!f) { logoImg = null; return draw(); }
    var img = new Image();
    img.onload = function () { logoImg = img; draw(); };
    img.src = URL.createObjectURL(f);   // read on this device only; never uploaded
  });
  $("t-st-dl").addEventListener("click", function () { T.download($("t-st-canvas"), "tinyada-" + curLink().code.replace("@", "") + ".png"); });
  $("t-st-ov-copy").addEventListener("click", function () { var b = this; T.copy($("t-st-ov").value).then(function () { T.flash(b, "Copied ✓"); }); });
  function card(l) {
    var c = document.createElement("canvas"); c.width = 1050; c.height = 600;
    var x = c.getContext("2d"), q = document.createElement("canvas"); q.width = 520;
    T.drawQr(q, { text: l.link, fg: $("t-st-fg").value, bg: $("t-st-bg").value, logo: logoImg });
    x.fillStyle = $("t-st-bg").value; x.fillRect(0, 0, 1050, 600);
    x.drawImage(q, 40, 40, 520, 520);
    x.fillStyle = $("t-st-fg").value; x.textBaseline = "top";
    x.font = "800 52px 'DM Sans', system-ui, sans-serif"; wrapText(x, l.title || "Tip me in crypto", 600, 150, 410, 60);
    x.font = "700 30px 'DM Sans', system-ui, sans-serif"; x.fillText(l.link.replace(/^https?:\/\//, ""), 600, 400);
    x.globalAlpha = .6; x.font = "600 24px 'DM Sans', system-ui, sans-serif"; x.fillText("Scan to pay · //TinyADA", 600, 450); x.globalAlpha = 1;
    return c;
  }
  function wrapText(x, text, left, top, width, lh) {
    var words = text.split(" "), line = "", y = top;
    words.forEach(function (w) { var t = line ? line + " " + w : w; if (x.measureText(t).width > width && line) { x.fillText(line, left, y); y += lh; line = w; } else line = t; });
    x.fillText(line, left, y);
  }
  function printSheet(kind) {
    var l = curLink(), box = $("t-print"), src = kind === "stickers" ? $("t-st-canvas").toDataURL("image/png") : card(l).toDataURL("image/png"), n = kind === "stickers" ? 12 : 10;
    box.className = "t-print " + kind;
    box.innerHTML = new Array(n).fill('<img alt="" src="' + src + '">').join("");
    document.body.classList.add("t-printing");
    var done = function () { document.body.classList.remove("t-printing"); box.innerHTML = ""; window.removeEventListener("afterprint", done); };
    window.addEventListener("afterprint", done);
    setTimeout(function () { window.print(); }, 50);
  }
  $("t-st-print-s").addEventListener("click", function () { printSheet("stickers"); });
  $("t-st-print-c").addEventListener("click", function () { printSheet("cards"); });
})();
