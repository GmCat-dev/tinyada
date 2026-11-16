/* TinyADA: the link page (tiny.gmcat.io/<code> and /@name). Everything shown comes from /api/tiny/l/<code>,
   escaped before it touches the page. */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$;
  var code = decodeURIComponent(location.pathname.replace(/^\/+|\/+$/g, "")), data = null, current = 0;

  function fail(msg) { $("t-state").innerHTML = "<h1 class=\"panel-h\">" + T.esc(msg) + '</h1><p class="muted">Ask the person who shared it for a new link.</p>'; }

  var mineKey = (function () { try { var x = JSON.parse(localStorage.getItem("tiny-mine") || "[]").find(function (i) { return i.code === code; }); return x && x.token; } catch (e) { return ""; } })();
  T.api("GET", "/l/" + encodeURIComponent(code), undefined, mineKey ? { "X-Owner-Key": mineKey } : undefined).then(function (r) {
    if (!r.ok) {
      document.title = "Link not found · TinyADA";
      return fail(r.status === 451 ? "This link is hidden while it's reviewed." : r.status === 404 ? "This link doesn't exist any more." : (r.data.error || "This link couldn't be opened."));
    }
    data = r.data;
    render();
  });

  function render() {
    var d = data, first = d.items[0], multi = d.items.length > 1;
    var title = d.title || (multi ? "Crypto addresses" : (first.handle || first.name + " address"));
    document.title = title + " · TinyADA";
    $("t-h").textContent = title;
    $("t-kind").textContent = multi ? "Tip page" : "Crypto address";
    if (d.bio) { $("t-bio").textContent = d.bio; $("t-bio").hidden = false; }
    var av = $("t-avatar");
    if (d.avatar) { av.textContent = d.avatar.e; av.className = "t-avatar t-av-" + d.avatar.c; }
    else { av.textContent = multi ? "//" : T.COINS[first.coin] ? T.COINS[first.coin].sym : first.coin; av.className = "t-avatar coin"; }
    if (d.changed_at) {
      $("t-changed").hidden = false;
      $("t-changed").textContent = "⚠ An address on this page was changed on " + T.fmtDate(d.changed_at) + (d.prev_tails && d.prev_tails.length ? " (the old one ended in …" + d.prev_tails.join(", …") + ")" : "") +
        ". If someone gave you an address before, check with them which one is right.";
    }
    if (d.owner && d.plus) {
      $("t-mine-note").hidden = false;
      $("t-mine-note").innerHTML = "This is your link. Your own visits aren't counted. <a href=\"/plus/\">Edit it in TinyADA Plus</a>";
    }
    var tabs = $("t-tabs");
    if (multi) {
      tabs.hidden = false;
      tabs.innerHTML = d.items.map(function (it, i) {
        return '<button type="button" role="tab" id="t-tab-' + i + '" aria-controls="t-item-' + i + '" aria-selected="' + (i === 0) + '">' + T.esc(it.label || T.COINS[it.coin].sym) + "</button>";
      }).join("");
      tabs.addEventListener("click", function (ev) { var b = ev.target.closest("button"); if (b) show(+b.id.split("-").pop()); });
    }
    $("t-items").innerHTML = d.items.map(item).join("");
    if (d.socials && d.socials.length) {
      $("t-socials").hidden = false;
      $("t-socials").innerHTML = d.socials.map(function (s) {
        var host = s.url.replace(/^https:\/\/(www\.)?/, "").split(/[/?#]/)[0];
        return '<li><a href="' + T.esc(s.url) + '" rel="nofollow noopener ugc" target="_blank">' + T.esc(s.label || host) + "</a></li>";
      }).join("");
    }
    $("t-foot").textContent = d.plus ? (d.mode === "forever" ? "TinyADA Plus link" : "Kept while people use it") :
      d.mode === "inuse" ? "Free link · kept while people use it" : "Free link · until " + T.fmtDate(d.expires);
    $("t-state").hidden = true;
    $("t-paper").hidden = false;
    show(0);
    document.dispatchEvent(new CustomEvent("tiny:loaded", { detail: d }));
  }

  function item(it, i) {
    var info = T.COINS[it.coin] || { name: it.coin, sym: it.coin }, uri = T.payUri(it);
    var ask = it.amount ? '<p class="t-ask-line">' + T.esc(it.amount) + " " + T.esc(info.sym) + (it.memo ? "<small>" + T.esc(it.memo) + "</small>" : "") + "</p>" :
      it.memo ? '<p class="t-ask-line"><small>' + T.esc(it.memo) + "</small></p>" : "";
    var trust = it.verified ? '<p class="t-trust ok">✓ Verified owner: whoever made this page proved they hold this address by signing with its wallet.</p>' :
      '<p class="t-trust">Not verified. TinyADA checked this address for typos, but not who owns it.</p>';
    return '<section class="t-item" id="t-item-' + i + '" role="' + (data.items.length > 1 ? "tabpanel" : "region") + '" aria-label="' + T.esc(info.name) + '"' + (i ? " hidden" : "") + ">" +
      '<p class="t-item-coin"' + (data.items.length === 1 && !it.label && !it.handle && !data.title ? " hidden" : "") + ">" + T.esc(info.name) + (it.label ? " <small>· " + T.esc(it.label) + "</small>" : "") + (it.handle ? " <small>· " + T.esc(it.handle) + "</small>" : "") + "</p>" +
      (it.moved ? '<p class="t-banner">' + T.esc(it.handle) + " points to a different address than when this link was made. This is the current one.</p>" : "") +
      ask + '<div class="t-qr" role="img" aria-label="QR code with the ' + T.esc(info.name) + ' address">' + T.qrSvg(it.amount || it.memo ? uri : it.address) + "</div>" +
      '<p class="t-addr">' + T.addrHtml(it.address) + "</p>" +
      '<div class="t-end"><p class="t-end-label">Check the ending matches your wallet</p><div class="t-end-chars">…' + T.esc(it.address.slice(-6)) + "</div></div>" +
      '<div class="t-item-btns"><button class="btn primary" type="button" data-copy="' + i + '">Copy address</button>' +
      '<a class="btn" href="' + T.esc(uri) + '" data-wallet>Open in wallet</a></div>' + trust + "</section>";
  }

  function show(i) {
    current = i;
    document.querySelectorAll(".t-item").forEach(function (s, k) { s.hidden = k !== i; });
    document.querySelectorAll("#t-tabs button").forEach(function (b, k) { b.setAttribute("aria-selected", k === i ? "true" : "false"); });
  }

  document.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-copy]");
    if (b) { var a = data.items[+b.dataset.copy].address; T.copy(a).then(function (ok) { T.flash(b, ok ? "Copied ✓" : "Press and hold the address to copy"); }); }
  });

  /* report */
  var dlg = $("t-rep-dlg");
  $("t-report").addEventListener("click", function () { $("t-rep-msg").textContent = ""; dlg.showModal(); });
  dlg.addEventListener("click", function (ev) { if (ev.target === dlg) dlg.close(); });
  $("t-rep-send").addEventListener("click", function () {
    var reason = $("t-rep-reason").value;
    if (!reason) { $("t-rep-msg").textContent = "Choose a reason first."; return; }
    T.api("POST", "/l/" + encodeURIComponent(code) + "/report", { reason: reason, details: $("t-rep-details").value }).then(function (r) {
      if (!r.ok) { $("t-rep-msg").textContent = r.data.error || "Couldn't send it. Please try again."; return; }
      dlg.close();
      T.tell({ title: "Thanks for telling us", text: "A person at GmCat will look at it. After several reports a link is hidden until it's reviewed." });
    });
  });
})();
