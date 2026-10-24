/* Theme before first paint: a blocking script in <head>. Dark is the default regardless of the system preference;
   the stored choice (localStorage pp-theme = "light" | "dark") wins. The header toggle (static/app.js) stores it. */
(function () {
  try {
    var t = localStorage.getItem('pp-theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) { /* private mode: stay dark */ }
})();
