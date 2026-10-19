/* LotHouse admin dashboard: sidebar behaviour + Chart.js rendering. */
(function () {
  "use strict";

  var STORAGE_KEY = "lothouse-admin-sidebar";
  var NAVY = "#14243A";
  var GOLD = "#D4A64A";
  var PALETTE = [NAVY, GOLD, "#5B6B80", "#8A6A1E", "#1F7A4D", "#B3261E", "#1C5C8A", "#C2963B"];

  function ready(fn) {
    if (document.readyState !== "loading") {
      fn();
    } else {
      document.addEventListener("DOMContentLoaded", fn);
    }
  }

  function initCharts() {
    if (typeof Chart === "undefined") {
      return;
    }
    var dataEl = document.getElementById("chartData");
    if (!dataEl) {
      return;
    }
    var payload;
    try {
      payload = JSON.parse(dataEl.textContent);
    } catch (err) {
      return;
    }

    document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
      var cfg = payload[canvas.getAttribute("data-chart")];
      if (!cfg) {
        return;
      }
      if (!cfg.labels || cfg.labels.length === 0 || (cfg.values && cfg.values.length === 0)) {
        var wrap = canvas.parentElement;
        if (wrap) {
          wrap.innerHTML = '<div class="empty-state"><i class="bi bi-bar-chart"></i>No data for this period.</div>';
        }
        return;
      }
      new Chart(canvas, buildConfig(cfg));
    });
  }

  function buildConfig(cfg) {
    var type = cfg.type || "line";
    var dataset = {
      label: cfg.label || "",
      data: cfg.values,
      borderColor: NAVY,
      borderWidth: 2,
      fill: type === "line",
      tension: 0.35,
      pointRadius: type === "line" ? 2 : 0,
      borderRadius: type === "bar" ? 6 : 0,
      backgroundColor: "rgba(20,36,58,0.14)",
    };

    if (type === "doughnut") {
      dataset.backgroundColor = PALETTE.slice(0, (cfg.labels || []).length);
      dataset.borderColor = "#ffffff";
    } else if (type === "bar") {
      dataset.backgroundColor = "rgba(20,36,58,0.75)";
    }

    var scales = {};
    if (type !== "doughnut") {
      scales = {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } },
        y: { beginAtZero: true, grid: { color: "#E4DFD4" }, ticks: { precision: 0, font: { size: 10 } } },
      };
    }

    return {
      type: type,
      data: { labels: cfg.labels, datasets: [dataset] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: type === "doughnut",
            position: "bottom",
            labels: { boxWidth: 12, font: { size: 11 } },
          },
        },
        scales: scales,
      },
    };
  }

  ready(function () {
    var shell = document.getElementById("adminShell");
    if (!shell) {
      return;
    }

    try {
      if (window.innerWidth >= 992 && localStorage.getItem(STORAGE_KEY) === "collapsed") {
        shell.classList.add("sidebar-collapsed");
      }
    } catch (err) { /* localStorage unavailable */ }

    var collapseBtn = document.getElementById("sidebarCollapse");
    if (collapseBtn) {
      collapseBtn.addEventListener("click", function () {
        if (window.innerWidth < 992) {
          shell.classList.toggle("sidebar-mobile-open");
          return;
        }
        shell.classList.toggle("sidebar-collapsed");
        try {
          localStorage.setItem(
            STORAGE_KEY,
            shell.classList.contains("sidebar-collapsed") ? "collapsed" : "expanded"
          );
        } catch (err) { /* ignore */ }
      });
    }

    var backdrop = document.getElementById("adminBackdrop");
    if (backdrop) {
      backdrop.addEventListener("click", function () {
        shell.classList.remove("sidebar-mobile-open");
      });
    }

    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.getAttribute("data-confirm"))) {
          event.preventDefault();
        }
      });
    });

    initCharts();
  });
})();
