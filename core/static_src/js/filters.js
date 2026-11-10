// Validation errors stay visible even when filters normally live in a panel.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-filter-panel]").forEach(function (panel) {
    panel.inert = true;
    panel.addEventListener("show.bs.offcanvas", function () {
      panel.inert = false;
    });
    panel.addEventListener("hidden.bs.offcanvas", function () {
      panel.inert = true;
    });
    if (panel.hasAttribute("data-filter-errors")) {
      bootstrap.Offcanvas.getOrCreateInstance(panel).show();
    }
  });
});
