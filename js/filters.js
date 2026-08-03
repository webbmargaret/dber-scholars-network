// Wires the sidebar controls (attribute selector, edge toggle, search, PhD-year range,
// legend, live count) to a NetworkGraph instance.

function initFilters({ graph, scholars, groups, els }) {
  const yearsWithData = scholars.map((s) => s.phd_year).filter((y) => y != null);
  const minYear = yearsWithData.length ? Math.min(...yearsWithData) : 1990;
  const maxYear = yearsWithData.length ? Math.max(...yearsWithData) : new Date().getFullYear();

  els.yearMin.min = minYear;
  els.yearMin.max = maxYear;
  els.yearMin.value = minYear;
  els.yearMax.min = minYear;
  els.yearMax.max = maxYear;
  els.yearMax.value = maxYear;
  els.yearLabel.textContent = `${minYear}–${maxYear}`;
  els.yearRangeToggle.checked = false;

  function applyYearFilter() {
    if (!els.yearRangeToggle.checked) {
      graph.setYearRange(null);
      els.yearLabel.textContent = `${minYear}–${maxYear} (all, incl. unknown)`;
      return;
    }
    const lo = Math.min(Number(els.yearMin.value), Number(els.yearMax.value));
    const hi = Math.max(Number(els.yearMin.value), Number(els.yearMax.value));
    graph.setYearRange([lo, hi]);
    els.yearLabel.textContent = `${lo}–${hi} (PhD year known)`;
    updateCount();
  }

  function renderLegend(attr) {
    els.legend.innerHTML = "";
    if (attr === "none") {
      els.legendTitle.textContent = "";
      return;
    }
    const list = groups[attr] || [];
    els.legendTitle.textContent = `Top ${ATTR_LABELS[attr]} groups`;
    const top = list.slice(0, 14);
    top.forEach((g, i) => {
      const li = document.createElement("li");
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = colorForIndex(i);
      const label = document.createElement("span");
      label.textContent = g.label;
      label.style.flex = "1";
      label.style.overflow = "hidden";
      label.style.textOverflow = "ellipsis";
      label.style.whiteSpace = "nowrap";
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = g.count;
      li.appendChild(swatch);
      li.appendChild(label);
      li.appendChild(count);
      li.title = "Click to isolate this group in the network";
      li.addEventListener("click", () => graph.isolateHub(`hub:${g.groupId}`));
      els.legend.appendChild(li);
    });
    if (list.length > top.length) {
      const more = document.createElement("li");
      more.textContent = `+ ${list.length - top.length} more…`;
      more.style.color = "var(--ink-soft)";
      more.style.cursor = "default";
      els.legend.appendChild(more);
    }
  }

  function updateCount() {
    const attr = els.attrSelect.value;
    const groupCount = attr === "none" ? 0 : (groups[attr] || []).length;
    const suffix = attr === "none" ? "" : ` across ${groupCount} ${ATTR_LABELS[attr].toLowerCase()} groups`;
    els.countReadout.textContent = `Showing ${scholars.length} people${suffix}`;
  }

  els.attrSelect.addEventListener("change", () => {
    const attr = els.attrSelect.value;
    graph.setAttribute(attr);
    renderLegend(attr);
    updateCount();
  });

  els.edgeToggle.addEventListener("change", () => {
    graph.setShowEdges(els.edgeToggle.checked);
  });

  els.search.addEventListener("input", () => {
    graph.setSearch(els.search.value);
  });

  els.yearRangeToggle.addEventListener("change", applyYearFilter);
  els.yearMin.addEventListener("input", applyYearFilter);
  els.yearMax.addEventListener("input", applyYearFilter);

  renderLegend(els.attrSelect.value);
  updateCount();
}
