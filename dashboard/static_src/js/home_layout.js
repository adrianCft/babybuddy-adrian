// Selected checkboxes are submitted in their visible DOM order.
(() => {
  const init = () => {
    document.querySelectorAll("[data-home-layout]").forEach((form) => {
      const selected = form.querySelector("[data-home-selected]");
      const available = form.querySelector("[data-home-available]");
      const count = form.querySelector("[data-home-count]");
      const limit = form.querySelector("[data-home-limit]");
      const sync = () => {
        const rows = Array.from(selected.children);
        count.textContent = rows.length;
        rows.forEach((row, index) => {
          row.querySelector("[data-home-order]").hidden = false;
          const up = row.querySelector('[data-card-move="up"]');
          const down = row.querySelector('[data-card-move="down"]');
          up.hidden = down.hidden = false;
          up.disabled = index === 0;
          down.disabled = index === rows.length - 1;
        });
        available.querySelectorAll('input[name="cards"]').forEach((input) => {
          input.disabled = rows.length >= 6;
        });
        limit.hidden = rows.length < 6;
        limit.textContent = form.dataset.limitMessage;
      };
      form.addEventListener("change", (event) => {
        const input = event.target;
        if (!input.matches('input[name="cards"]')) return;
        const row = input.closest("[data-home-option]");
        if (input.checked) {
          selected.append(row);
          input.scrollIntoView({ block: "nearest" });
        } else {
          row.querySelector("[data-home-order]").hidden = true;
          available.append(row);
          const next =
            selected.querySelector("input") ||
            form.querySelector('button[type="submit"]');
          next.focus();
        }
        sync();
      });
      form.addEventListener("click", (event) => {
        const button = event.target.closest("[data-card-move]");
        if (!button) return;
        const row = button.closest("[data-home-option]");
        if (button.dataset.cardMove === "up" && row.previousElementSibling) {
          selected.insertBefore(row, row.previousElementSibling);
        } else if (
          button.dataset.cardMove === "down" &&
          row.nextElementSibling
        ) {
          selected.insertBefore(row.nextElementSibling, row);
        }
        sync();
        if (button.disabled) row.querySelector("input").focus();
        else button.focus();
      });
      sync();
    });
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
