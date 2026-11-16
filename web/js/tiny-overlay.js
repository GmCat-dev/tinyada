/* TinyADA stream overlay: tiny.gmcat.io/<code>/overlay[?theme=light] as an OBS browser source (transparent page).
   Refreshes every 10 minutes, so an edited Plus link updates on stream by itself. Overlay views are not counted. */
(function () {
  "use strict";
  var T = window.Tiny, $ = T.$;
  var code = decodeURIComponent(location.pathname.split("/")[1] || ""), box = $("t-overlay");
  if (/[?&]theme=light/.test(location.search)) box.classList.add("light");
  function load() {
    T.api("GET", "/l/" + encodeURIComponent(code) + "?nc=1").then(function (r) {
      if (!r.ok) { box.hidden = true; return; }
      var d = r.data, it = d.items[0];
      $("t-ov-qr").innerHTML = T.qrSvg(d.link);
      $("t-ov-title").textContent = d.title || (d.items.length > 1 ? "Tip me in crypto" : (it.handle || "Tip me in " + (T.COINS[it.coin] || { sym: it.coin }).sym));
      $("t-ov-link").textContent = d.link.replace(/^https?:\/\//, "");
      box.hidden = false;
    });
  }
  load();
  setInterval(load, 600000);
})();
