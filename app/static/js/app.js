/* PDF Merger – frontend logic */
(() => {
  "use strict";

  /* ---------- Sidebar bridge ----------
     The sidebar module (sidebar.js) listens for these events so it can
     re-render its list whenever the grid changes (upload, delete,
     split, duplicate, reorder, undo). */
  function syncSidebar(pages) {
    if (window.PageSidebar && typeof window.PageSidebar.setPages === "function") {
      window.PageSidebar.setPages(pages);
    }
  }

  const API = {
    async createProject(name) {
      const r = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_name: name }),
      });
      return handle(r);
    },
    async getProject(id) { return handle(await fetch(`/api/projects/${id}`)); },
    async listPages(id) { return handle(await fetch(`/api/projects/${id}/pages`)); },
    async reorderPages(id, order) {
      return handle(await fetch(`/api/projects/${id}/pages/reorder`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      }));
    },
    async updatePage(pageId, fields) {
      return handle(await fetch(`/api/pages/${pageId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      }));
    },
    async deletePage(pageId) {
      return handle(await fetch(`/api/pages/${pageId}`, { method: "DELETE" }));
    },
    async duplicatePage(pageId) {
      return handle(await fetch(`/api/pages/${pageId}/duplicate`, { method: "POST" }));
    },
    async merge(id) {
      return handle(await fetch(`/api/projects/${id}/merge`, { method: "POST" }));
    },
    async splitPage(pageId, opts) {
      return handle(await fetch(`/api/pages/${pageId}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(opts || {}),
      }));
    },
    async getPageSize(pageId) {
      return handle(await fetch(`/api/pages/${pageId}/size`));
    },
    async compress(id, preset = "medium") {
      return handle(await fetch(`/api/projects/${id}/compress`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset }),
      }));
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

  /* ---------- State ---------- */
  const state = {
    projectId: null,
    pages: [],           // ordered list of visible pages
    deletedPages: [],    // undo buffer
    selected: new Set(),
    previewIndex: -1,
    previewZoom: 1,
    // --- crop ---
    cropMode: false,
    cropRect: null,   // { x0, y0, x1, y1 } in *image pixel* coordinates
  };

  /* ---------- DOM refs ---------- */
  const $ = (sel) => document.querySelector(sel);
  const el = {
    dropZone: $("#dropZone"),
    fileInput: $("#fileInput"),
    selectFilesBtn: $("#selectFilesBtn"),
    addMoreBtn: $("#addMoreBtn"),
    newProjectBtn: $("#newProjectBtn"),
    mergeBtn: $("#mergeBtn"),
    compressBtn: $("#compressBtn"),
    undoDeleteBtn: $("#undoDeleteBtn"),
    uploadProgress: $("#uploadProgress"),
    progressFill: $("#progressFill"),
    progressText: $("#progressText"),
    toolbar: $("#toolbar"),
    pageCountLabel: $("#pageCountLabel"),
    selectedCount: $("#selectedCount"),
    pagesSection: $("#pagesSection"),
    pagesGrid: $("#pagesGrid"),
    successSection: $("#successSection"),
    successInfo: $("#successInfo"),
    downloadLink: $("#downloadLink"),
    projectLabel: $("#projectLabel"),
    toast: $("#toast"),
    previewModal: $("#previewModal"),
    previewImage: $("#previewImage"),
    previewTitle: $("#previewTitle"),
    prevPageBtn: $("#prevPageBtn"),
    nextPageBtn: $("#nextPageBtn"),
    zoomInBtn: $("#zoomInBtn"),
    zoomOutBtn: $("#zoomOutBtn"),
    closePreviewBtn: $("#closePreviewBtn"),

    cropToggleBtn: $("#cropToggleBtn"),
    cropClearBtn: $("#cropClearBtn"),
    cropSaveBtn: $("#cropSaveBtn"),
    cropOverlay: $("#cropOverlay"),
    cropBox: $("#cropBox"),
    cropStage: $("#cropStage"),
    imageWrap: $("#imageWrap"),
  };

  /* ---------- Helpers ---------- */
  function toast(msg, type = "") {
    el.toast.textContent = msg;
    el.toast.className = "toast " + type;
    el.toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.toast.hidden = true; }, 3000);
  }

  function fmtSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0, n = bytes;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  /* ---------- Project bootstrap ---------- */
  async function ensureProject() {
    if (state.projectId) return state.projectId;
    const project = await API.createProject("PDF Merge Session");
    state.projectId = project._id;
    el.projectLabel.hidden = false;
    el.projectLabel.textContent = `Project: ${project.project_name}`;
    if (window.PageSidebar && window.PageSidebar.setProject) {
      window.PageSidebar.setProject(state.projectId);
    }
    return state.projectId;
  }

  async function newProject() {
    state.projectId = null;
    state.pages = [];
    state.deletedPages = [];
    state.selected.clear();
    el.successSection.hidden = true;
    el.toolbar.hidden = true;
    el.pagesSection.hidden = true;
    el.projectLabel.hidden = true;
    if (el.compressBtn) el.compressBtn.hidden = true;
    if (window.PageSidebar && window.PageSidebar.clear) {
      window.PageSidebar.clear();
    }
    renderPages();
  }

  /* ---------- Upload ---------- */
  async function uploadFiles(files) {
    const pdfs = Array.from(files).filter(f => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    if (!pdfs.length) { toast("Please select PDF files only", "error"); return; }

    el.uploadProgress.hidden = false;
    el.progressFill.style.width = "0%";
    el.progressText.textContent = `Uploading ${pdfs.length} file(s)…`;

    try {
      await ensureProject();
    } catch (e) {
      el.uploadProgress.hidden = true;
      toast(e.message, "error");
      return;
    }

    const fd = new FormData();
    pdfs.forEach(f => fd.append("files", f, f.name));

    try {
      const data = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `/api/projects/${state.projectId}/upload`);
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            el.progressFill.style.width = pct + "%";
            el.progressText.textContent = `Uploading… ${pct}%`;
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try { resolve(JSON.parse(xhr.responseText)); }
            catch { resolve({}); }
          } else {
            let msg = `HTTP ${xhr.status}`;
            try { msg = JSON.parse(xhr.responseText).error || msg; } catch {}
            reject(new Error(msg));
          }
        };
        xhr.onerror = () => reject(new Error("Network error during upload"));
        xhr.send(fd);
      });

      el.progressFill.style.width = "100%";
      el.progressText.textContent = "Upload complete";
      setTimeout(() => { el.uploadProgress.hidden = true; }, 800);

      await refreshPages();
      el.successSection.hidden = true;
      if (data && data.skipped_count) {
        toast(`${pdfs.length} file(s) uploaded · ${data.skipped_count} blank page(s) skipped`, "success");
      } else {
        toast(`${pdfs.length} file(s) uploaded`, "success");
      }
    } catch (e) {
      el.uploadProgress.hidden = true;
      toast(e.message, "error");
    }
  }

  /* ---------- Page rendering ---------- */
  async function refreshPages() {
    if (!state.projectId) return;
    const pages = await API.listPages(state.projectId);
    state.pages = pages;
    renderPages();
  }

  function renderPages() {
    const pages = state.pages;
    el.pagesGrid.innerHTML = "";

    if (!pages.length) {
      el.toolbar.hidden = true;
      el.pagesSection.hidden = true;
      syncSidebar([]);
      return;
    }
    el.toolbar.hidden = false;
    el.pagesSection.hidden = false;

    const frag = document.createDocumentFragment();
    pages.forEach((p, idx) => frag.appendChild(buildPageCard(p, idx)));
    el.pagesGrid.appendChild(frag);

    el.pageCountLabel.textContent = `${pages.length} page${pages.length === 1 ? "" : "s"}`;
    updateSelectedCount();
    el.undoDeleteBtn.hidden = state.deletedPages.length === 0;
    syncSidebar(pages);
  }

  function buildPageCard(page, index) {
    const card = document.createElement("div");
    card.className = "page-card";
    card.draggable = true;
    card.dataset.pageId = page._id;
    card.dataset.index = index;

    if (state.selected.has(page._id)) card.classList.add("selected");

    const rot = page.rotation || 0;
    // ?ts=${Date.now()}
    card.innerHTML = `
      <div class="page-thumb-wrap">
        <img class="page-thumb"
             src="/api/pages/${page._id}/thumbnail"
             alt="Page ${index + 1}"
             loading="lazy"
             style="transform: rotate(${rot}deg) scale(${rot % 180 === 90 ? 0.75 : 1})" />
        <span class="page-index">${index + 1}</span>
        ${page.crop ? '<span class="page-badge" title="Cropped page">✂</span>' : ''}
      </div>
      <div class="page-name" title="${escapeHtml(page.file_name || "")}">
        ${escapeHtml(page.file_name || "PDF")} – p${page.original_page_number}
      </div>
      <div class="page-actions">
        <button class="btn btn-icon" data-action="rotate-left" title="Rotate left">⟲</button>
        <button class="btn btn-icon" data-action="split" title="Split page">✂</button>
        <button class="btn btn-icon" data-action="duplicate" title="Duplicate">⧉</button>
        <button class="btn btn-icon" data-action="select" title="Select">✓</button>
        <button class="btn btn-icon" data-action="rotate-right" title="Rotate right">⟳</button>
        <button class="btn btn-icon btn-danger" data-action="delete" title="Delete">✕</button>
      </div>
    `;

    // Open preview
    card.querySelector(".page-thumb-wrap").addEventListener("click", () => openPreview(index));
    card.querySelector(".page-name").addEventListener("click", () => openPreview(index));

    // Action buttons
    card.addEventListener("click", async (e) => {
      const btn = e.target.closest("button[data-action]");
      if (!btn) return;
      e.stopPropagation();
      const action = btn.dataset.action;
      try {
        if (action === "rotate-left")  await rotatePage(page._id, -90);
        if (action === "rotate-right") await rotatePage(page._id, 90);
        if (action === "duplicate")    await duplicatePage(page._id);
        if (action === "delete")       await deletePage(page);
        if (action === "select")       toggleSelect(page._id);
        if (action === "split")        await openSplitDialog(page);
      } catch (err) { toast(err.message, "error"); }
    });

    // Drag & drop
    card.addEventListener("dragstart", (e) => {
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", page._id);
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.querySelectorAll(".drag-over").forEach(n => n.classList.remove("drag-over"));
    });
    card.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", async (e) => {
      e.preventDefault();
      card.classList.remove("drag-over");
      const draggedId = e.dataTransfer.getData("text/plain");
      if (!draggedId || draggedId === page._id) return;
      await movePage(draggedId, page._id);
    });

    return card;
  }

  function toggleSelect(pageId) {
    if (state.selected.has(pageId)) state.selected.delete(pageId);
    else state.selected.add(pageId);
    renderPages();
  }

  function updateSelectedCount() {
    const n = state.selected.size;
    el.selectedCount.hidden = n === 0;
    el.selectedCount.textContent = n ? `${n} selected` : "";
  }

  /* ---------- Page operations ---------- */
  async function rotatePage(pageId, delta) {
    const page = state.pages.find(p => p._id === pageId);
    if (!page) return;
    const newRot = ((page.rotation || 0) + delta + 360) % 360;
    await API.updatePage(pageId, { rotation: newRot });
    page.rotation = newRot;
    renderPages();
    if (state.previewIndex >= 0) {
      const idx = state.pages.findIndex(p => p._id === pageId);
      if (idx === state.previewIndex) loadPreviewImage(idx);
    }
  }

  async function duplicatePage(pageId) {
    await API.duplicatePage(pageId);
    await refreshPages();
    toast("Page duplicated", "success");
  }

  async function deletePage(page) {
    if (!confirm(`Delete page (${page.file_name} – p${page.original_page_number})?`)) return;
    await API.deletePage(page._id);
    state.deletedPages.push(page);
    state.pages = state.pages.filter(p => p._id !== page._id);
    state.selected.delete(page._id);
    renderPages();
    toast("Page deleted", "");
  }

  async function undoDelete() {
    const page = state.deletedPages.pop();
    if (!page) return;
    await API.updatePage(page._id, { deleted: false });
    await refreshPages();
    toast("Page restored", "success");
  }

  async function movePage(draggedId, targetId) {
    const pages = state.pages.slice();
    const from = pages.findIndex(p => p._id === draggedId);
    const to   = pages.findIndex(p => p._id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = pages.splice(from, 1);
    pages.splice(to, 0, moved);
    state.pages = pages;
    renderPages();
    try {
      await API.reorderPages(state.projectId, pages.map(p => p._id));
    } catch (e) {
      toast(e.message, "error");
      await refreshPages();
    }
  }

  /* ---------- Split page ---------- */
  async function openSplitDialog(page) {
    let size;
    try { size = await API.getPageSize(page._id); }
    catch (e) { toast(e.message, "error"); return; }

    const isLandscape = size.width >= size.height;
    const defaultDir = isLandscape ? "vertical" : "horizontal";

    const dir = prompt(
      `Split page (${Math.round(size.width)}×${Math.round(size.height)} pts)\n\n` +
      `Enter direction:\n` +
      `  v = vertical (left / right)\n` +
      `  h = horizontal (top / bottom)\n\n` +
      `Default: ${defaultDir === "vertical" ? "v" : "h"}`,
      defaultDir === "vertical" ? "v" : "h"
    );
    if (dir === null) return;

    const direction = (dir.trim().toLowerCase().startsWith("h"))
      ? "horizontal" : "vertical";

    const ratioStr = prompt("Split position (0.05–0.95). 0.5 = middle.", "0.5");
    if (ratioStr === null) return;
    const ratio = parseFloat(ratioStr);
    if (isNaN(ratio) || ratio < 0.05 || ratio > 0.95) {
      toast("Invalid ratio", "error");
      return;
    }

    const gutterStr = prompt(
      "Optional gutter (points) to trim from the split edge.\nUse for scanned book spreads. Enter 0 for none.",
      "0"
    );
    if (gutterStr === null) return;
    const gutter = parseFloat(gutterStr) || 0;

    try {
      await API.splitPage(page._id, { direction, ratio, gutter });
      await refreshPages();
      toast("Page split into two", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  }

  /* ---------- Preview modal ---------- */
  function openPreview(index) {
    if (index < 0 || index >= state.pages.length) return;
    state.previewIndex = index;
    state.previewZoom = 1;
    el.previewModal.hidden = false;
    loadPreviewImage(index);
  }

  function closePreview() {
    if (state.cropMode) exitCropMode();
    state.previewIndex = -1;
    el.previewModal.hidden = true;
    el.previewImage.src = "";
  }

  function loadPreviewImage(index) {
    const page = state.pages[index];
    if (!page) return;
    el.previewTitle.textContent = `${page.file_name} – page ${page.original_page_number} (${index + 1}/${state.pages.length})`;
    el.previewImage.style.width = `${state.previewZoom * 100}%`;
    el.previewImage.src = `/api/pages/${page._id}/preview?ts=${Date.now()}`;
  }

  function previewPrev() {
    if (state.previewIndex > 0) {
      state.previewIndex--;
      loadPreviewImage(state.previewIndex);
    }
  }

  function previewNext() {
    if (state.previewIndex < state.pages.length - 1) {
      state.previewIndex++;
      loadPreviewImage(state.previewIndex);
    }
  }

  /* ============================================================
   CROP TOOL
   ============================================================ */

let cropDrag = null;   // { mode: 'move'|'resize', handle: string, startX, startY, origRect }

function enterCropMode() {
  const page = state.pages[state.previewIndex];
  if (!page) return;

  state.cropMode = true;
  state.previewZoom = 1;
  el.previewImage.style.width = "100%";

  el.previewModal.querySelector(".modal-body").classList.add("crop-mode");
  el.cropToggleBtn.hidden = true;
  el.cropSaveBtn.hidden = false;
  el.cropClearBtn.hidden = false;

  // If the page already has a crop, load it. Otherwise start with 10% inset.
  const img = el.previewImage;
  const ready = img.complete ? Promise.resolve() : new Promise(r => img.onload = r);
  ready.then(() => {
    const W = img.clientWidth;
    const H = img.clientHeight;

    if (page.crop && page._pageSize) {
      // Convert stored PDF pts -> image px
      const sz = page._pageSize;
      const sx = W / sz.width;
      const sy = H / sz.height;
      state.cropRect = {
        x0: (page.crop.x0 - sz.x0) * sx,
        y0: (page.crop.y0 - sz.y0) * sy,
        x1: (page.crop.x1 - sz.x0) * sx,
        y1: (page.crop.y1 - sz.y0) * sy,
      };
    } else {
      state.cropRect = {
        x0: W * 0.1, y0: H * 0.1,
        x1: W * 0.9, y1: H * 0.9,
      };
    }
    el.cropOverlay.hidden = false;
    paintCropRect();
    attachCropListeners();
  });
}

function exitCropMode() {
  state.cropMode = false;
  state.cropRect = null;
  el.previewModal.querySelector(".modal-body").classList.remove("crop-mode");
  el.cropToggleBtn.hidden = false;
  el.cropSaveBtn.hidden = true;
  el.cropClearBtn.hidden = true;
  el.cropOverlay.hidden = true;
  detachCropListeners();
}

function paintCropRect() {
  const r = state.cropRect;
  if (!r) return;
  el.cropBox.style.left = `${r.x0}px`;
  el.cropBox.style.top = `${r.y0}px`;
  el.cropBox.style.width = `${r.x1 - r.x0}px`;
  el.cropBox.style.height = `${r.y1 - r.y0}px`;
}

function clampCropRect(rect) {
  const W = el.previewImage.clientWidth;
  const H = el.previewImage.clientHeight;
  const MIN = 30; // minimum crop size in px
  let { x0, y0, x1, y1 } = rect;
  if (x0 > x1) [x0, x1] = [x1, x0];
  if (y0 > y1) [y0, y1] = [y1, y0];
  x0 = Math.max(0, Math.min(x0, W - MIN));
  y0 = Math.max(0, Math.min(y0, H - MIN));
  x1 = Math.max(x0 + MIN, Math.min(x1, W));
  y1 = Math.max(y0 + MIN, Math.min(y1, H));
  return { x0, y0, x1, y1 };
}

function attachCropListeners() {
  el.cropBox.addEventListener("mousedown", onCropMouseDown);
  el.cropBox.addEventListener("touchstart", onCropTouchStart, { passive: false });
  el.cropOverlay.querySelectorAll(".crop-handle").forEach(h => {
    h.addEventListener("mousedown", (e) => onHandleMouseDown(e, h.dataset.handle));
    h.addEventListener("touchstart",
      (e) => onHandleTouchStart(e, h.dataset.handle), { passive: false });
  });
}

function detachCropListeners() {
  el.cropBox.removeEventListener("mousedown", onCropMouseDown);
  el.cropBox.removeEventListener("touchstart", onCropTouchStart);
  el.cropOverlay.querySelectorAll(".crop-handle").forEach(h => {
    h.replaceWith(h.cloneNode(true));  // cheap detach
  });
}

/* --- move --- */
function onCropMouseDown(e) {
  e.preventDefault();
  startDrag("move", null, e.clientX, e.clientY);
  window.addEventListener("mousemove", onDragMove);
  window.addEventListener("mouseup", onDragEnd);
}
function onCropTouchStart(e) {
  e.preventDefault();
  const t = e.touches[0];
  startDrag("move", null, t.clientX, t.clientY);
  window.addEventListener("touchmove", onDragMoveTouch, { passive: false });
  window.addEventListener("touchend", onDragEnd);
}

/* --- resize --- */
function onHandleMouseDown(e, handle) {
  e.preventDefault(); e.stopPropagation();
  startDrag("resize", handle, e.clientX, e.clientY);
  window.addEventListener("mousemove", onDragMove);
  window.addEventListener("mouseup", onDragEnd);
}
function onHandleTouchStart(e, handle) {
  e.preventDefault(); e.stopPropagation();
  const t = e.touches[0];
  startDrag("resize", handle, t.clientX, t.clientY);
  window.addEventListener("touchmove", onDragMoveTouch, { passive: false });
  window.addEventListener("touchend", onDragEnd);
}

function startDrag(mode, handle, x, y) {
  cropDrag = {
    mode, handle,
    startX: x, startY: y,
    origRect: { ...state.cropRect },
  };
}

function onDragMove(e) {
  if (!cropDrag) return;
  updateDrag(e.clientX, e.clientY);
}
function onDragMoveTouch(e) {
  if (!cropDrag) return;
  const t = e.touches[0];
  updateDrag(t.clientX, t.clientY);
}

function updateDrag(x, y) {
  const dx = x - cropDrag.startX;
  const dy = y - cropDrag.startY;
  const o = cropDrag.origRect;
  let r;

  if (cropDrag.mode === "move") {
    r = { x0: o.x0 + dx, y0: o.y0 + dy, x1: o.x1 + dx, y1: o.y1 + dy };
    // Clamp to image bounds
    const W = el.previewImage.clientWidth;
    const H = el.previewImage.clientHeight;
    const w = r.x1 - r.x0, h = r.y1 - r.y0;
    if (r.x0 < 0) { r.x0 = 0; r.x1 = w; }
    if (r.y0 < 0) { r.y0 = 0; r.y1 = h; }
    if (r.x1 > W) { r.x1 = W; r.x0 = W - w; }
    if (r.y1 > H) { r.y1 = H; r.y0 = H - h; }
  } else {
    r = { ...o };
    if (cropDrag.handle.includes("w")) r.x0 = o.x0 + dx;
    if (cropDrag.handle.includes("e")) r.x1 = o.x1 + dx;
    if (cropDrag.handle.includes("n")) r.y0 = o.y0 + dy;
    if (cropDrag.handle.includes("s")) r.y1 = o.y1 + dy;
  }

  state.cropRect = clampCropRect(r);
  paintCropRect();
}

function onDragEnd() {
  cropDrag = null;
  window.removeEventListener("mousemove", onDragMove);
  window.removeEventListener("mouseup", onDragEnd);
  window.removeEventListener("touchmove", onDragMoveTouch);
  window.removeEventListener("touchend", onDragEnd);
}

/* --- save / clear --- */
async function saveCrop() {
  const page = state.pages[state.previewIndex];
  if (!page || !state.cropRect) return;

  // Convert image px -> PDF pts using the page's natural size.
  // We fetch the size if we don't already have it.
  let sz = page._pageSize;
  if (!sz) {
    try {
      sz = await API.getPageSize(page._id);
      page._pageSize = sz;
    } catch (e) {
      toast(e.message, "error");
      return;
    }
  }

  const imgW = el.previewImage.clientWidth;
  const imgH = el.previewImage.clientHeight;
  const sx = sz.width / imgW;
  const sy = sz.height / imgH;
  const r = state.cropRect;

  const crop = {
    x0: sz.x0 + r.x0 * sx,
    y0: sz.y0 + r.y0 * sy,
    x1: sz.x0 + r.x1 * sx,
    y1: sz.y0 + r.y1 * sy,
  };

  try {
    await API.updatePage(page._id, { crop });
    page.crop = crop;
    // Bust the thumbnail cache
    renderPages();
    toast("Crop saved", "success");
    exitCropMode();
    // Reload preview so user sees the cropped result
    loadPreviewImage(state.previewIndex);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function clearCrop() {
  const page = state.pages[state.previewIndex];
  if (!page) return;
  try {
    await API.updatePage(page._id, { crop: null });
    page.crop = null;
    renderPages();
    toast("Crop cleared", "success");
    exitCropMode();
    loadPreviewImage(state.previewIndex);
  } catch (e) {
    toast(e.message, "error");
  }
}

  /* ---------- Merge ---------- */
  async function mergeProject() {
    if (!state.projectId || !state.pages.length) {
      toast("Upload at least one PDF first", "error");
      return;
    }
    el.mergeBtn.disabled = true;
    el.mergeBtn.textContent = "Merging…";
    try {
      const res = await API.merge(state.projectId);
      el.successSection.hidden = false;
      el.successInfo.textContent = `${res.page_count} pages · ${res.output_filename}`;
      el.downloadLink.href = res.download_url;
      el.downloadLink.setAttribute("download", res.output_filename);
      el.successSection.scrollIntoView({ behavior: "smooth", block: "center" });
      toast("Merged PDF ready!", "success");
      if (el.compressBtn) el.compressBtn.hidden = false;
    } catch (e) {
      toast(e.message, "error");
    } finally {
      el.mergeBtn.disabled = false;
      el.mergeBtn.textContent = "🔗 Merge & Create PDF";
    }
  }

  /* ---------- Compress ---------- */
  async function compressProject() {
    if (!state.projectId) {
      toast("Merge a project first", "error");
      return;
    }

    const choice = prompt(
      "Choose compression level:\n" +
      "  low     — light (best quality)\n" +
      "  medium  — balanced (default)\n" +
      "  high    — strong\n" +
      "  extreme — maximum (lowest quality)",
      "medium"
    );
    if (choice === null) return;

    const preset = choice.trim().toLowerCase();
    if (!["low", "medium", "high", "extreme"].includes(preset)) {
      toast("Invalid preset", "error");
      return;
    }

    el.compressBtn.disabled = true;
    el.compressBtn.textContent = "Compressing…";
    try {
      const res = await API.compress(state.projectId, preset);
      const kb = (n) => (n / 1024).toFixed(1) + " KB";
      el.successSection.hidden = false;
      el.successInfo.textContent =
        `Compressed (${res.preset}): ${kb(res.input_size)} → ${kb(res.output_size)} ` +
        `(${res.saved_pct}% saved) · ${res.output_filename}`;
      el.downloadLink.href = res.download_url;
      el.downloadLink.setAttribute("download", res.output_filename);
      el.successSection.scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Compressed! Saved ${res.saved_pct}%`, "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      el.compressBtn.disabled = false;
      el.compressBtn.textContent = "🗜 Compress PDF";
    }
  }

  /* ---------- Event wiring ---------- */
  function wireEvents() {
    el.selectFilesBtn.addEventListener("click", (e) => { e.stopPropagation(); el.fileInput.click(); });
    el.addMoreBtn.addEventListener("click", () => el.fileInput.click());
    el.dropZone.addEventListener("click", () => el.fileInput.click());
    el.dropZone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.fileInput.click(); }
    });

    el.fileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files.length) {
        uploadFiles(e.target.files);
        e.target.value = "";
      }
    });

    ["dragenter", "dragover"].forEach(evt =>
      el.dropZone.addEventListener(evt, (e) => {
        e.preventDefault(); e.stopPropagation();
        el.dropZone.classList.add("dragover");
      })
    );

    ["dragleave", "drop"].forEach(evt =>
      el.dropZone.addEventListener(evt, (e) => {
        e.preventDefault(); e.stopPropagation();
        el.dropZone.classList.remove("dragover");
      })
    );

    el.dropZone.addEventListener("drop", (e) => {
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) uploadFiles(files);
    });

    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => e.preventDefault());

    el.mergeBtn.addEventListener("click", mergeProject);
    if (el.compressBtn) el.compressBtn.addEventListener("click", compressProject);
    el.undoDeleteBtn.addEventListener("click", undoDelete);
    el.newProjectBtn.addEventListener("click", () => {
      if (confirm("Start a new project? Current session will be cleared from the UI.")) newProject();
    });

    // Preview modal
    el.closePreviewBtn.addEventListener("click", closePreview);
    el.previewModal.querySelector("[data-close]").addEventListener("click", closePreview);
    el.prevPageBtn.addEventListener("click", previewPrev);
    el.nextPageBtn.addEventListener("click", previewNext);
    el.zoomInBtn.addEventListener("click", () => {
      state.previewZoom = Math.min(3, state.previewZoom + 0.25);
      el.previewImage.style.width = `${state.previewZoom * 100}%`;
    });
    el.zoomOutBtn.addEventListener("click", () => {
      state.previewZoom = Math.max(0.4, state.previewZoom - 0.25);
      el.previewImage.style.width = `${state.previewZoom * 100}%`;
    });

    document.addEventListener("keydown", (e) => {
      if (el.previewModal.hidden) return;
      if (state.cropMode) {
        if (e.key === "Escape") exitCropMode();
        return;
      }
      if (e.key === "Escape") closePreview();
      if (e.key === "ArrowLeft") previewPrev();
      if (e.key === "ArrowRight") previewNext();
    });

    el.cropToggleBtn.addEventListener("click", enterCropMode);
    el.cropSaveBtn.addEventListener("click", saveCrop);
    el.cropClearBtn.addEventListener("click", clearCrop);

    // When the sidebar reorders, reload the grid.
    document.addEventListener("pages:refresh", async () => {
      if (state.projectId) {
        const pages = await API.listPages(state.projectId);
        state.pages = pages;
        renderPages();
      }
    });

    // Footer year
    const footerYear = document.getElementById("footerYear");
    if (footerYear) footerYear.textContent = new Date().getFullYear();
  }

  document.addEventListener("DOMContentLoaded", wireEvents);
})();