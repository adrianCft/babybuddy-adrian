// Only browsing selectors navigate. Form selectors belong to their save form.
document.addEventListener("change", function (event) {
  if (!event.target.matches("[data-child-switcher-select]")) return;
  const form = event.target.closest("[data-child-switcher]");
  if (form) form.requestSubmit();
});
