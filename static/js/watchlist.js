/**
 * Progressive enhancement for the Watch / Watching button.
 *
 * The button is a real POST form (see templates/watchlist/_watch_button.html),
 * so it already works without JS. This script intercepts the submit, toggles
 * the watch state over AJAX, and falls back to a normal form submit if the
 * request fails for any reason.
 */
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  function applyState(form, watching, watchersCount) {
    form.dataset.watching = watching ? "1" : "0";

    const button = form.querySelector("button");
    const label = form.querySelector(".watch-label");
    const icon = form.querySelector("i");

    if (label) label.textContent = watching ? "Watching" : "Watch";
    if (icon) icon.className = "bi " + (watching ? "bi-bookmark-check-fill" : "bi-bookmark");
    if (button) {
      button.classList.toggle("btn-brass", watching);
      button.classList.toggle("btn-outline-cream", !watching);
    }

    if (watchersCount !== undefined && watchersCount !== null) {
      // Scope to this card/section so sibling cards keep their own counts.
      const scope = form.closest("[data-watch-scope]") || form.parentElement;
      const countEl = scope ? scope.querySelector(".js-watchers-count") : null;
      if (countEl) countEl.textContent = watchersCount;
    }
  }

  function initForm(form) {
    form.addEventListener("submit", function (event) {
      if (!window.fetch) return; // let the browser do a normal submit
      event.preventDefault();

      const button = form.querySelector("button");
      if (button) button.disabled = true;

      fetch(form.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: new URLSearchParams(new FormData(form)).toString(),
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (button) button.disabled = false;
          if (!result.ok || !result.data.ok) {
            if (result.data && result.data.error) {
              window.alert(result.data.error);
              return;
            }
            form.submit(); // fall back to the full-page submit
            return;
          }
          applyState(form, result.data.watching, result.data.watchers_count);
        })
        .catch(function () {
          if (button) button.disabled = false;
          form.submit();
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form.watch-toggle").forEach(initForm);
  });
})();
