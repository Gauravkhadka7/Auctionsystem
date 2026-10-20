/**
 * Live bidding widget: submits bids via AJAX and polls the auction status
 * endpoint every few seconds so the price/time/bid-count stay fresh for
 * everyone watching the page, without a full reload.
 */
(function () {
  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  function initBidForm() {
    const form = document.getElementById("bid-form");
    if (!form) return;

    const amountInput = document.getElementById("bid-amount");
    const errorBox = document.getElementById("bid-error");
    const slug = form.dataset.slug;

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      errorBox.classList.add("d-none");

      fetch(`/bids/${slug}/place/ajax/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: `amount=${encodeURIComponent(amountInput.value)}`,
      })
        .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
          if (!ok || !data.ok) {
            errorBox.textContent = data.error || "Couldn't place that bid.";
            errorBox.classList.remove("d-none");
            return;
          }
          applyStatus(data);
          amountInput.value = data.minimum_next_bid;
          if (data.extended) {
            // Anti-sniping: restart the countdown from the extended deadline.
            window.LotHouseAuction.showNotice(
              `Your late bid extended this auction to ${new Date(
                data.auction_end
              ).toLocaleString()}.`,
              "warning"
            );
          }
        })
        .catch(() => {
          errorBox.textContent = "Network error — please try again.";
          errorBox.classList.remove("d-none");
        });
    });
  }

  function applyStatus(data) {
    const priceEl = document.getElementById("current-price");
    const minBidEl = document.getElementById("bid-amount");
    const bidsCountEl = document.getElementById("total-bids");
    const biddersCountEl = document.getElementById("total-bidders");

    if (priceEl && data.current_price) priceEl.textContent = data.current_price;
    if (minBidEl && data.minimum_next_bid) minBidEl.setAttribute("min", data.minimum_next_bid);
    if (bidsCountEl && data.total_bids !== undefined) bidsCountEl.textContent = data.total_bids;
    if (biddersCountEl && data.total_bidders !== undefined) biddersCountEl.textContent = data.total_bidders;

    // Keep the client countdown honest by re-syncing with the server clock.
    // This also picks up anti-sniping extensions without a page reload.
    if (window.LotHouseAuction) window.LotHouseAuction.applyDeadline(data);
  }

  function pollStatus() {
    const container = document.getElementById("live-auction-panel");
    if (!container) return;
    const slug = container.dataset.slug;
    let knownEnd = null;

    const interval = setInterval(() => {
      fetch(`/bids/${slug}/status/ajax/`)
        .then((res) => res.json())
        .then((data) => {
          applyStatus(data);
          if (knownEnd && data.auction_end && data.auction_end !== knownEnd) {
            window.LotHouseAuction.showNotice(
              `This auction was extended to ${new Date(
                data.auction_end
              ).toLocaleString()} by a late bid.`,
              "warning"
            );
          }
          knownEnd = data.auction_end || knownEnd;
          if (data.status === "CLOSED") {
            clearInterval(interval);
            // Reload exactly once so we don't loop forever on a closed auction.
            if (!window.__auctionClosedHandled) {
              window.__auctionClosedHandled = true;
              window.location.reload();
            }
          }
        })
        .catch(() => {});
    }, 5000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initBidForm();
    pollStatus();
  });
})();
