/* TinyADA shared pieces for editing a link (TinyADA Plus and Privacy Plus use the same editor and the same visits chart). */
(function () {
  "use strict";
  var T = window.Tiny;

  /* T.editor(box, {avatars, maxItems, names: [..] | null}) -> {set(link | null), get() -> request body, nameValue()} */
  T.editor = function (box, opt) {
    box.innerHTML =
      (opt.names ? '<label><span class="field-label">Address of the page</span><select class="e-name"></select></label>' : "") +
      '<label><span class="field-label">Title <small>(optional)</small></span><input class="e-title" maxlength="60" placeholder="e.g. GmCat’s tip jar"></label>' +
      '<label><span class="field-label">Short bio <small>(optional)</small></span><textarea class="e-bio" rows="2" maxlength="280" placeholder="e.g. Pixel art and cozy games. Thanks for the coffee!"></textarea></label>' +
      '<span class="field-label">Picture</span><div class="t-avatar-pick e-avatar"></div>' +
      '<span class="field-label">Addresses</span><ol class="t-ed-items e-items"></ol><button class="btn" type="button" data-e-add>Add another coin</button>' +
      '<span class="field-label t-gap">Social links <small>(optional, up to 5)</small></span><div class="t-ed-socials e-socials"></div>';
    var $ = function (s) { return box.querySelector(s); };

    function avatarPick(cur) {
      var e0 = cur ? cur.e : "", c0 = cur ? cur.c : 0, pick = $(".e-avatar");
      pick.innerHTML = '<button type="button" data-e="" aria-pressed="' + !e0 + '" aria-label="No picture (coin badge)">∅</button>' +
        (opt.avatars || []).map(function (e) { return '<button type="button" data-e="' + e + '" aria-pressed="' + (e === e0) + '">' + e + "</button>"; }).join("") +
        [0, 1, 2, 3, 4, 5, 6, 7].map(function (c) { return '<button type="button" class="t-swatch t-av-' + c + '" data-c="' + c + '" aria-label="Colour ' + (c + 1) + '" aria-pressed="' + (c === c0) + '"></button>'; }).join("");
      pick.onclick = function (ev) {
        var b = ev.target.closest("button"); if (!b) return;
        var attr = b.dataset.c !== undefined ? "data-c" : "data-e";
        pick.querySelectorAll("button[" + attr + "]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      };
    }
    function addItem(it) {
      var li = document.createElement("li");
      li.className = "t-ed-item";
      li.innerHTML = '<label class="t-ed-addr"><span class="field-label">Address or $handle</span><input class="i-addr" autocomplete="off" spellcheck="false" autocapitalize="off" value="' + T.esc(it.handle || it.address || "") + '"></label>' +
        '<label><span class="field-label">Coin</span><select class="i-coin">' + T.ORDER.map(function (c) { return '<option value="' + c + '"' + (it.coin === c ? " selected" : "") + ">" + T.COINS[c].sym + "</option>"; }).join("") + "</select></label>" +
        '<label><span class="field-label">Amount</span><input class="i-amount" inputmode="decimal" placeholder="any" value="' + T.esc(it.amount || "") + '"></label>' +
        '<button class="btn" type="button" aria-label="Remove this address">✕</button>' +
        '<label class="t-ed-memo"><span class="field-label">Note</span><input class="i-memo" maxlength="80" value="' + T.esc(it.memo || "") + '"></label>' +
        '<label class="t-ed-label"><span class="field-label">Tab name</span><input class="i-label" maxlength="40" placeholder="e.g. Tips" value="' + T.esc(it.label || "") + '"></label>' +
        '<div class="t-ed-detect" aria-live="polite"></div>';
      $(".e-items").appendChild(li);
      var inp = li.querySelector(".i-addr"), det = li.querySelector(".t-ed-detect"), coin = li.querySelector(".i-coin");
      function look() {
        var v = inp.value.trim();
        if (!v) { det.innerHTML = ""; return; }
        if (v[0] === "$") { coin.value = "ADA"; det.innerHTML = T.isHandle(v) ? '<span class="muted">Cardano $handle (checked when you save)</span>' : '<span class="t-bad">That doesn\'t look like a $handle.</span>'; return; }
        var c = T.detect(v);
        if (c.length) { if (c.indexOf(coin.value) < 0) coin.value = c[0]; det.innerHTML = '<span class="t-ok">✓ ' + T.esc(T.COINS[coin.value].name) + "</span>"; }
        else det.innerHTML = '<span class="t-bad">' + T.esc(T.why(v)) + "</span>";
      }
      inp.addEventListener("input", look);
      li.querySelector("button").addEventListener("click", function () { if ($(".e-items").children.length > 1) li.remove(); });
      if (it.address) look();
    }
    box.querySelector("[data-e-add]").addEventListener("click", function () { if ($(".e-items").children.length < (opt.maxItems || 8)) addItem({}); });

    return {
      set: function (l, names) {
        if (opt.names) {
          var sel = $(".e-name");
          if (l) { sel.innerHTML = "<option>tiny.gmcat.io/" + T.esc(l.code) + "</option>"; sel.disabled = true; }
          else {
            sel.disabled = false;
            sel.innerHTML = '<option value="">tiny.gmcat.io/ + random letters</option>' + (names || []).map(function (n) { return '<option value="' + T.esc(n) + '">tiny.gmcat.io/@' + T.esc(n) + "</option>"; }).join("");
          }
        }
        $(".e-title").value = l ? l.title || "" : ""; $(".e-bio").value = l ? l.bio || "" : "";
        avatarPick(l && l.avatar);
        $(".e-items").innerHTML = "";
        (l ? l.items : [{}]).forEach(addItem);
        var soc = (l && l.socials) || [];
        $(".e-socials").innerHTML = [0, 1, 2, 3, 4].map(function (i) { return '<input type="url" inputmode="url" placeholder="https://x.com/yourname" aria-label="Social link ' + (i + 1) + '" value="' + T.esc(soc[i] ? soc[i].url : "") + '">'; }).join("");
      },
      nameValue: function () { return opt.names ? $(".e-name").value : ""; },
      get: function () {
        var items = Array.from($(".e-items").children).map(function (li) {
          var v = li.querySelector(".i-addr").value.trim(), o = { coin: li.querySelector(".i-coin").value, amount: li.querySelector(".i-amount").value.trim(), memo: li.querySelector(".i-memo").value.trim(), label: li.querySelector(".i-label").value.trim() };
          if (v[0] === "$") o.handle = v; else o.address = v;
          return o;
        }).filter(function (o) { return o.address || o.handle; });
        var e = $(".e-avatar").querySelector('button[data-e][aria-pressed="true"]'), c = $(".e-avatar").querySelector('button[data-c][aria-pressed="true"]');
        return { items: items, title: $(".e-title").value, bio: $(".e-bio").value, avatar: e && e.dataset.e ? { e: e.dataset.e, c: c ? +c.dataset.c : 0 } : null,
                 socials: Array.from($(".e-socials").querySelectorAll("input")).map(function (i) { return { url: i.value.trim() }; }).filter(function (s) { return s.url; }) };
      }
    };
  };
  /* Pick a Cardano browser wallet (CIP-30). Resolves {id, w} or null. */
  function cardanoWallets() {
    var c = window.cardano || {}, out = [];
    Object.keys(c).forEach(function (k) { var w = c[k]; if (w && typeof w.enable === "function" && w.name && !out.some(function (o) { return o.w === w; })) out.push({ id: k, w: w }); });
    return out;
  }
  T.pickWallet = function () {
    return new Promise(function (resolve) {
      var list = cardanoWallets();
      if (!list.length) { T.tell({ title: "No Cardano wallet found", html: '<p class="t-ask-text">Install a browser wallet like Lace, Eternl or VESPR, then reload this page. <a href="https://wallets.gmcat.io/">Help me pick one</a></p>' }).then(function () { resolve(null); }); return; }
      if (list.length === 1) return resolve(list[0]);
      var d = document.createElement("dialog");
      d.className = "t-dlg card";
      d.innerHTML = '<h2 class="panel-h">Choose your wallet</h2><div class="t-wallets">' + list.map(function (x, i) { return '<button class="btn" type="button" data-i="' + i + '">' + T.esc(x.w.name) + "</button>"; }).join("") +
        '</div><div class="tool-actions"><button class="btn" type="button" data-i="-1">Cancel</button></div>';
      document.body.appendChild(d);
      d.addEventListener("click", function (ev) { var b = ev.target.closest("[data-i]"); if (b || ev.target === d) { var i = b ? +b.dataset.i : -1; d.close(); d.remove(); resolve(i >= 0 ? list[i] : null); } });
      d.addEventListener("cancel", function () { d.remove(); resolve(null); });
      d.showModal();
    });
  };

  /* Solana: Phantom / Solflare / Backpack style provider, or null */
  T.solanaWallet = function () { var w = window.phantom && window.phantom.solana || window.solflare || window.backpack || window.solana; return w && w.signMessage ? w : null; };

  /* The owner card: a small text file with the link and its owner key */
  T.ownerCard = function (code, key) {
    var text = "TinyADA owner card\n\nLink: https://tiny.gmcat.io/" + code + "\nOwner key: " + key +
      "\n\nKeep this private. Anyone with this key can change, upgrade or delete the link.\nTo use it on another device: open the link, choose \"I own this link\" and paste the key.\n" +
      "Lost it? If the link shows a Cardano or Solana address, the wallet holding that address can always take the link back by signing a message.\n";
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" })); a.download = "tinyada-owner-" + code.replace("@", "") + ".txt";
    document.body.appendChild(a); a.click(); a.remove();
  };

  /* Would saving `body` remove an address that's on `link` now? (visitors then see a 30-day notice) */
  T.removesAddress = function (link, body) {
    return link.items.some(function (it) { return !body.items.some(function (n) { return n.address === it.address || (it.handle && n.handle === it.handle); }); });
  };

  /* Visits per day: one series, thin bars anchored to the baseline with rounded tops, hover tooltips, a table for screen readers. */
  T.visitsChart = function (body, data) {
    var days = data.days, max = Math.max(1, Math.max.apply(null, days.map(function (d) { return d.n; }))), W = 600, H = 200, top = 16, base = 170, bw = W / days.length;
    var sum = days.reduce(function (a, d) { return a + d.n; }, 0);
    var bars = days.map(function (d, i) {
      var h = d.n ? Math.max(4, (base - top) * d.n / max) : 0, x = i * bw + 1, w = bw - 2, y = base - h, rr = Math.min(4, w / 2, h);
      var path = h ? "M" + x + "," + base + "V" + (y + rr) + "Q" + x + "," + y + " " + (x + rr) + "," + y + "H" + (x + w - rr) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + rr) + "V" + base + "Z" : "";
      return '<rect class="hit" x="' + (i * bw) + '" y="' + top + '" width="' + bw + '" height="' + (base - top + 4) + '" data-i="' + i + '"></rect>' + '<path class="bar" d="' + path + '"></path>';
    }).join("");
    var label = function (i) { return new Date(days[i].day * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }); };
    body.innerHTML = '<p class="muted">' + sum + " visit" + (sum === 1 ? "" : "s") + " in the last 60 days · " + data.total + " in total. Your own visits and overlays aren't counted.</p>" +
      '<div class="t-chart-wrap"><svg class="t-chart" viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Visits per day, last 60 days. Highest: ' + max + '">' +
      '<line class="axis" x1="0" x2="' + W + '" y1="' + (base + .5) + '" y2="' + (base + .5) + '"></line>' + bars +
      '<text x="0" y="' + (H - 8) + '">' + label(0) + '</text><text x="' + W + '" y="' + (H - 8) + '" text-anchor="end">Today</text>' +
      '<text x="' + W + '" y="11" text-anchor="end">max ' + max + "</text></svg><div class=\"t-tip\" hidden></div></div>" +
      '<details><summary class="small-print">Show as a table</summary><table class="small-print"><tbody>' +
      days.slice().reverse().filter(function (d) { return d.n; }).map(function (d) { return "<tr><td>" + T.esc(new Date(d.day * 1000).toLocaleDateString()) + "</td><td>" + d.n + "</td></tr>"; }).join("") + "</tbody></table></details>";
    var svg = body.querySelector("svg"), tip = body.querySelector(".t-tip");
    svg.addEventListener("mousemove", function (ev) {
      var h = ev.target.closest(".hit");
      body.querySelectorAll(".bar.on").forEach(function (b) { b.classList.remove("on"); });
      if (!h) { tip.hidden = true; return; }
      var i = +h.dataset.i, rect = svg.getBoundingClientRect(), k = rect.width / W;
      h.nextElementSibling.classList.add("on");
      tip.hidden = false; tip.textContent = label(i) + ": " + days[i].n + " visit" + (days[i].n === 1 ? "" : "s");
      tip.style.left = ((i + .5) * bw * k) + "px"; tip.style.top = (top * k + 10) + "px";
    });
    svg.addEventListener("mouseleave", function () { tip.hidden = true; body.querySelectorAll(".bar.on").forEach(function (b) { b.classList.remove("on"); }); });
  };

  /* Payment panel for any order (Plus or Privacy Plus): every option the payment socket offers, $GMGM first.
     onDone(status) is called once when it's paid or ends. Returns a stop() function. */
  T.payPanel = function (box, order, statusUrl, onDone) {
    var opts = order.options || [];
    box.innerHTML = '<div class="t-pay">' + opts.map(function (o, i) {
      return '<div class="t-pay-opt"><p><b>' + T.esc(o.label) + "</b>" + (o.discount ? ' <span class="chip live">' + o.discount + "% off</span>" : "") + "</p>" +
        '<p class="muted">' + T.esc(o.note || "") + "</p>" +
        '<span class="field-label">Amount</span><code>' + T.esc(Number(o.amount).toLocaleString("en-US")) + " " + T.esc(o.label) + '</code><div><button class="btn" type="button" data-copy-amt="' + i + '">Copy amount</button></div>' +
        '<span class="field-label">To this address</span><code>' + T.esc(o.address) + '</code><div><button class="btn" type="button" data-copy-addr="' + i + '">Copy address</button></div></div>';
    }).join("") + '<p class="muted t-pay-status">Waiting for your payment… This updates by itself. The request is open until ' +
      new Date(order.expires * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + ".</p>" +
      (order.receipt ? '<p class="small-print"><a href="' + T.esc(order.receipt.replace(/^https?:\/\/[^/]+/, "")) + '" target="_blank" rel="noopener">Your private receipt</a> (bookmark it: it\'s the only record, there\'s no account)</p>' : "") + "</div>";
    box.onclick = function (ev) {
      var a = ev.target.closest("[data-copy-amt]"), b = ev.target.closest("[data-copy-addr]");
      if (a) T.copy(String(opts[+a.dataset.copyAmt].amount)).then(function () { T.flash(a, "Copied ✓"); });
      if (b) T.copy(opts[+b.dataset.copyAddr].address).then(function () { T.flash(b, "Copied ✓"); });
    };
    var st = box.querySelector(".t-pay-status"), done = false;
    var timer = setInterval(function () {
      T.api("GET", statusUrl).then(function (r) {
        if (!r.ok || done) return;
        var s = r.data.status;
        if (s === "paid" || s === "paid-check") { done = true; clearInterval(timer); st.innerHTML = '<b class="t-ok">✓ Paid. Thank you!</b>'; setTimeout(function () { onDone(s); }, 1500); }
        else if (s === "expired" || s === "withdrawn") {
          done = true; clearInterval(timer);
          st.innerHTML = s === "withdrawn" ? '<b class="t-bad">This request was cancelled. Please don\'t send anything to this address.</b>' : "This request has ended. If you already sent the payment, it will still be found; otherwise start a new one.";
          onDone(s);
        }
      });
    }, 10000);
    return function () { clearInterval(timer); };
  };
})();
