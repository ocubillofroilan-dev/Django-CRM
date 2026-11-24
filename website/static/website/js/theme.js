/* Runs before first paint so the page never flashes the wrong theme. */
(function () {
  try {
    var saved = localStorage.getItem("crm-theme");
    var theme = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-bs-theme", theme);
  } catch (error) {
    /* storage blocked: stay on the default light theme */
  }
})();