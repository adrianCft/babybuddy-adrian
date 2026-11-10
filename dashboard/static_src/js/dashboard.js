/* Baby Buddy Dashboard
 *
 * Provides a "watch" function to update the dashboard at one minute intervals
 * and/or on visibility state changes.
 */
BabyBuddy.Dashboard = (function ($) {
  var runIntervalId = null;
  var dashboardElement = null;
  var hidden = null;

  var Dashboard = {
    watch: function (element_id, refresh_rate) {
      dashboardElement = $("#" + element_id);

      if (dashboardElement.length == 0) {
        console.error("Baby Buddy: Dashboard element not found.");
        return false;
      }

      if (typeof document.hidden !== "undefined") {
        hidden = "hidden";
      } else if (typeof document.msHidden !== "undefined") {
        hidden = "msHidden";
      } else if (typeof document.webkitHidden !== "undefined") {
        hidden = "webkitHidden";
      }

      if (
        typeof window.addEventListener === "undefined" ||
        typeof document.hidden === "undefined"
      ) {
        if (refresh_rate) {
          runIntervalId = setInterval(this.update, refresh_rate);
        }
      } else {
        window.addEventListener(
          "focus",
          Dashboard.handleVisibilityChange,
          false,
        );
        if (refresh_rate) {
          runIntervalId = setInterval(
            Dashboard.handleVisibilityChange,
            refresh_rate,
          );
        }
      }
    },

    handleVisibilityChange: function () {
      const editing =
        document.querySelector(
          "[data-home-customizer][open], .bb-home-more[open]",
        ) ||
        document.activeElement.matches("input, select, textarea") ||
        document.querySelector(".offcanvas.show, #navbar-app.show");
      if (!document[hidden] && !editing) {
        Dashboard.update();
      }
    },

    update: function () {
      // TODO: Someday maybe update in place?
      location.reload();
    },
  };

  return Dashboard;
})(jQuery);
