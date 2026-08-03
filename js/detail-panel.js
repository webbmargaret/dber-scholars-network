// Renders a selected scholar's full record into the detail panel. Only fields that are
// actually present are shown — sparse records get a note instead of a wall of blanks.

const FIELD_DEFS = [
  { key: "institution", label: "Institution", type: "chips" },
  { key: "program", label: "Program", type: "chips" },
  { key: "position_title", label: "Position", type: "text" },
  { key: "position_type", label: "Position Type", type: "text" },
  { key: "dber_field", label: "DBER Field", type: "chips" },
  { key: "research_interests", label: "Research Interests", type: "text" },
  { key: "expert_type", label: "Expert Type", type: "chips" },
  { key: "phd_year", label: "PhD Year", type: "text" },
  { key: "dissertation_title", label: "Dissertation Title", type: "text" },
  { key: "position_or_advisor_note", label: "First Position / Advisor Note", type: "text" },
  { key: "phase", label: "Phase / Fellow Notes", type: "text" },
  { key: "notes", label: "Notes", type: "text" },
  { key: "data_quality_flag", label: "Data Quality Flag", type: "text" },
  { key: "source_list", label: "Source(s)", type: "chips" },
];

function isEmpty(v) {
  if (v == null) return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "string") return v.trim() === "";
  return false;
}

function renderDetailPanel(panelEl, scholar) {
  panelEl.innerHTML = "";

  const closeBtn = document.createElement("button");
  closeBtn.className = "close-btn";
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", () => panelEl.classList.remove("open"));
  panelEl.appendChild(closeBtn);

  const h3 = document.createElement("h3");
  h3.textContent = scholar.name;
  panelEl.appendChild(h3);

  let shown = 0;
  for (const def of FIELD_DEFS) {
    const val = scholar[def.key];
    if (isEmpty(val)) continue;
    shown++;
    const wrap = document.createElement("div");
    wrap.className = "detail-field";
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = def.label;
    wrap.appendChild(label);

    if (def.type === "chips") {
      const row = document.createElement("div");
      row.className = "chip-row";
      for (const v of val) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = v;
        row.appendChild(chip);
      }
      wrap.appendChild(row);
    } else {
      const value = document.createElement("div");
      value.className = "value";
      value.textContent = val;
      wrap.appendChild(value);
    }
    panelEl.appendChild(wrap);
  }

  if (scholar.completeness < 0.2) {
    const note = document.createElement("div");
    note.className = "sparse-note";
    note.textContent =
      "Limited information is available for this person in the source data — this isn't an error, just what was recoverable from public sources.";
    panelEl.appendChild(note);
  }

  panelEl.classList.add("open");
}
