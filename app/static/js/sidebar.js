/* Sidebar with page titles + drag-and-drop reorder.
   Works alongside app.js without modifying it. */
(() => {
  "use strict";

  const API = {
    async listPages(projectId) {
      const r = await fetch(`/api/projects/${projectId}/pages`);
      return handle(r);
    },
    async reorderPages(projectId, order) {
      const r = await fetch(`/api/projects/${projectId}/pages/reorder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      });
      return handle(r);
    },
    async updatePage(pageId, fields) {
      const r = await fetch(`/api/pages/${pageId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      return handle(r);
    },
  };

  async function handle(response) {
    let data = null;
    const text = await response.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = { raw: text }; }
    }
    if (!response.ok) {
      const msg = (data && (data.error || data.message)) || `HTTP ${response.status}`;
      throw new Error(msg);
    }
    return data;
  }

  const state = {
    projectId: null,
    pages: [],
    selectedIds: new Set(),
    dragSourceId: null,
  };

  const $ = (sel) => document.querySelector(sel);
  const el = {
    sidebar: $("#pageSidebar"),
    sidebarList: $("#sidebarList"),
    sidebarCount: $("#sidebarCount"),
    sidebarEmpty: $("#sidebarEmpty"),
    sidebarToggle: $("#sidebarToggle"),
    toast: $("#toast"),
  };

  /* ---------- Colour palette (cyclic) ----------
     Eight hues chosen to be distinguishable and pleasant in both
     light and dark UI contexts. The same colour is applied to the
     row's left border, number badge, and background tint. */
  const ROW_COLORS = [
    { name: "indigo",  fg: "#4f46e5", bg: "#eef2ff", bd: "#c7d2fe" },
    { name: "teal",    fg: "#0d9488", bg: "#ecfdf5", bd: "#a7f3d0" },
    { name: "amber",   fg: "#b45309", bg: "#fffbeb", bd: "#fde68a" },
    { name: "rose",    fg: "#be123c", bg: "#fff1f2", bd: "#fecdd3" },
    { name: "violet",  fg: "#7c3aed", bg: "#f5f3ff", bd: "#ddd6fe" },
    { name: "sky",     fg: "#0369a1", bg: "#f0f9ff", bd: "#bae6fd" },
    { name: "lime",    fg: "#4d7c0f", bg: "#f7fee7", bd: "#d9f99d" },
    { name: "fuchsia", fg: "#a21caf", bg: "#fdf4ff", bd: "#f5d0fe" },
  ];

  /* Deterministic string hash → 0..N-1. Used to colour the file chip
     so pages from the same source file share a hue. */
  function hashIndex(str, mod) {
    let h = 0;
    const s = String(str || "");
    for (let i = 0; i < s.length; i++) {
      h = (h * 31 + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h) % mod;
  }

  /* ---------- Helpers ---------- */
  function toast(msg, type = "") {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.className = "toast " + type;
    el.toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.toast.hidden = true; }, 2600);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function shortFileStem(name) {
    const stem = String(name || "PDF").replace(/\.pdf$/i, "");
    return stem.length > 18 ? stem.slice(0, 17) + "…" : stem;
  }

  function titleFor(page, idx) {
    if (page.title && page.title.trim()) return page.title.trim();
    const fname = page.file_name || "PDF";
    const stem = fname.replace(/\.pdf$/i, "");
    const isSplitChild = !!page.parent_page_id;
    const suffix = isSplitChild
      ? `p${page.original_page_number} (split)`
      : `p${page.original_page_number}`;
    return `${idx + 1}. ${stem} – ${suffix}`;
  }

  /* ---------- Rendering ---------- */
  function render() {
    if (!el.sidebarList) return;

    el.sidebarCount.textContent = state.pages.length;
    el.sidebarList.innerHTML = "";
    el.sidebarEmpty.hidden = state.pages.length > 0;

    const frag = document.createDocumentFragment();
    state.pages.forEach((p, idx) => {
      frag.appendChild(buildRow(p, idx));
    });
    el.sidebarList.appendChild(frag);
  }

  function buildRow(page, idx) {
    const row = document.createElement("li");
    row.className = "sidebar-row";
    row.dataset.pageId = page._id;
    row.dataset.index = idx;
    row.draggable = true;

    // Cycle through the palette by index so adjacent rows always contrast.
    const c = ROW_COLORS[idx % ROW_COLORS.length];

    // File chip gets a stable colour based on the file name hash.
    const fileColor = ROW_COLORS[hashIndex(page.file_name || "PDF", ROW_COLORS.length)];

    // CSS custom properties drive border, badge, and tint.
    row.style.setProperty("--row-fg", c.fg);
    row.style.setProperty("--row-bg", c.bg);
    row.style.setProperty("--row-bd", c.bd);
    row.style.setProperty("--file-fg", fileColor.fg);
    row.style.setProperty("--file-bg", fileColor.bg);
    row.style.setProperty("--file-bd", fileColor.bd);

    if (state.selectedIds.has(page._id)) row.classList.add("selected");
    if (page._id === state.dragSourceId) row.classList.add("dragging");

    const label = titleFor(page, idx);
    const shortFile = shortFileStem(page.file_name);

    // Status pills
    const pills = [];
    if (page.parent_page_id) {
      pills.push(`<span class="status-pill pill-split" title="Split child">✂</span>`);
    }
    if (page.rotation && page.rotation !== 0) {
      pills.push(`<span class="status-pill pill-rot" title="Rotated ${page.rotation}°">↻${page.rotation}</span>`);
    }
    if (page.crop) {
      pills.push(`<span class="status-pill pill-crop" title="Cropped">▣</span>`);
    }

    row.innerHTML = `
      <span class="drag-handle" title="Drag to reorder" aria-hidden="true">⋮⋮</span>
      <span class="sidebar-number" title="Position ${idx + 1}">${idx + 1}</span>
      <div class="sidebar-body">
        <input type="text"
               class="sidebar-title"
               value="${escapeHtml(label)}"
               data-page-id="${page._id}"
               aria-label="Page title" />
        <div class="sidebar-meta">
          <span class="file-chip" title="${escapeHtml(page.file_name || "")}">
            ${escapeHtml(shortFile)} · p${page.original_page_number}
          </span>
          <span class="pills">${pills.join("")}</span>
        </div>
      </div>
      <button class="sidebar-go" type="button" title="Jump to page in grid">→</button>
    `;

    const input = row.querySelector(".sidebar-title");

    input.addEventListener("focus", () => {
      input.dataset.original = input.value;
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); input.blur(); }
      if (e.key === "Escape") {
        input.value = input.dataset.original || input.value;
        input.blur();
      }
    });

    input.addEventListener("blur", async () => {
      const original = input.dataset.original || "";
      const next = input.value.trim();
      if (next === original) return;
      try {
        await API.updatePage(page._id, { title: next });
        page.title = next;
        toast("Title saved", "success");
      } catch (err) {
        input.value = original;
        toast(err.message, "error");
      }
    });

    input.addEventListener("mousedown", (e) => e.stopPropagation());
    input.addEventListener("dragstart", (e) => e.preventDefault());

    row.querySelector(".sidebar-go").addEventListener("click", (e) => {
      e.stopPropagation();
      const target = document.querySelector(
        `.page-card[data-page-id="${page._id}"]`
      );
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.add("flash");
        setTimeout(() => target.classList.remove("flash"), 900);
      }
    });

    /* --- Drag & drop --- */
    row.addEventListener("dragstart", (e) => {
      if (e.target === input) { e.preventDefault(); return; }
      state.dragSourceId = page._id;
      row.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", page._id);
      el.sidebarList.classList.add("drag-active");
    });

    row.addEventListener("dragend", () => {
      state.dragSourceId = null;
      row.classList.remove("dragging");
      el.sidebarList.classList.remove("drag-active");
      el.sidebarList
        .querySelectorAll(".drag-over-top, .drag-over-bottom")
        .forEach(n => n.classList.remove("drag-over-top", "drag-over-bottom"));
    });

    row.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (!state.dragSourceId || state.dragSourceId === page._id) return;

      const rect = row.getBoundingClientRect();
      const isTopHalf = (e.clientY - rect.top) < rect.height / 2;

      el.sidebarList
        .querySelectorAll(".drag-over-top, .drag-over-bottom")
        .forEach(n => n.classList.remove("drag-over-top", "drag-over-bottom"));

      row.classList.add(isTopHalf ? "drag-over-top" : "drag-over-bottom");
      e.dataTransfer.dropEffect = "move";
    });

    row.addEventListener("dragleave", () => {
      row.classList.remove("drag-over-top", "drag-over-bottom");
    });

    row.addEventListener("drop", async (e) => {
      e.preventDefault();
      const isTopHalf = row.classList.contains("drag-over-top");
      row.classList.remove("drag-over-top", "drag-over-bottom");

      const draggedId = e.dataTransfer.getData("text/plain") || state.dragSourceId;
      if (!draggedId || draggedId === page._id) return;

      await movePage(draggedId, page._id, isTopHalf ? "before" : "after");
    });

    return row;
  }

  /* ---------- Reorder ---------- */
  async function movePage(draggedId, targetId, position) {
    const pages = state.pages.slice();
    const from = pages.findIndex(p => p._id === draggedId);
    if (from < 0) return;
    const [moved] = pages.splice(from, 1);

    let to = pages.findIndex(p => p._id === targetId);
    if (to < 0) return;
    if (position === "after") to += 1;

    pages.splice(to, 0, moved);

    state.pages = pages;
    render();

    try {
      await API.reorderPages(state.projectId, pages.map(p => p._id));
      document.dispatchEvent(new CustomEvent("pages:refresh"));
      toast("Order saved", "success");
    } catch (err) {
      toast(err.message, "error");
      await reload();
    }
  }

  /* ---------- Data load ---------- */
  async function reload() {
    if (!state.projectId) {
      state.pages = [];
      render();
      return;
    }
    try {
      const pages = await API.listPages(state.projectId);
      state.pages = pages || [];
      render();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  /* ---------- Public API (used by app.js) ---------- */
  window.PageSidebar = {
    setProject(projectId) {
      state.projectId = projectId;
      reload();
    },
    clear() {
      state.projectId = null;
      state.pages = [];
      render();
    },
    reload,
    setPages(pages) {
      state.pages = pages || [];
      render();
    },
  };

  /* ---------- Toggle (mobile) ---------- */
  function wireToggle() {
    if (!el.sidebarToggle || !el.sidebar) return;
    el.sidebarToggle.addEventListener("click", () => {
      el.sidebar.classList.toggle("open");
    });
  }

  /* ---------- Init ---------- */
  document.addEventListener("DOMContentLoaded", () => {
    wireToggle();
    render();

    document.addEventListener("pages:changed", () => {
      reload();
    });
  });
})();