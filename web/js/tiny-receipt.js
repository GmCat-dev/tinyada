/* TinyADA private receipt (tiny.gmcat.io/receipt/<order id>). Whoever has this address can see the order: there is no
   account, so this page IS the record. Shows live status and, while it's open, how to pay. */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$, id = decodeURIComponent(location.pathname.split("/")[2] || ""), stop = null;
  var WORD = { open: "Waiting for payment", late: "Waiting (late payments still count for a day)", paid: "Paid ✓", "paid-check": "Paid ✓ (being checked by GmCat)", expired: "Ended without payment", withdrawn: "Cancelled" };
  function load() {
    T.api("GET", "/orders/" + encodeURIComponent(id)).then(function (r) {
      if (!r.ok) { $("t-rc").innerHTML = '<h1 class="panel-h">Receipt not found</h1><p class="muted">Check the address, or ask GmCat through the support page.</p>'; return; }
      var o = r.data, paid = o.status === "paid" || o.status === "paid-check";
      $("t-rc").innerHTML = '<p class="eyebrow"><a href="/">TinyADA</a> · Receipt</p><h1 class="panel-h">' + T.esc(o.upgrade === "name" ? "Custom name @" + o.name : o.label) + "</h1>" +
        '<table class="t-rc-table"><tbody><tr><th>For</th><td><a href="/' + T.esc(o.code) + '">tiny.gmcat.io/' + T.esc(o.code) + "</a></td></tr>" +
        "<tr><th>Price</th><td>$" + o.usd.toFixed(2) + ((o.options || []).filter(function (x) { return x.discount; }).map(function (x) { return " · $" + x.usd.toFixed(2) + " when paid in " + T.esc(x.label) + " (" + x.discount + "% off)"; })[0] || "") + "</td></tr><tr><th>Started</th><td>" + T.esc(new Date(o.created * 1000).toLocaleString()) + "</td></tr>" +
        '<tr><th>Status</th><td><b class="' + (paid ? "t-ok" : "") + '">' + T.esc(WORD[o.status] || o.status) + "</b></td></tr>" +
        (o.tx ? "<tr><th>Transaction</th><td><code>" + T.esc(o.tx) + "</code></td></tr>" : "") + "</tbody></table>" +
        (o.status === "open" || o.status === "late" ? '<div id="t-rc-pay"></div>' : "") +
        '<p class="small-print muted">Bookmark this page: with no account, it\'s your only record. Something wrong? Write to GmCat through <a href="https://support.gmcat.io/#feedback">support</a> and include this page\'s address.</p>';
      if (o.status === "open" || o.status === "late") {
        if (stop) stop();
        stop = T.payPanel($("t-rc-pay"), o, "/orders/" + encodeURIComponent(id), load);
      }
    });
  }
  load();
})();
