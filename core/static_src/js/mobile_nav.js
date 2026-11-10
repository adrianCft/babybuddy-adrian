// Keep registration and the full menu separate on small screens.
$(function () {
  if (document.querySelector(".submit-primary")) {
    document.body.classList.add("bb-app--form");
  }

  var quickPanel = document.getElementById("quick-record-panel");
  var fullMenu = document.getElementById("navbar-app");
  if (!quickPanel || !fullMenu) return;

  quickPanel.addEventListener("show.bs.offcanvas", function () {
    if (fullMenu.classList.contains("show")) {
      bootstrap.Collapse.getOrCreateInstance(fullMenu, {
        toggle: false,
      }).hide();
    }
  });
});
