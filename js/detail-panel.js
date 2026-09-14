// Renders a selected scholar's full record into the detail panel. Only fields that are
// actually present are shown — sparse records get a note instead of a wall of blanks.

const FIELD_DEFS = [
  { key: "institution", label: "Institution", type: "chips" },
  { key: "program", label: "Program", type: "chips" },
  { key: "position_title", label: "Position", type: "text" },
  { key: "position_type", label: "Position Type", type: "text" },
  { key: "dber_field", label: "DBER Field", type: "chips" },
  { key: "dber_field_inferred", label: "DBER Field (machine-inferred)", type: "chips" },
  { key: "research_interests", label: "Research Interests", type: "text" },
  { key: "phd_year", label: "PhD Year", type: "text" },
  { key: "dissertation_title", label: "Dissertation Title", type: "text" },
  { key: "position_or_advisor_note", label: "First Position / Advisor Note", type: "text" },
  { key: "n_citations", label: "Citations (Scholar-matched)", type: "text" },
  { key: "h_index", label: "h-index (Scholar-matched)", type: "text" },
  { key: "notes", label: "Notes", type: "text" },
];

function isEmpty(v) {
  if (v == null) return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "string") return v.trim() === "";
  return false;
}

function renderDetailPanel(panelEl, scholar, grant) {
  panelEl.innerHTML = "";

  const closeBtn = document.createElement("button");
  closeBtn.className = "close-btn";
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", () => panelEl.classList.remove("open"));
  panelEl.appendChild(closeBtn);

  const h3 = document.createElement("h3");
  h3.textContent = scholar.name;
  panelEl.appendChild(h3);

  if (grant) {
    const chip = document.createElement("span");
    chip.className = "chip chip--grant";
    chip.textContent = `Apprentice Faculty Grant, ${grant.award_year}`;
    panelEl.appendChild(chip);
  }

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
    if ((def.key === "n_citations" || def.key === "h_index") && scholar.match_confidence && scholar.match_confidence !== "high") {
      label.title = `From an automated Scholar-profile match flagged '${scholar.match_confidence}' confidence — may reflect the wrong person. See About.`;
      label.classList.add("label--caveat");
    }
    wrap.appendChild(label);

    if (def.type === "chips") {
      const row = document.createElement("div");
      row.className = "chip-row";
      for (const v of val) {
        const chip = document.createElement("span");
        if (def.key === "institution") {
          chip.className = v.status === "former" ? "chip chip--former" : "chip";
          chip.textContent = v.status === "former" ? `${v.name} (former)` : v.name;
        } else if (def.key === "dber_field_inferred") {
          chip.className = "chip chip--inferred";
          chip.textContent = v.code;
          chip.title = `Inferred from publication venues/keywords, not hand-verified. Confidence: ${v.confidence}. Evidence: ${v.evidence}`;
        } else {
          chip.className = "chip";
          chip.textContent = v;
        }
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
