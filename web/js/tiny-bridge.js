/* TinyADA sign-in bridge (same idea as Drop's and NomCat's). The GmCat account page loads
   /session-bridge.html in a hidden frame so its "Signed in on this device" list can show whether this browser is signed in
   to TinyADA, and sign it out from there. It answers only the GmCat account page, and shares only: signed in or not, and
   how (wallet or GmCat account). Never the session itself (that cookie is HttpOnly anyway). */
(function () {
  "use strict";
  var local = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  var PARENTS = local ? ["http://127.0.0.1:4191", "http://localhost:4191"] : ["https://account.gmcat.io"];
  if (window.parent === window) return;
  function status() {
    return fetch("/api/tiny/me", { credentials: "same-origin" }).then(function (r) { return r.json(); }).catch(function () { return {}; }).then(function (d) {
      return { gmcat: "session", site: "tiny", signedIn: !!d.signed_in, via: d.signed_in ? (d.via === "wallet" ? "wallet" : "gmcat") : "" };
    });
  }
  function tell(origin) { status().then(function (s) { window.parent.postMessage(s, origin); }); }
  window.addEventListener("message", function (ev) {
    if (PARENTS.indexOf(ev.origin) < 0 || ev.source !== window.parent) return;
    var m = ev.data || {};
    if (m.gmcat !== "session") return;
    if (m.do === "sign-out") {
      return fetch("/api/tiny/session", { method: "DELETE", credentials: "same-origin" }).catch(function () {}).then(function () { tell(ev.origin); });
    }
    tell(ev.origin);
  });
  PARENTS.forEach(function (o) { try { tell(o); } catch (e) { /* not this parent */ } });
})();
