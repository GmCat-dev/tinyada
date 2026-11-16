/* GmCat day / night switch (theme.py). Light by default; the choice follows you across every *.gmcat.io site. */
(function () {
  "use strict";
  var root = document.documentElement, LIGHT = "#eef1ff", DARK = "#0c1030";
  function label() {
    var dark = root.getAttribute("data-theme") === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      b.setAttribute("aria-label", dark ? "Switch to day mode" : "Switch to night mode");
      if (b.classList.contains("theme-toggle")) { b.setAttribute("aria-pressed", dark ? "true" : "false"); b.querySelector(".tt-label").textContent = dark ? "Night" : "Day"; }
    });
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) { m.setAttribute("content", dark ? DARK : LIGHT); });
  }
  function saved() {
    var m = document.cookie.match(/(?:^|; )gmcat-theme=(dark|light)/);
    if (m) return m[1];
    try { var v = localStorage.getItem("gmcat-theme"); if (v === "dark" || v === "light") return v; } catch (e) { /* fine */ }
    return null;
  }
  function save(t) {
    var shared = /(^|\.)gmcat\.io$/.test(location.hostname);
    document.cookie = "gmcat-theme=" + t + "; Path=/; Max-Age=31536000; SameSite=Lax" + (shared ? "; Domain=gmcat.io; Secure" : "");
    try { localStorage.setItem("gmcat-theme", t); } catch (e) { /* not saved: fine */ }
  }
  function sync() {   // another GmCat site changed it (back button, other tab): follow quietly
    var t = saved() || "light";
    if (root.getAttribute("data-theme") !== t) { root.setAttribute("data-theme", t); label(); }
  }
  function toggle() {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.classList.add("theme-anim");
    clearTimeout(toggle.t); toggle.t = setTimeout(function () { root.classList.remove("theme-anim"); }, 1100);
    root.setAttribute("data-theme", next);
    save(next);
    document.querySelectorAll(".sky-stage .cat").forEach(function (cat) { cat.classList.remove("boop"); void cat.offsetWidth; cat.classList.add("boop"); });
    label();
  }
  label();
  var t0 = saved();
  if (t0 && !/(?:^|; )gmcat-theme=/.test(document.cookie)) save(t0);   // carry an older per-site choice over to every site
  window.addEventListener("pageshow", sync);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) sync(); });
  document.addEventListener("click", function (ev) { if (ev.target.closest && ev.target.closest("[data-theme-toggle]")) toggle(); });
})();
