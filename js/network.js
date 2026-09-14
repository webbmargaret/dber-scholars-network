// Hub-and-spoke force graph rendered to canvas. One hub node per group value of the
// currently-active attribute; person nodes link to their hub(s). Edge count is O(n),
// not O(n^2) — see build/build_data.py and the project README for why.

const ATTR_LABELS = {
  institution: "Institution",
  program: "Program",
  dber_field: "DBER Field",
  phd_era: "PhD Era",
};

const PALETTE = [
  "#1F5B63", "#B15C33", "#6B4C8A", "#4C7A3D", "#A13D3D",
  "#C89238", "#3D6B8C", "#8A5C4C", "#5C7A3D", "#7A3D6B",
];

function colorForIndex(i) {
  return PALETTE[i % PALETTE.length];
}

// Person node radius, sized by citation count where known (a Scholar-profile match) —
// sqrt-scaled and clamped so the citation-count power law doesn't blow up the graph.
// Opacity (see _draw) carries record-completeness instead, so the two axes stay
// distinct rather than one field doing double duty.
function prominenceRadius(nCitations) {
  const base = 2;
  if (!nCitations) return base;
  return Math.min(base + Math.sqrt(nCitations) * 0.34, 15);
}

class NetworkGraph {
  constructor(canvas, { onSelectPerson, onStateChange } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelectPerson = onSelectPerson || (() => {});
    this.onStateChange = onStateChange || (() => {});
    this.scholars = [];
    this.groups = {};
    this.collabEdgeDefs = [];
    this.nodes = [];
    this.links = [];
    this.scholarById = new Map();
    this.activeAttr = "institution";
    this.showEdges = true;
    this.showCollabEdges = false;
    this.searchTerm = "";
    this.searchWords = [];
    this.matchCount = 0;
    this.matches = [];
    this.yearRange = null; // [min, max] or null
    this.transform = { x: 0, y: 0, k: 1 };
    this.isolatedHub = null;
    this.subAttr = null;
    this._subclustered = false;
    this.dragging = null;
    this.hoveredId = null;

    this._resize();
    window.addEventListener("resize", () => this._resize());
    this._bindInteraction();
  }

  _resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.width = rect.width;
    this.height = rect.height;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.canvas.style.width = rect.width + "px";
    this.canvas.style.height = rect.height + "px";
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._draw();
  }

  load(scholars, groups, collabEdgeDefs = []) {
    this.scholars = scholars;
    this.groups = groups;
    this.collabEdgeDefs = collabEdgeDefs;
    this.scholarById = new Map(scholars.map((s) => [s.id, s]));
    this._haystackById = new Map(scholars.map((s) => [s.id, this._buildHaystack(s)]));
    this._nameHaystackById = new Map(scholars.map((s) => [s.id, (s.name || "").toLowerCase()]));
    this.setAttribute(this.activeAttr, { warm: false });
  }

  _attrValuesForScholar(scholar, attr) {
    if (attr === "institution") return scholar.institution.map((i) => i.name);
    if (attr === "program") return scholar.program;
    if (attr === "dber_field") {
      const inferred = (scholar.dber_field_inferred || []).map((d) => d.code);
      return [...new Set([...scholar.dber_field, ...inferred])];
    }
    if (attr === "phd_era") return scholar.phd_era ? [scholar.phd_era] : [];
    return [];
  }

  _buildHaystack(scholar) {
    return [
      scholar.name,
      scholar.institution.map((i) => i.name).join(" "),
      scholar.program.join(" "),
      scholar.dber_field.join(" "),
      scholar.research_interests,
      scholar.position_title,
      scholar.dissertation_title,
      scholar.position_or_advisor_note,
      scholar.notes,
    ]
      .map((v) => v || "")
      .join(" ")
      .toLowerCase();
  }

  setAttribute(attr, { warm = true } = {}) {
    this.activeAttr = attr;
    this.isolatedHub = null;
    this.subAttr = null;
    this._subclustered = false;
    const prevPositions = warm ? this._capturePositions() : null;
    this._buildNodesAndLinks(attr);
    if (prevPositions) this._restorePositions(prevPositions);
    this._startSimulation();
    this.onStateChange();
  }

  setShowEdges(show) {
    this.showEdges = show;
    this._draw();
    this.onStateChange();
  }

  setShowCollabEdges(show) {
    this.showCollabEdges = show;
    const prevPositions = this._capturePositions();
    if (this._subclustered) {
      this._buildSubclusteredNodesAndLinks(this.isolatedHub, this.subAttr);
    } else {
      this._buildNodesAndLinks(this.activeAttr);
    }
    this._restorePositions(prevPositions);
    this._startSimulation();
    this.onStateChange();
  }

  setSearch(term) {
    this.searchTerm = term.trim().toLowerCase();
    this.searchWords = this.searchTerm.split(/\s+/).filter(Boolean);
    this._draw();
    this.onStateChange();
  }

  setYearRange(range) {
    this.yearRange = range;
    this._draw();
    this.onStateChange();
  }

  isolateHub(hubId) {
    this.isolatedHub = this.isolatedHub === hubId ? null : hubId;
    this.subAttr = null;
    if (this._subclustered) {
      this._subclustered = false;
      this._buildNodesAndLinks(this.activeAttr, { warm: true });
      this._startSimulation();
    } else {
      this._draw();
    }
    this.onStateChange();
  }

  clearIsolation() {
    if (!this.isolatedHub) return;
    this.isolateHub(this.isolatedHub);
  }

  setSubAttribute(attr) {
    if (!this.isolatedHub) return;
    const next = attr && attr !== "none" ? attr : null;
    this.subAttr = next;
    const prevPositions = this._capturePositions();
    if (next) {
      this._buildSubclusteredNodesAndLinks(this.isolatedHub, next);
      this._subclustered = true;
    } else {
      this._subclustered = false;
      this._buildNodesAndLinks(this.activeAttr);
    }
    this._restorePositions(prevPositions);
    this._startSimulation();
    this.onStateChange();
  }

  _buildSubclusteredNodesAndLinks(hubId, subAttr) {
    const groupId = hubId.replace("hub:", "");
    const topGroup = (this.groups[this.activeAttr] || []).find((g) => g.groupId === groupId);
    const memberIds = topGroup ? topGroup.memberIds : [];
    const memberIdSet = new Set(memberIds);
    const memberScholars = memberIds.map((id) => this.scholarById.get(id)).filter(Boolean);

    const bySubValue = new Map();
    for (const s of memberScholars) {
      const values = this._attrValuesForScholar(s, subAttr);
      const keys = values.length ? values : ["(none)"];
      for (const v of keys) {
        if (!bySubValue.has(v)) bySubValue.set(v, []);
        bySubValue.get(v).push(s.id);
      }
    }
    const subGroupList = [...bySubValue.entries()]
      .map(([label, ids]) => ({ label, memberIds: ids }))
      .sort((a, b) => b.memberIds.length - a.memberIds.length);

    const subHubNodes = subGroupList.map((g, i) => ({
      id: `subhub:${i}`,
      type: "hub",
      label: g.label,
      count: g.memberIds.length,
      color: colorForIndex(i),
      x: this.width / 2 + Math.cos((i / Math.max(subGroupList.length, 1)) * 2 * Math.PI) * 40,
      y: this.height / 2 + Math.sin((i / Math.max(subGroupList.length, 1)) * 2 * Math.PI) * 40,
    }));

    const personNodes = memberScholars.map((s) => ({
      id: s.id,
      type: "person",
      scholar: s,
      color: "#8C8F7E",
      x: this.width / 2 + (Math.random() - 0.5) * 200,
      y: this.height / 2 + (Math.random() - 0.5) * 200,
    }));

    const links = [];
    subGroupList.forEach((g, i) => {
      const hub = subHubNodes[i];
      for (const memberId of g.memberIds) links.push({ source: memberId, target: hub.id, kind: "hub" });
    });

    if (this.showCollabEdges) {
      for (const e of this.collabEdgeDefs) {
        if (memberIdSet.has(e.source) && memberIdSet.has(e.target)) {
          links.push({ source: e.source, target: e.target, kind: "collab" });
        }
      }
    }

    this.nodes = [...subHubNodes, ...personNodes];
    this.links = links;
    this.hubNodes = subHubNodes;
  }

  _capturePositions() {
    const map = new Map();
    for (const n of this.nodes || []) map.set(n.id, { x: n.x, y: n.y });
    return map;
  }

  _restorePositions(prev) {
    for (const n of this.nodes) {
      const p = prev.get(n.id);
      if (p) {
        n.x = p.x;
        n.y = p.y;
      }
    }
  }

  _buildNodesAndLinks(attr) {
    const groupList = attr === "none" ? [] : this.groups[attr] || [];
    const hubNodes = groupList.map((g, i) => ({
      id: `hub:${g.groupId}`,
      type: "hub",
      label: g.label,
      count: g.count,
      color: colorForIndex(i),
      x: this.width / 2 + Math.cos((i / Math.max(groupList.length, 1)) * 2 * Math.PI) * 40,
      y: this.height / 2 + Math.sin((i / Math.max(groupList.length, 1)) * 2 * Math.PI) * 40,
    }));
    const hubByGroupId = new Map(hubNodes.map((h) => [h.id.replace("hub:", ""), h]));

    const personNodes = this.scholars.map((s) => ({
      id: s.id,
      type: "person",
      scholar: s,
      color: "#8C8F7E",
      x: this.width / 2 + (Math.random() - 0.5) * 200,
      y: this.height / 2 + (Math.random() - 0.5) * 200,
    }));
    const personById = new Map(personNodes.map((n) => [n.id, n]));

    const links = [];
    if (attr !== "none") {
      for (const g of groupList) {
        const hub = hubByGroupId.get(g.groupId);
        for (const memberId of g.memberIds) {
          links.push({ source: memberId, target: hub.id, kind: "hub" });
          const pn = personById.get(memberId);
          if (pn) pn.color = hub.color;
        }
      }
    }

    if (this.showCollabEdges) {
      for (const e of this.collabEdgeDefs) {
        links.push({ source: e.source, target: e.target, kind: "collab" });
      }
    }

    this.nodes = attr === "none" ? personNodes : [...hubNodes, ...personNodes];
    this.links = links;
    this.hubNodes = hubNodes;
  }

  _startSimulation() {
    if (this.simulation) this.simulation.stop();
    const nodes = this.nodes;
    const links = this.links;
    const width = this.width;
    const height = this.height;

    this.simulation = d3
      .forceSimulation(nodes)
      .alphaDecay(0.035)
      .velocityDecay(0.42)
      .force(
        "link",
        d3
          .forceLink(links)
          .id((d) => d.id)
          .distance((d) => (d.kind === "collab" ? 60 : 38))
          .strength((d) => (d.kind === "collab" ? 0.25 : 0.55))
      )
      .force("charge", d3.forceManyBody().strength((d) => (d.type === "hub" ? -220 : -32)))
      .force(
        "collide",
        d3.forceCollide().radius((d) => (d.type === "hub" ? 22 : prominenceRadius(d.scholar.n_citations) + 1.5))
      )
      .force("center", d3.forceCenter(width / 2, height / 2))
      .on("tick", () => this._draw());

    // Let it settle then stop ticking to save CPU; a drag/attribute-change restarts it.
    this.simulation.on("end", () => {});
    clearTimeout(this._stopTimer);
    this._stopTimer = setTimeout(() => {
      if (this.simulation) this.simulation.alphaTarget(0);
    }, 4000);
  }

  _matchesFilters(scholar) {
    if (this.yearRange && scholar.phd_year != null) {
      if (scholar.phd_year < this.yearRange[0] || scholar.phd_year > this.yearRange[1]) return false;
    }
    if (this.yearRange && scholar.phd_year == null) return false;
    if (this.searchWords.length) {
      const hay = this._haystackById.get(scholar.id) || this._buildHaystack(scholar);
      if (!this.searchWords.every((w) => hay.includes(w))) return false;
    }
    return true;
  }

  _isNameMatch(scholar) {
    const nameHay = this._nameHaystackById.get(scholar.id) || (scholar.name || "").toLowerCase();
    return this.searchWords.every((w) => nameHay.includes(w));
  }

  _draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    if (!this.nodes) return;

    ctx.save();
    ctx.translate(this.transform.x, this.transform.y);
    ctx.scale(this.transform.k, this.transform.k);

    // Isolation dimming only applies to the top-level hub view — once sub-clustered,
    // this.nodes already contains only the isolated set, so there's nothing left to dim.
    const isolated = this._subclustered ? null : this.isolatedHub;
    const isolatedMemberIds = isolated
      ? new Set(
          this.links
            .filter((l) => l.kind === "hub" && l.target.id === isolated)
            .map((l) => l.source.id)
        )
      : null;

    // Edges
    ctx.lineWidth = 1 / this.transform.k;
    for (const l of this.links) {
      const s = l.source, t = l.target;
      if (typeof s !== "object" || typeof t !== "object") continue;
      if (l.kind === "collab") {
        if (!this.showCollabEdges) continue;
        if (isolated && !(isolatedMemberIds.has(s.id) && isolatedMemberIds.has(t.id))) continue;
        ctx.setLineDash([3 / this.transform.k, 2 / this.transform.k]);
        ctx.strokeStyle = "rgba(200,146,56,0.4)";
      } else {
        if (!this.showEdges) continue;
        if (isolated && t.id !== isolated) continue;
        ctx.setLineDash([]);
        ctx.strokeStyle = isolated ? "rgba(31,91,99,0.35)" : "rgba(76,88,92,0.12)";
      }
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Person nodes
    let matchCount = 0;
    const matches = [];
    for (const n of this.nodes) {
      if (n.type !== "person") continue;
      const sc = n.scholar;
      const passesFilter = this._matchesFilters(sc);
      if (passesFilter) {
        matchCount++;
        if (this.searchWords.length) {
          matches.push({ scholar: sc, isNameMatch: this._isNameMatch(sc) });
        }
      }
      const dimmedByIsolation = isolated && !isolatedMemberIds.has(n.id);
      const dim = !passesFilter || dimmedByIsolation;
      const r = prominenceRadius(sc.n_citations);
      ctx.globalAlpha = dim ? 0.08 : 0.35 + sc.completeness * 0.5;
      ctx.fillStyle = n.color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fill();
    }
    this.matchCount = matchCount;
    if (this.searchWords.length) {
      matches.sort((a, b) => b.isNameMatch - a.isNameMatch);
      this.matches = matches;
    } else {
      this.matches = [];
    }
    ctx.globalAlpha = 1;

    // Hub nodes
    for (const n of this.nodes) {
      if (n.type !== "hub") continue;
      const dim = isolated && n.id !== isolated;
      ctx.globalAlpha = dim ? 0.25 : 0.92;
      const r = 5 + Math.sqrt(n.count) * 1.6;
      ctx.fillStyle = n.color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fill();
      if (this.transform.k > 0.35) {
        ctx.globalAlpha = dim ? 0.35 : 1;
        ctx.fillStyle = "#1E2A2E";
        ctx.font = `${11 / Math.max(this.transform.k, 0.6)}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(n.label, n.x, n.y - r - 4 / this.transform.k);
      }
    }
    ctx.globalAlpha = 1;

    // Hovered person label
    if (this.hoveredId) {
      const n = this.nodes.find((x) => x.id === this.hoveredId && x.type === "person");
      if (n) {
        ctx.fillStyle = "#1E2A2E";
        ctx.font = `${12 / this.transform.k}px Inter, sans-serif`;
        ctx.textAlign = "left";
        ctx.fillText(n.scholar.name, n.x + 7 / this.transform.k, n.y + 3 / this.transform.k);
      }
    }

    ctx.restore();
  }

  _screenToWorld(px, py) {
    return {
      x: (px - this.transform.x) / this.transform.k,
      y: (py - this.transform.y) / this.transform.k,
    };
  }

  _nodeAt(px, py) {
    const { x, y } = this._screenToWorld(px, py);
    let closest = null;
    let closestDist = Infinity;
    for (const n of this.nodes) {
      const r = n.type === "hub" ? 5 + Math.sqrt(n.count) * 1.6 : prominenceRadius(n.scholar.n_citations);
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < r + 3 && d < closestDist) {
        closest = n;
        closestDist = d;
      }
    }
    return closest;
  }

  _bindInteraction() {
    const canvas = this.canvas;
    let panStart = null;
    // Pointer Events unify mouse/touch/pen into one code path — needed for real
    // multi-touch pinch-zoom, which a mouse-only or parallel touch-listener
    // approach can't get "for free" the way tracking each pointer's id can.
    const pointers = new Map(); // pointerId -> {x, y}
    let pinch = null; // { lastDist }

    const pinchDist = () => {
      const pts = [...pointers.values()];
      return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    };
    const pinchMidpoint = () => {
      const pts = [...pointers.values()];
      return { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
    };

    canvas.addEventListener("pointerdown", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      pointers.set(e.pointerId, { x: px, y: py });
      canvas.setPointerCapture(e.pointerId);

      if (pointers.size === 2) {
        this.dragging = null;
        panStart = null;
        pinch = { lastDist: pinchDist() };
        return;
      }
      if (pointers.size !== 1) return;
      const node = this._nodeAt(px, py);
      if (node) {
        this.dragging = node;
        this.simulation.alphaTarget(0.15).restart();
      } else {
        panStart = { x: e.clientX - this.transform.x, y: e.clientY - this.transform.y };
      }
    });

    window.addEventListener("pointermove", (e) => {
      if (!pointers.has(e.pointerId)) {
        // Hover preview (mouse only — touch has no hover state before a tap).
        if (e.pointerType !== "touch" && !this.dragging && !panStart) {
          const rect = canvas.getBoundingClientRect();
          const px = e.clientX - rect.left;
          const py = e.clientY - rect.top;
          const node = this._nodeAt(px, py);
          this.hoveredId = node && node.type === "person" ? node.id : null;
          canvas.style.cursor = node ? "pointer" : "grab";
          this._draw();
        }
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      pointers.set(e.pointerId, { x: px, y: py });

      if (pointers.size === 2 && pinch) {
        const newDist = pinchDist();
        const factor = newDist / pinch.lastDist;
        const mid = pinchMidpoint();
        const worldBefore = this._screenToWorld(mid.x, mid.y);
        this.transform.k = Math.min(Math.max(this.transform.k * factor, 0.15), 6);
        this.transform.x = mid.x - worldBefore.x * this.transform.k;
        this.transform.y = mid.y - worldBefore.y * this.transform.k;
        pinch.lastDist = newDist;
        this._draw();
        return;
      }
      if (this.dragging) {
        const { x, y } = this._screenToWorld(px, py);
        this.dragging.fx = x;
        this.dragging.fy = y;
      } else if (panStart) {
        this.transform.x = e.clientX - panStart.x;
        this.transform.y = e.clientY - panStart.y;
        this._draw();
      }
    });

    const endPointer = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size === 0) {
        if (this.dragging) {
          this.dragging.fx = null;
          this.dragging.fy = null;
          if (this.simulation) this.simulation.alphaTarget(0);
        }
        this.dragging = null;
        panStart = null;
        pinch = null;
      } else if (pointers.size === 1) {
        // Dropped from two fingers to one — resume as a fresh pan from here,
        // rather than jumping using the old two-finger midpoint as the anchor.
        // `pointers` stores canvas-relative coords; panStart is compared against
        // client-space clientX/Y in pointermove, so convert back via the rect.
        const rect = canvas.getBoundingClientRect();
        const [remaining] = [...pointers.values()];
        panStart = {
          x: remaining.x + rect.left - this.transform.x,
          y: remaining.y + rect.top - this.transform.y,
        };
        pinch = null;
      }
    };
    window.addEventListener("pointerup", endPointer);
    window.addEventListener("pointercancel", endPointer);

    canvas.addEventListener("click", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const node = this._nodeAt(px, py);
      if (!node) return;
      if (node.type === "person") {
        this.onSelectPerson(node.scholar);
      } else if (node.type === "hub" && !this._subclustered) {
        // Sub-hubs (shown once a top-level hub is isolated and sub-grouped) cap at one
        // level of nesting for now — clicking one doesn't drill further.
        this.isolateHub(node.id);
      }
    });

    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const rect = canvas.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const worldBefore = this._screenToWorld(px, py);
        const factor = e.deltaY < 0 ? 1.1 : 0.9;
        this.transform.k = Math.min(Math.max(this.transform.k * factor, 0.15), 6);
        this.transform.x = px - worldBefore.x * this.transform.k;
        this.transform.y = py - worldBefore.y * this.transform.k;
        this._draw();
      },
      { passive: false }
    );
  }
}
