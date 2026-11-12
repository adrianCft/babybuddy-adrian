// The real text field remains the submitted value, including with JavaScript off.
(() => {
  const bindDoseSuggestions = (picker, choice, form) => {
    const source = picker.querySelector("[data-dose-source]");
    if (!source) return;
    const { date, children } = JSON.parse(
      document.getElementById("medication-dose-suggestions").textContent,
    );
    const child = form.elements.namedItem("child");
    const time = form.elements.namedItem("time");
    const dosage = form.elements.namedItem("dosage");
    const interval = form.elements.namedItem("next_dose_interval");
    const units = form.querySelectorAll('[name="dosage_unit"]');

    const onSuggestionDate = () => time.value.slice(0, 10) === date;
    const fill = () => {
      const medications = children[child.value];
      const [amount, unit, origin, hours] =
        onSuggestionDate() &&
        medications &&
        Object.hasOwn(medications, choice.value)
          ? medications[choice.value]
          : [];
      dosage.value = amount ?? "";
      interval.value = hours ?? "";
      units.forEach((radio) => (radio.checked = radio.value === unit));
      source.textContent = origin ? source.dataset[origin] : "";
      source.hidden = !origin;
    };
    const clearSource = () => {
      source.hidden = true;
      source.textContent = "";
    };

    choice.addEventListener("change", fill);
    child.addEventListener("change", () => {
      if (choice.value) fill();
    });
    time.addEventListener("change", () => {
      if (!onSuggestionDate() && !source.hidden) fill();
    });
    dosage.addEventListener("input", clearSource);
    interval.addEventListener("input", clearSource);
    units.forEach((radio) => radio.addEventListener("change", clearSource));
  };

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
      bindDoseSuggestions(picker, choice, input.form);
    });
  };
  document.addEventListener("bb:prescription-added", (event) =>
    initPickers(event.target),
  );
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => initPickers(document));
  } else initPickers(document);
})();
