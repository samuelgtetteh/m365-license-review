// Shared light/dark theme handling for all pages.
// Applied immediately (before paint) to avoid a flash, then wires the toggle.
(function () {
  var saved = null;
  try { saved = localStorage.getItem("m365-theme"); } catch (e) {}
  if (saved) document.documentElement.setAttribute("data-theme", saved);
})();

document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  function current() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }
  function render() {
    btn.textContent = current() === "light" ? "🌙 Dark" : "☀ Light";
  }
  render();
  btn.addEventListener("click", function () {
    var next = current() === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("m365-theme", next); } catch (e) {}
    render();
  });
});
