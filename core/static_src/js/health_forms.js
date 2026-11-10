// Add optional medication rows without exposing Django's formset controls.
(() => {
  const init = () => {
    document.querySelectorAll("[data-visit-specialty]").forEach((row) => {
      const kind = row.closest("form").querySelector('[name="kind"]');
      const updateSpecialty = () => {
        // Keep the entered value when switching visit types back and forth.
        row.hidden = kind.value !== "specialist";
      };
      kind.addEventListener("change", updateSpecialty);
      updateSpecialty();
    });

    document
      .querySelectorAll("[data-prescription-formset]")
      .forEach((section) => {
        const list = section.querySelector("[data-prescription-list]");
        const template = section.querySelector("[data-prescription-template]");
        const add = section.querySelector("[data-prescription-add]");
        const prefix = section.dataset.prefix;
        const total = section.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
        const maximum = section.querySelector(
          `[name="${prefix}-MAX_NUM_FORMS"]`,
        );
        const emptyMessage = section.querySelector(
          "[data-prescription-empty-message]",
        );

        const sync = () => {
          const cards = Array.from(list.children);
          cards.forEach((card, index) => {
            const oldPrefix = card.dataset.formPrefix + "-";
            const newPrefix = `${prefix}-${index}-`;
            card
              .querySelectorAll("[name], [id], [for], [aria-describedby]")
              .forEach((node) => {
                ["name", "id", "for", "aria-describedby"].forEach(
                  (attribute) => {
                    const value = node.getAttribute(attribute);
                    if (value)
                      node.setAttribute(
                        attribute,
                        value.replaceAll(oldPrefix, newPrefix),
                      );
                  },
                );
              });
            card.dataset.formPrefix = `${prefix}-${index}`;
            card.querySelector("[data-prescription-number]").textContent =
              index + 1;
            const remove = card.querySelector("[data-prescription-remove]");
            if (remove) remove.hidden = false;
          });
          total.value = cards.length;
          emptyMessage.hidden = cards.length !== 0;
          if (add) add.disabled = cards.length >= Number(maximum.value || 1000);
        };

        if (add) add.hidden = false;
        if (add)
          add.addEventListener("click", () => {
            const fragment = template.content.cloneNode(true);
            list.append(fragment);
            sync();
            list.lastElementChild.dispatchEvent(
              new Event("bb:prescription-added", { bubbles: true }),
            );
            list.lastElementChild.querySelector('input[name$="-name"]').focus();
          });
        list.addEventListener("click", (event) => {
          const remove = event.target.closest("[data-prescription-remove]");
          if (!remove) return;
          const card = remove.closest("[data-prescription-card]");
          card.dispatchEvent(
            new Event("bb:prescription-removed", { bubbles: true }),
          );
          card.remove();
          sync();
          if (add) add.focus();
        });
        sync();
      });
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
