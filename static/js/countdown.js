/**
 * Drives every countdown on the page. Each element needs:
 *   data-countdown="SECONDS_REMAINING"
 * and child spans with data-unit="d|h|m|s".
 * When a countdown hits zero, it dispatches a "countdown:complete" event
 * on the element so pages can react (e.g. refresh bid status via AJAX).
 */
(function () {
  function tick(el) {
    let remaining = parseInt(el.dataset.countdown, 10);
    if (isNaN(remaining) || remaining <= 0) {
      renderUnits(el, 0);
      return false;
    }
    remaining -= 1;
    el.dataset.countdown = remaining;
    renderUnits(el, remaining);
    if (remaining <= 0) {
      el.dispatchEvent(new CustomEvent("countdown:complete", { bubbles: true }));
      return false;
    }
    return true;
  }

  function renderUnits(el, totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = Math.floor(totalSeconds % 60);

    const map = { d: days, h: hours, m: minutes, s: seconds };
    el.querySelectorAll("[data-unit]").forEach((span) => {
      const key = span.dataset.unit;
      span.textContent = String(map[key]).padStart(2, "0");
    });
  }

  function init() {
    document.querySelectorAll("[data-countdown]").forEach((el) => {
      renderUnits(el, parseInt(el.dataset.countdown, 10) || 0);
      const interval = setInterval(() => {
        const keepGoing = tick(el);
        if (!keepGoing) clearInterval(interval);
      }, 1000);
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
