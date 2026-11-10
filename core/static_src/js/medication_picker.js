// The real text field remains the submitted value, including with JavaScript off.
(() => {
  const initPickers = (root) => {
    root.querySelectorAll("[data-medication-picker]").forEach((picker) => {
      if (picker.dataset.ready) return;
      picker.dataset.ready = "true";
      const choice = picker.querySelector("[data-medication-choice]");
      const input = picker.querySelector("input");
      const entry = picker.querySelector("[data-medication-new]");
      const label = picker
        .closest(".bb-form-field")
        .querySelector(".bb-form-label");
      const known = Array.from(choice.options).find(
        (option) => option.value && option.value === input.value,
      );
      let draft = known ? "" : input.value;
      choice.value = known ? known.value : "";
      choice.hidden = false;
      const update = (focus) => {
        if (choice.value) {
          input.value = choice.value;
          entry.hidden = true;
          label.htmlFor = choice.id;
        } else {
          input.value = draft;
          entry.hidden = false;
          label.htmlFor = input.id;
          if (focus) input.focus();
        }
      };
      input.addEventListener("input", () => {
        draft = input.value;
      });
      choice.addEventListener("change", () => update(true));
      update(false);
    });
  };
  document.addEventListener("bb:prescription-added", (event) =>
    initPickers(event.target),
  );
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initPickers(document));
  } else initPickers(document);
})();
