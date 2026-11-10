// Local previews use object URLs. Files are only uploaded by the normal save form.
(() => {
  const uploads = new WeakMap();
  const live = new Set();
  const release = (state) => {
    state.urls.forEach((url) => URL.revokeObjectURL(url));
    state.urls = [];
  };
  const render = (input, focusIndex = null) => {
    const root = input.closest("[data-photo-upload]");
    let state = uploads.get(input);
    if (!state) {
      state = { input, root, urls: [] };
      uploads.set(input, state);
      live.add(state);
    }
    release(state);
    const files = Array.from(input.files || []);
    const grid = root.querySelector("[data-photo-previews]");
    const status = root.querySelector("[data-photo-status]");
    const clear = root.querySelector("[data-photo-clear]");
    grid.replaceChildren();
    const error =
      files.length > Number(root.dataset.photoLimit)
        ? root.dataset.limitError
        : files.some((file) => file.size > Number(root.dataset.photoBytes))
          ? root.dataset.sizeError
          : "";
    input.setCustomValidity(error);
    status.textContent =
      error ||
      (files.length === 1
        ? root.dataset.oneLabel
        : files.length
          ? root.dataset.manyLabel.replace("{count}", files.length)
          : "");
    status.classList.toggle("text-danger", Boolean(error));
    clear.hidden = files.length === 0;
    files.forEach((file, index) => {
      const url = URL.createObjectURL(file);
      state.urls.push(url);
      const tile = document.createElement("div");
      tile.className = "bb-photo-tile";
      const link = document.createElement("a");
      link.className = "bb-photo-link";
      link.href = url;
      link.dataset.photoViewer = "";
      link.dataset.photoCaption = file.name;
      link.setAttribute(
        "aria-label",
        root.dataset.viewLabel + ": " + file.name,
      );
      const image = document.createElement("img");
      image.src = url;
      image.alt = file.name;
      image.addEventListener(
        "error",
        () => {
          image.hidden = true;
          const fallback = document.createElement("p");
          fallback.className = "small p-2";
          fallback.textContent = root.dataset.previewError;
          link.prepend(fallback);
        },
        { once: true },
      );
      const caption = document.createElement("span");
      caption.className = "bb-photo-caption";
      caption.textContent = file.name;
      link.append(image, caption);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-outline-secondary";
      remove.textContent = root.dataset.removeLabel;
      remove.setAttribute(
        "aria-label",
        root.dataset.removeLabel + ": " + file.name,
      );
      remove.addEventListener("click", () => {
        try {
          const transfer = new DataTransfer();
          files.forEach((item, position) => {
            if (position !== index) transfer.items.add(item);
          });
          input.files = transfer.files;
          render(input, Math.min(index, transfer.files.length - 1));
        } catch {
          status.textContent = root.dataset.removeError;
          clear.focus();
        }
      });
      tile.append(link, remove);
      grid.append(tile);
    });
    if (focusIndex !== null) {
      const button = grid.querySelectorAll("button")[focusIndex];
      (button || input).focus();
    }
  };
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input.matches("[data-photo-input]")) render(input);
    if (input.matches('input[type="checkbox"][name$="remove_photos"]')) {
      const tile = input.closest(".bb-photo-tile");
      if (tile)
        tile.classList.toggle("bb-photo-pending-removal", input.checked);
    }
  });
  document.addEventListener("click", (event) => {
    const clear = event.target.closest("[data-photo-clear]");
    if (!clear) return;
    const input = clear
      .closest("[data-photo-upload]")
      .querySelector("[data-photo-input]");
    input.value = "";
    render(input, -1);
  });
  document.addEventListener(
    "invalid",
    (event) => {
      let parent = event.target.parentElement;
      while (parent) {
        if (parent.tagName === "DETAILS") parent.open = true;
        parent = parent.parentElement;
      }
    },
    true,
  );
  document.addEventListener("bb:prescription-removed", (event) => {
    event.target.querySelectorAll("[data-photo-input]").forEach((input) => {
      const state = uploads.get(input);
      if (state) {
        release(state);
        live.delete(state);
        uploads.delete(input);
      }
    });
  });
  window.addEventListener("pagehide", () => live.forEach(release));
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) live.forEach((state) => render(state.input));
  });

  const initViewer = () => {
    const viewer = document.getElementById("bb-photo-viewer");
    if (!viewer || !window.bootstrap || !window.bootstrap.Modal) return;
    const image = viewer.querySelector("[data-photo-viewer-image]");
    const title = viewer.querySelector(".modal-title");
    const original = viewer.querySelector("[data-photo-original]");
    const previous = viewer.querySelector("[data-photo-previous]");
    const next = viewer.querySelector("[data-photo-next]");
    let links = [],
      index = 0,
      opener = null;
    const show = (position) => {
      index = position;
      const link = links[index];
      image.src = link.href;
      image.alt = link.dataset.photoCaption || title.textContent;
      title.textContent = image.alt;
      original.href = link.href;
      previous.disabled = index === 0;
      next.disabled = index === links.length - 1;
    };
    document.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-photo-viewer]");
      if (
        !link ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
      opener = link;
      const gallery = link.closest("[data-photo-gallery]");
      links = gallery
        ? Array.from(gallery.querySelectorAll("a[data-photo-viewer]"))
        : [link];
      show(links.indexOf(link));
      bootstrap.Modal.getOrCreateInstance(viewer).show(link);
    });
    previous.addEventListener("click", () => {
      if (index > 0) show(index - 1);
    });
    next.addEventListener("click", () => {
      if (index < links.length - 1) show(index + 1);
    });
    viewer.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" && index > 0) {
        event.preventDefault();
        show(index - 1);
      }
      if (event.key === "ArrowRight" && index < links.length - 1) {
        event.preventDefault();
        show(index + 1);
      }
    });
    viewer.addEventListener("hidden.bs.modal", () => {
      image.removeAttribute("src");
      original.removeAttribute("href");
      if (opener) opener.focus({ preventScroll: true });
      links = [];
    });
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", initViewer);
  else initViewer();
})();
