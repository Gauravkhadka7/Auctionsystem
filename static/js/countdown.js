/**
 * Drives every countdown on the page. Each element needs:
 *   data-countdown="SECONDS_REMAINING"
 * and child spans with data-unit="d|h|m|s".
 * When a countdown hits zero, it dispatches a "countdown:complete" event
 * on the element so pages can react (e.g. refresh bid status via AJAX).
 *
 * Anti-sniping support: scripts that receive a fresh server-side deadline
 * (AJAX bid response or WebSocket frame) set a new data-countdown value and
 * dispatch "countdown:update" — the ticker restarts from the new value instead
 * of staying frozen on the stale one.
 */
(function () {
  function renderUnits(el, totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    const map = { d: days, h: hours, m: minutes, s: seconds };
    el.querySelectorAll("[data-unit]").forEach((span) => {
      const unit = span.dataset.unit;
      span.textContent = String(map[unit]).padStart(2, "0");
    });
  }

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

  function start(el) {
    if (el.__countdownTimer) {
      clearInterval(el.__countdownTimer);
      el.__countdownTimer = null;
    }
    renderUnits(el, parseInt(el.dataset.countdown, 10) || 0);
    el.__countdownTimer = setInterval(() => {
      if (!tick(el)) {
        clearInterval(el.__countdownTimer);
        el.__countdownTimer = null;
      }
    }, 1000);
  }

  function init() {
    document.querySelectorAll("[data-countdown]").forEach(start);
  }

  // A new (possibly extended) deadline was pushed from the server.
  document.addEventListener("countdown:update", (event) => {
    const el = event.target;
    if (el && el.hasAttribute && el.hasAttribute("data-countdown")) start(el);
  });

  document.addEventListener("DOMContentLoaded", init);

  /**
   * Small shared helper used by bidding.js / auction_socket.js to surface
   * auction events (anti-sniping extension, ending-soon reminder) without a
   * page reload. Creates the notice panel inside #live-auction-panel on demand.
   */
  window.LotHouseAuction = {
    showNotice(message, variant) {
      const panel = document.getElementById("live-auction-panel");
      if (!panel) return;
      let notice = document.getElementById("auction-notice");
      if (!notice) {
        notice = document.createElement("div");
        notice.id = "auction-notice";
        notice.className = "alert py-2 small mb-3 d-none";
        panel.insertBefore(notice, panel.firstChild);
      }
      notice.className =
        "alert py-2 small mb-3 " +
        (variant === "warning" ? "alert-warning" : "alert-info");
      notice.textContent = message;
    },
    applyDeadline(data) {
      const countdownEl = document.querySelector(".countdown-strip");
      if (!countdownEl || data.time_remaining_seconds == null) return;
      countdownEl.dataset.countdown = data.time_remaining_seconds;
      countdownEl.dispatchEvent(new CustomEvent("countdown:update", { bubbles: true }));
    },
    describeEvent(data) {
      if (data.event === "extended" || (data.extended && data.auction_end)) {
        const when = data.auction_end
          ? new Date(data.auction_end).toLocaleString()
          : "a later time";
        return {
          message: `Anti-sniping: a late bid pushed this auction's close time back to ${when}.`,
          variant: "warning",
        };
      }
      if (data.event === "ending_soon") {
        return {
          message: "This auction is ending soon — place your final bids now.",
          variant: "info",
        };
      }
      return null;
    },
  };
})();
