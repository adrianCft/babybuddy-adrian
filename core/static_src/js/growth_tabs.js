(() => {
  const init = () => {
    document.querySelectorAll("[data-growth-tab]").forEach((tab) => {
      tab.addEventListener("shown.bs.tab", () => {
        const url = new URL(window.location.href);
        url.searchParams.set("metric", tab.dataset.growthTab);
        window.history.replaceState(null, "", url);
      });
    });
    document.querySelectorAll("[data-growth-chart]").forEach((chart) => {
      const points = Array.from(chart.querySelectorAll("[data-growth-point]"));
      const readout = chart.querySelector("[data-growth-readout]");
      const select = (point) => {
        points.forEach((candidate) =>
          candidate.classList.toggle("is-selected", candidate === point),
        );
        readout.querySelector("[data-point-date]").textContent =
          point.dataset.date;
        readout.querySelector("[data-point-value]").textContent =
          point.dataset.value === point.dataset.chartValue
            ? point.dataset.value
            : point.dataset.value + " · " + point.dataset.chartValue;
        readout.querySelector("[data-point-percentile]").textContent =
          point.dataset.percentile;
        readout.hidden = false;
      };
      chart.addEventListener("click", (event) => {
        let point = event.target.closest("[data-growth-point]");
        if (!point) return;
        // Enlarged touch targets can overlap; pick the closest plotted dot.
        const svg = chart.querySelector("svg");
        const matrix = svg.getScreenCTM();
        if (matrix) {
          const cursor = svg.createSVGPoint();
          cursor.x = event.clientX;
          cursor.y = event.clientY;
          const local = cursor.matrixTransform(matrix.inverse());
          point = points.reduce((nearest, candidate) => {
            const distance = (p) =>
              Math.pow(Number(p.getAttribute("cx")) - local.x, 2) +
              Math.pow(Number(p.getAttribute("cy")) - local.y, 2);
            return distance(candidate) < distance(nearest)
              ? candidate
              : nearest;
          }, point);
        }
        select(point);
        readout.scrollIntoView({ block: "nearest" });
      });
      points.forEach((point) => {
        point.addEventListener("focus", () => select(point));
        point.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            select(point);
            readout.scrollIntoView({ block: "nearest" });
          }
        });
      });
    });
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
