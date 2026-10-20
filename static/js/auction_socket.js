/**
 * Live auction WebSocket client.
 *
 * Connects to /ws/auction/<slug>/ and applies pushed state changes instantly.
 * It auto-reconnects with backoff and degrades gracefully: if WebSockets are
 * unavailable the HTTP polling in bidding.js keeps the page up to date.
 */
(function () {
  const panel = document.getElementById("live-auction-panel");
  if (!panel || !panel.dataset.slug) return;
  if (!("WebSocket" in window)) return;

  const slug = panel.dataset.slug;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  let socket = null;
  let retries = 0;
  let stopped = false;

  function apply(data) {
    const priceEl = document.getElementById("current-price");
    const minBidEl = document.getElementById("bid-amount");
    const bidsEl = document.getElementById("total-bids");
    const biddersEl = document.getElementById("total-bidders");

    if (priceEl && data.current_price != null) priceEl.textContent = data.current_price;
    if (minBidEl && data.minimum_next_bid != null) minBidEl.setAttribute("min", data.minimum_next_bid);
    if (bidsEl && data.total_bids != null) bidsEl.textContent = data.total_bids;
    if (biddersEl && data.total_bidders != null) biddersEl.textContent = data.total_bidders;

    // Re-sync the countdown against the server deadline — this is what makes
    // an anti-sniping extension visible without reloading the page.
    if (window.LotHouseAuction) {
      window.LotHouseAuction.applyDeadline(data);
      const notice = window.LotHouseAuction.describeEvent(data);
      if (notice && data.event !== "snapshot") {
        window.LotHouseAuction.showNotice(notice.message, notice.variant);
      }
    }

    if (data.status === "CLOSED") {
      stopped = true;
      if (socket) {
        socket.__manualClose = true;
        socket.close();
      }
      if (!window.__auctionClosedHandled) {
        window.__auctionClosedHandled = true;
        window.location.reload();
      }
    }
  }

  function connect() {
    if (stopped) return;
    socket = new WebSocket(`${scheme}://${window.location.host}/ws/auction/${slug}/`);

    socket.onopen = function () {
      retries = 0;
    };

    socket.onmessage = function (event) {
      try {
        apply(JSON.parse(event.data));
      } catch (err) {
        /* ignore malformed frames */
      }
    };

    socket.onclose = function () {
      if (socket.__manualClose || stopped) return;
      retries = Math.min(retries + 1, 6);
      setTimeout(connect, retries * 1000);
    };

    socket.onerror = function () {
      if (socket) socket.close();
    };
  }

  connect();
})();
