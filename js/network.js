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

class NetworkGraph {
  constructor(canvas, { onSelectPerson } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelectPerson = onSelectPerson || (() => {});
    this.scholars = [];
    this.groups = {};
    this.nodes = [];
    this.links = [];
    this.scholarById = new Map();
    this.activeAttr = "institution";
    this.showEdges = true;
    this.searchTerm = "";
    this.yearRange = null; // [min, max] or null
    this.transform = { x: 0, y: 0, k: 1 };
    this.isolatedHub = null;
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

  load(scholars, groups) {
    this.scholars = scholars;
    this.groups = groups;
    this.scholarById = new Map(scholars.map((s) => [s.id, s]));
    this.setAttribute(this.activeAttr, { warm: false });
  }

  setAttribute(attr, { warm = true } = {}) {
    this.activeAttr = attr;
    this.isolatedHub = null;
    const prevPositions = warm ? this._capturePositions() : null;
    this._buildNodesAndLinks(attr);
    if (prevPositions) this._restorePositions(prevPositions);
    this._startSimulation();
  }

  setShowEdges(show) {
    this.showEdges = show;
    this._draw();
  }

  setSearch(term) {
    this.searchTerm = term.trim().toLowerCase();
    this._draw();
  }

  setYearRange(range) {
    this.yearRange = range;
    this._draw();
  }

  isolateHub(hubId) {
    this.isolatedHub = this.isolatedHub === hubId ? null : hubId;
    this._draw();
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
          links.push({ source: memberId, target: hub.id });
          const pn = personById.get(memberId);
          if (pn) pn.color = hub.color;
        }
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
        d3.forceLink(links).id((d) => d.id).distance(38).strength(0.55)
      )
      .force("charge", d3.forceManyBody().strength((d) => (d.type === "hub" ? -220 : -32)))
      .force("collide", d3.forceCollide().radius((d) => (d.type === "hub" ? 22 : 4.5)))
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
    if (this.searchTerm) {
      const hay = (scholar.name + " " + scholar.institution.join(" ") + " " + scholar.program.join(" ")).toLowerCase();
      if (!hay.includes(this.searchTerm)) return false;
    }
    return true;
  }

  _draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);
    if (!this.nodes) return;

    ctx.save();
    ctx.translate(this.transform.x, this.transform.y);
    ctx.scale(this.transform.k, this.transform.k);

    const isolated = this.isolatedHub;
    const isolatedMemberIds = isolated
      ? new Set(this.links.filter((l) => l.target.id === isolated).map((l) => l.source.id))
      : null;

    // Edges
    if (this.showEdges) {
      ctx.lineWidth = 1 / this.transform.k;
      for (const l of this.links) {
        if (isolated && l.target.id !== isolated) continue;
        const s = l.source, t = l.target;
        if (typeof s !== "object" || typeof t !== "object") continue;
        ctx.strokeStyle = isolated ? "rgba(31,91,99,0.35)" : "rgba(76,88,92,0.12)";
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
      }
    }

    // Person nodes
    for (const n of this.nodes) {
      if (n.type !== "person") continue;
      const sc = n.scholar;
      const passesFilter = this._matchesFilters(sc);
      const dimmedByIsolation = isolated && !isolatedMemberIds.has(n.id);
      const dim = !passesFilter || dimmedByIsolation;
      const r = 2.4 + sc.completeness * 3.2;
      ctx.globalAlpha = dim ? 0.08 : 0.35 + sc.completeness * 0.5;
      ctx.fillStyle = n.color;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fill();
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
      const r = n.type === "hub" ? 5 + Math.sqrt(n.count) * 1.6 : 5;
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

    canvas.addEventListener("mousedown", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const node = this._nodeAt(px, py);
      if (node && node.type === "person") {
        this.dragging = node;
        this.simulation.alphaTarget(0.15).restart();
      } else if (node && node.type === "hub") {
        this.dragging = node;
        this.simulation.alphaTarget(0.15).restart();
      } else {
        panStart = { x: e.clientX - this.transform.x, y: e.clientY - this.transform.y };
      }
    });

    window.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      if (this.dragging) {
        const { x, y } = this._screenToWorld(px, py);
        this.dragging.fx = x;
        this.dragging.fy = y;
      } else if (panStart) {
        this.transform.x = e.clientX - panStart.x;
        this.transform.y = e.clientY - panStart.y;
        this._draw();
      } else {
        const node = this._nodeAt(px, py);
        this.hoveredId = node && node.type === "person" ? node.id : null;
        canvas.style.cursor = node ? "pointer" : "grab";
        this._draw();
      }
    });

    window.addEventListener("mouseup", () => {
      if (this.dragging) {
        this.dragging.fx = null;
        this.dragging.fy = null;
        if (this.simulation) this.simulation.alphaTarget(0);
      }
      this.dragging = null;
      panStart = null;
    });

    canvas.addEventListener("click", (e) => {
      const rect = canvas.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const node = this._nodeAt(px, py);
      if (!node) return;
      if (node.type === "person") {
        this.onSelectPerson(node.scholar);
      } else if (node.type === "hub") {
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
