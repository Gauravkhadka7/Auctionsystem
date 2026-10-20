/**
 * Live notification bell.
 *
 * Subscribes to /ws/notifications/ and updates the navbar bell in place: the
 * unread badge and the dropdown preview. Purely an enhancement — without
 * WebSockets the bell still updates on the next page load.
 */
(function () {
  const bell = document.getElementById("notification-bell");
  if (!bell || !("WebSocket" in window)) return;

  const badge = document.getElementById("notification-badge");
  const menu = document.getElementById("notification-menu");
  const scheme = window.location.protocol === "https:" ? "wss" : "https";

  function renderBadge(count) {
    if (!badge) return;
    if (count > 0) {
      badge.textContent = count;
      badge.classList.remove("d-none");
    } else {
      badge.classList.add("d-none");
    }
  }

  function prependNotification(data) {
    if (!menu) return;
    const empty = menu.querySelector("[data-notification-empty]");
    if (empty) empty.remove();

    const item = document.createElement("li");
    const link = document.createElement("a");
    link.className = "dropdown-item small fw-semibold";
    link.href = data.open_url || data.link || "#";
    link.textContent =
      data.message.length > 60
        ? `${data.message.slice(0, 57)}...`
        : data.message;
    item.appendChild(link);
    menu.insertBefore(item, menu.firstChild);
  }

  function connect() {
    const socket = new WebSocket(
      `${scheme}://${window.location.host}/ws/notifications/`
    );

    socket.onmessage = function (event) {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (typeof data.unread_count === "number") {
        renderBadge(data.unread_count);
      }
      if (data.type === "notification.new" && data.message) {
        prependNotification(data);
      }
    };

    socket.onclose = function () {
      // Silent: the bell refreshes on the next page load.
    };
  }

  connect();
})();
