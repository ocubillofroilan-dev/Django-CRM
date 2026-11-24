/* CRM front-end behaviour. Plain JavaScript, no build step.
   Everything degrades gracefully: with JS off, search is a normal GET form,
   delete goes to a confirmation page, and flash messages stay visible. */
(function () {
  "use strict";

  var doc = document;
  var hasBootstrap = typeof window.bootstrap !== "undefined";

  /* ---------- Theme toggle ------------------------------------------- */
  function currentTheme() {
    return doc.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }
  function syncThemeButtons() {
    var dark = currentTheme() === "dark";
    doc.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
      var use = button.querySelector("use");
      if (use) use.setAttribute("href", dark ? "#i-sun" : "#i-moon");
    });
  }
  doc.addEventListener("click", function (event) {
    var button = event.target.closest("[data-theme-toggle]");
    if (!button) return;
    var next = currentTheme() === "dark" ? "light" : "dark";
    doc.documentElement.setAttribute("data-bs-theme", next);
    try { localStorage.setItem("crm-theme", next); } catch (error) { /* ignore */ }
    syncThemeButtons();
  });
  syncThemeButtons();

  /* ---------- Mobile sidebar ----------------------------------------- */
  var sidebar = doc.getElementById("sidebar");
  var backdrop = doc.getElementById("sidebarBackdrop");
  var sidebarButton = doc.querySelector("[data-sidebar-toggle]");

  function setSidebar(open) {
    if (!sidebar || !sidebarButton) return;
    sidebar.classList.toggle("is-open", open);
    if (backdrop) backdrop.classList.toggle("is-visible", open);
    sidebarButton.setAttribute("aria-expanded", String(open));
    doc.body.classList.toggle("no-scroll", open);
    if (open) {
      var first = sidebar.querySelector("a, button");
      if (first) first.focus();
    } else {
      sidebarButton.focus();
    }
  }
  if (sidebar && sidebarButton) {
    sidebarButton.addEventListener("click", function () {
      setSidebar(!sidebar.classList.contains("is-open"));
    });
    if (backdrop) backdrop.addEventListener("click", function () { setSidebar(false); });
    sidebar.addEventListener("click", function (event) {
      if (event.target.closest("a")) { sidebar.classList.remove("is-open"); if (backdrop) backdrop.classList.remove("is-visible"); doc.body.classList.remove("no-scroll"); }
    });
    window.matchMedia("(min-width: 992px)").addEventListener("change", function (query) {
      if (query.matches) { sidebar.classList.remove("is-open"); if (backdrop) backdrop.classList.remove("is-visible"); doc.body.classList.remove("no-scroll"); }
    });
  }
  doc.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && sidebar && sidebar.classList.contains("is-open")) setSidebar(false);
  });

  /* ---------- Flash messages (toasts) -------------------------------- */
  if (hasBootstrap) {
    doc.querySelectorAll(".toast").forEach(function (element) {
      var slow = element.classList.contains("text-bg-danger") || element.classList.contains("text-bg-warning");
      window.bootstrap.Toast.getOrCreateInstance(element, { delay: slow ? 9000 : 5000 }).show();
    });
  }

  /* ---------- Show / hide password ----------------------------------- */
  doc.addEventListener("click", function (event) {
    var button = event.target.closest("[data-toggle-password]");
    if (!button) return;
    var input = button.parentElement.querySelector("input");
    if (!input) return;
    var reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
    button.setAttribute("aria-pressed", String(reveal));
    var use = button.querySelector("use");
    if (use) use.setAttribute("href", reveal ? "#i-eye-off" : "#i-eye");
  });

  /* ---------- Loading state on submit (stops double submits) --------- */
  doc.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.hasAttribute("data-live-search")) return;
    var button = event.submitter || form.querySelector('button[type="submit"]');
    if (!button || button.hasAttribute("data-no-loading")) return;
    // Wait one tick so the browser has already collected the form data.
    setTimeout(function () {
      button.classList.add("is-loading");
      button.disabled = true;
    }, 0);
  });
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    doc.querySelectorAll(".btn.is-loading").forEach(function (button) {
      button.classList.remove("is-loading");
      button.disabled = false;
    });
  });

  /* ---------- Delete confirmation modal ------------------------------ */
  var deleteModalElement = doc.getElementById("deleteModal");
  if (deleteModalElement && hasBootstrap) {
    var deleteModal = window.bootstrap.Modal.getOrCreateInstance(deleteModalElement);
    doc.addEventListener("click", function (event) {
      var trigger = event.target.closest("[data-confirm-delete]");
      if (!trigger) return;
      event.preventDefault();
      deleteModalElement.querySelector("form").setAttribute("action", trigger.getAttribute("data-delete-url") || trigger.getAttribute("href"));
      deleteModalElement.querySelector("[data-delete-name]").textContent = trigger.getAttribute("data-delete-name") || "this customer";
      deleteModal.show();
    });
  }

  /* ---------- Clickable table rows ----------------------------------- */
  doc.addEventListener("click", function (event) {
    var row = event.target.closest("tr[data-href]");
    if (!row) return;
    if (event.target.closest("a, button, input, select, textarea, label")) return;
    var selection = window.getSelection && window.getSelection().toString();
    if (selection) return;
    window.location.href = row.getAttribute("data-href");
  });

  /* ---------- Live search / filter / paginate ------------------------ */
  var form = doc.querySelector("[data-live-search]");
  var results = doc.getElementById("results");
  var exportLink = doc.querySelector("[data-export-link]");
  var searchInput = doc.querySelector("[data-search-input]");

  if (form && results && window.fetch && window.URL && window.AbortController) {
    var timer = null;
    var controller = null;
    var exportBase = exportLink ? exportLink.getAttribute("href").split("?")[0] : "";

    var currentParams = function () {
      var params = new URLSearchParams(new FormData(form));
      Array.from(params.keys()).forEach(function (key) {
        if (!params.get(key)) params.delete(key);
      });
      return params;
    };
    var pathOf = function () { return form.getAttribute("action") || window.location.pathname; };
    var syncExport = function (params) {
      if (!exportLink) return;
      var copy = new URLSearchParams(params.toString());
      copy.delete("page");
      var query = copy.toString();
      exportLink.setAttribute("href", exportBase + (query ? "?" + query : ""));
    };

    var load = function (url, push) {
      if (controller) controller.abort();
      var mine = new AbortController();
      controller = mine;
      results.classList.add("is-loading");
      results.setAttribute("aria-busy", "true");

      window.fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
        signal: mine.signal
      })
        .then(function (response) {
          // Session expired -> the server redirected to the login page. Do a real navigation.
          if (response.redirected || !response.ok) { window.location.href = url; return null; }
          return response.text();
        })
        .then(function (html) {
          if (html === null) return;
          results.innerHTML = html;
          var summary = results.querySelector("[data-result-summary]");
          var status = doc.getElementById("resultsStatus");
          if (status && summary) status.textContent = summary.getAttribute("data-result-summary");
          if (push) window.history.pushState({}, "", url);
          syncExport(new URL(url, window.location.origin).searchParams);
        })
        .catch(function (error) {
          if (error && error.name === "AbortError") return;
          window.location.href = url;
        })
        .then(function () {
          if (controller === mine) {
            results.classList.remove("is-loading");
            results.removeAttribute("aria-busy");
          }
        });
    };

    var run = function () {
      var query = currentParams().toString();
      load(pathOf() + (query ? "?" + query : ""), true);
    };

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      window.clearTimeout(timer);
      run();
    });
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(run, 280);
      });
    }
    form.querySelectorAll("select").forEach(function (select) {
      select.addEventListener("change", run);
    });

    results.addEventListener("click", function (event) {
      var link = event.target.closest("a[data-page]");
      if (!link) return;
      event.preventDefault();
      load(link.getAttribute("href"), true);
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    doc.addEventListener("click", function (event) {
      var link = event.target.closest("[data-clear-filters]");
      if (!link) return;
      event.preventDefault();
      form.reset();
      if (searchInput) searchInput.value = "";
      form.querySelectorAll("select").forEach(function (select) { select.selectedIndex = 0; });
      run();
    });

    window.addEventListener("popstate", function () {
      var params = new URLSearchParams(window.location.search);
      form.querySelectorAll("input[name], select[name]").forEach(function (field) {
        field.value = params.get(field.name) || (field.tagName === "SELECT" ? field.options[0].value : "");
      });
      load(window.location.pathname + window.location.search, false);
    });
  }

  /* ---------- Keyboard: "/" jumps to search -------------------------- */
  doc.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
    var active = doc.activeElement;
    var typing = active && (/^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName) || active.isContentEditable);
    if (typing || !searchInput) return;
    event.preventDefault();
    searchInput.focus();
    searchInput.select();
  });
})();