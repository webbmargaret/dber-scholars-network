// Wires the sidebar controls (attribute selector, edge toggle, search, PhD-year range,
// legend, live count) to a NetworkGraph instance.

// Per-grouping caveats, condensed from about.html / README_scholars_dataset.md — shown
// under the Group-by select so a first-time visitor sees them without digging into
// About. Percentages here are static (checked against data/build_meta.json's
// fill_counts at time of writing); about.html's own stats table is the live source.
const ATTR_CAVEATS = {
  institution: "Coverage leans on institutions with a published, dated alumni roster — not a measure of program size or activity.",
  program: "Institution and Program often cluster near-identically for the largest schools (Purdue's Engineering Education program essentially is Purdue's presence here).",
  dber_field: "Only ~6% of people have a hand-sourced DBER field tag; the rest of any visible coverage is machine-inferred (dashed chips in the detail panel), not verified.",
  phd_era: "PhD year is known for under 10% of people — most of the graph has no PhD-era group at all.",
  none: "",
};

function initFilters({ graph, scholars, groups, els }) {
  let legendExpanded = false;

  function renderGroupCaveat(attr) {
    if (!els.groupCaveat) return;
    const text = ATTR_CAVEATS[attr] || "";
    els.groupCaveat.textContent = text;
    els.groupCaveat.hidden = !text;
  }

  function populateSubgroupOptions(activeAttr) {
    if (!els.subgroupSelect) return;
    els.subgroupSelect.innerHTML = "";
    const noneOpt = document.createElement("option");
    noneOpt.value = "none";
    noneOpt.textContent = "None";
    els.subgroupSelect.appendChild(noneOpt);
    Object.keys(ATTR_LABELS)
      .filter((a) => a !== activeAttr)
      .forEach((a) => {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = ATTR_LABELS[a];
        els.subgroupSelect.appendChild(opt);
      });
  }

  if (els.subgroupWrap) {
    graph.onIsolationChange = (hubId) => {
      if (hubId) {
        populateSubgroupOptions(els.attrSelect.value);
        els.subgroupSelect.value = "none";
        els.subgroupWrap.hidden = false;
      } else {
        els.subgroupWrap.hidden = true;
      }
    };
  }

  els.subgroupSelect?.addEventListener("change", () => {
    graph.setSubAttribute(els.subgroupSelect.value);
  });
  els.clearIsolationBtn?.addEventListener("click", () => {
    graph.clearIsolation();
  });
  els.collabEdgeToggle?.addEventListener("change", () => {
    graph.setShowCollabEdges(els.collabEdgeToggle.checked);
  });
  const groupedCountCache = {};
  function groupedPeopleCount(attr) {
    if (attr === "none") return scholars.length;
    if (groupedCountCache[attr] == null) {
      const ids = new Set();
      (groups[attr] || []).forEach((g) => g.memberIds.forEach((id) => ids.add(id)));
      groupedCountCache[attr] = ids.size;
    }
    return groupedCountCache[attr];
  }
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
    const visible = legendExpanded ? list : list.slice(0, 14);
    visible.forEach((g, i) => {
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
    if (list.length > 14) {
      const toggle = document.createElement("li");
      toggle.className = "legend-toggle";
      toggle.textContent = legendExpanded ? "Show fewer" : `+ ${list.length - 14} more…`;
      toggle.tabIndex = 0;
      toggle.setAttribute("role", "button");
      toggle.setAttribute("aria-expanded", String(legendExpanded));
      const toggleFn = () => {
        legendExpanded = !legendExpanded;
        renderLegend(attr);
      };
      toggle.addEventListener("click", toggleFn);
      toggle.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleFn();
        }
      });
      els.legend.appendChild(toggle);
    }
  }

  const RESULTS_CAP = 8;

  function renderSearchResults(term) {
    els.searchResults.innerHTML = "";
    if (!term) {
      els.searchResults.hidden = true;
      return;
    }
    els.searchResults.hidden = false;
    const all = graph.matches;
    const visible = all.slice(0, RESULTS_CAP);
    visible.forEach(({ scholar, isNameMatch }) => {
      const li = document.createElement("li");
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      const nameEl = document.createElement("span");
      nameEl.className = "search-result-name";
      nameEl.textContent = scholar.name;
      const instEl = document.createElement("span");
      instEl.className = "search-result-inst";
      instEl.textContent = scholar.institution[0] ? scholar.institution[0].name : "Institution unknown";
      li.appendChild(nameEl);
      li.appendChild(instEl);
      if (!isNameMatch) {
        const badge = document.createElement("span");
        badge.className = "search-result-badge";
        badge.textContent = "mentioned in notes";
        li.appendChild(badge);
      }
      const select = () => graph.onSelectPerson(scholar);
      li.addEventListener("click", select);
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          select();
        }
      });
      els.searchResults.appendChild(li);
    });
    if (all.length > RESULTS_CAP) {
      const more = document.createElement("li");
      more.className = "search-result-overflow";
      const remaining = all.length - RESULTS_CAP;
      more.textContent = `+ ${remaining} more match${remaining === 1 ? "" : "es"} — refine your search to narrow`;
      els.searchResults.appendChild(more);
    }
  }

  function updateCount() {
    const attr = els.attrSelect.value;
    const groupCount = attr === "none" ? 0 : (groups[attr] || []).length;
    const suffix = attr === "none" ? "" : ` across ${groupCount} ${ATTR_LABELS[attr].toLowerCase()} groups`;
    const term = els.search.value.trim();
    if (term) {
      const n = graph.matchCount;
      els.countReadout.classList.toggle("no-match", n === 0);
      els.countReadout.textContent =
        n === 0
          ? `0 people match "${term}" — try a different term`
          : `${n} ${n === 1 ? "person" : "people"} match "${term}"`;
      return;
    }
    els.countReadout.classList.remove("no-match");
    els.countReadout.textContent = `Showing ${groupedPeopleCount(attr)} people${suffix}`;
  }

  els.attrSelect.addEventListener("change", () => {
    const attr = els.attrSelect.value;
    legendExpanded = false;
    graph.setAttribute(attr);
    renderLegend(attr);
    renderGroupCaveat(attr);
    updateCount();
  });

  els.edgeToggle.addEventListener("change", () => {
    graph.setShowEdges(els.edgeToggle.checked);
  });

  els.search.addEventListener("input", () => {
    graph.setSearch(els.search.value);
    updateCount();
    renderSearchResults(els.search.value.trim());
  });

  els.yearRangeToggle.addEventListener("change", applyYearFilter);
  els.yearMin.addEventListener("input", applyYearFilter);
  els.yearMax.addEventListener("input", applyYearFilter);

  renderLegend(els.attrSelect.value);
  renderGroupCaveat(els.attrSelect.value);
  updateCount();
  renderSearchResults(els.search.value.trim());
}
