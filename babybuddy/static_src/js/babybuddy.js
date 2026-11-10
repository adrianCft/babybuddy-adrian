if (typeof jQuery === "undefined") {
  throw new Error("Baby Buddy requires jQuery.");
}

/**
 * Baby Buddy Namespace
 *
 * Default namespace for the Baby Buddy app.
 *
 * @type {{}}
 */
var BabyBuddy = (function () {
  return {};
})();

/**
 * Pull to refresh.
 *
 * @type {{init: BabyBuddy.PullToRefresh.init, onRefresh: BabyBuddy.PullToRefresh.onRefresh}}
 */
BabyBuddy.PullToRefresh = (function (ptr) {
  return {
    init: function () {
      ptr.init({
        mainElement: "body",
        onRefresh: this.onRefresh,
      });
    },

    onRefresh: function () {
      window.location.reload();
    },
  };
})(PullToRefresh);

/**
 * Show a loading spinner on the submit button when a form is submitted and
 * prevent double-submission.
 */
(function handleFormSubmit() {
  $("form").on("submit", function (event) {
    var submitter =
      (event.originalEvent && event.originalEvent.submitter) ||
      $(this).find('[type="submit"]')[0];
    if (!submitter || $(submitter).prop("disabled")) return;
    // Disabled buttons are omitted from POST data. Preserve the clicked action.
    if (submitter.name) {
      $("<input>", {
        type: "hidden",
        name: submitter.name,
        value: submitter.value,
      })
        .attr("data-bb-submit-name", "")
        .appendTo(this);
    }
    submitter.dataset.bbSubmitting = "1";
    $(submitter)
      .prop("disabled", true)
      .prepend(
        '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true" data-bb-submit-spinner></span>',
      );
  });
  window.addEventListener("pageshow", function () {
    document
      .querySelectorAll("[data-bb-submitting]")
      .forEach(function (button) {
        button.disabled = false;
        delete button.dataset.bbSubmitting;
        const spinner = button.querySelector("[data-bb-submit-spinner]");
        if (spinner) spinner.remove();
      });
    document
      .querySelectorAll("[data-bb-submit-name]")
      .forEach(function (input) {
        input.remove();
      });
  });
})();

BabyBuddy.RememberAdvancedToggle = function (ptr) {
  localStorage.setItem("advancedForm", event.newState);
};

(function toggleAdvancedFields() {
  window.addEventListener("load", function () {
    if (localStorage.getItem("advancedForm") !== "open") {
      return;
    }

    document.querySelectorAll(".advanced-fields").forEach(function (node) {
      node.open = true;
    });
  });
})();
