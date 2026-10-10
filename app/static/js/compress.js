/* Compress Image page */
(() => {
  "use strict";

  const API = {
    async upload(file) {
      const fd = new FormData();
      fd.append("file", file, file.name);
      const r = await fetch("/api/images/upload", { method: "POST", body: fd });
      return handle(r);
    },
    async compress(jobId, body) {
      const r = await fetch(`/api/images/${jobId}/compress`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
    jobId: null,
    file: null,
    mode: "recommended",
    targetKb: 500,
    customQuality: 80,
  };

  const $ = (sel) => document.querySelector(sel);
  const el = {
    dropZone: $("#imgDropZone"),
    fileInput: $("#imgFileInput"),
    pickBtn: $("#pickFileBtn"),
    clearBtn: $("#clearFileBtn"),
    compressBtn: $("#compressNowBtn"),
    uploaded: $("#uploadedFile"),
    thumb: $("#uploadedThumb"),
    name: $("#uploadedName"),
    size: $("#uploadedSize"),
    pct: $("#uploadedPct"),
    targetKb: $("#targetKb"),
    targetKbValue: $("#targetKbValue"),
    customQuality: $("#customQuality"),
    customQualityValue: $("#customQualityValue"),
    result: $("#stepResult"),
    resultBefore: $("#resultBefore"),
    resultAfter: $("#resultAfter"),
    resultSaved: $("#resultSaved"),
    resultMode: $("#resultMode"),
    downloadBtn: $("#downloadBtn"),
    compressAnother: $("#compressAnotherBtn"),
    toast: $("#toast"),
    footerYear: $("#footerYear"),
    newProjectBtn: $("#newProjectBtn"),
  };

  /* ---------- Helpers ---------- */
  function toast(msg, type = "") {
    el.toast.textContent = msg;
    el.toast.className = "toast " + type;
    el.toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { el.toast.hidden = true; }, 3200);
  }

  function fmtKB(kb) {
    if (kb == null) return "—";
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(2)} MB`;
  }

  /* ---------- Upload ---------- */
  function resetUI() {
    state.jobId = null;
    state.file = null;
    el.uploaded.hidden = true;
    el.result.hidden = true;
    el.compressBtn.disabled = true;
    el.pct.textContent = "0%";
    el.thumb.removeAttribute("src");
  }

  async function handleFile(file) {
    if (!file) return;
    const okTypes = ["image/jpeg", "image/png", "image/webp",
                     "image/bmp", "image/tiff"];
    const okExt = /\.(jpe?g|png|webp|bmp|tiff?)$/i.test(file.name);
    if (!okTypes.includes(file.type) && !okExt) {
      toast("Please select a JPG, PNG, WEBP, BMP or TIFF image", "error");
      return;
    }
    if (file.size > 25 * 1024 * 1024) {
      toast("File is too large (max 25 MB)", "error");
      return;
    }

    state.file = file;

    // Show local preview instantly
    const localUrl = URL.createObjectURL(file);
    el.thumb.src = localUrl;
    el.name.textContent = file.name;
    el.size.textContent = fmtKB(file.size / 1024);
    el.pct.textContent = "100%";
    el.uploaded.hidden = false;
    el.compressBtn.disabled = true;

    try {
      const res = await API.upload(file);
      state.jobId = res.job_id;
      el.size.textContent = fmtKB(res.file_size_kb);
      el.compressBtn.disabled = false;
      toast("Image uploaded", "success");
    } catch (e) {
      toast(e.message, "error");
      el.uploaded.hidden = true;
      URL.revokeObjectURL(localUrl);
    }
  }

  /* ---------- Mode selection ---------- */
  function wireModeRadios() {
    document.querySelectorAll('input[name="mode"]').forEach(radio => {
      radio.addEventListener("change", () => {
        state.mode = radio.value;
        const isTarget = state.mode === "target_size";
        const isQuality = state.mode === "quality";
        el.targetKb.disabled = !isTarget;
        el.customQuality.disabled = !isQuality;
      });
    });

    el.targetKb.addEventListener("input", () => {
      state.targetKb = parseInt(el.targetKb.value, 10) || 500;
      el.targetKbValue.textContent = `${state.targetKb} KB`;
    });

    el.customQuality.addEventListener("input", () => {
      state.customQuality = parseInt(el.customQuality.value, 10) || 80;
      el.customQualityValue.textContent = `${state.customQuality}%`;
    });

    // Click on the row (not just the radio) selects it
    document.querySelectorAll(".option-row").forEach(row => {
      row.addEventListener("click", (e) => {
        if (e.target.tagName === "INPUT") return;
        const radio = row.querySelector('input[type="radio"]');
        if (radio) {
          radio.checked = true;
          radio.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    });
  }

  /* ---------- Compress ---------- */
  async function compress() {
    if (!state.jobId) {
      toast("Upload an image first", "error");
      return;
    }

    const body = { mode: state.mode };
    if (state.mode === "target_size") body.target_kb = state.targetKb;
    if (state.mode === "quality")     body.custom_quality = state.customQuality;

    el.compressBtn.disabled = true;
    el.compressBtn.textContent = "Compressing…";

    try {
      const res = await API.compress(state.jobId, body);

      el.resultBefore.textContent = fmtKB(res.input_size_kb);
      el.resultAfter.textContent  = fmtKB(res.output_size_kb);
      el.resultSaved.textContent  = `${res.saved_pct}%`;
      el.resultMode.textContent   =
        `Mode: ${res.mode} · ${res.original_dimensions.join("×")} → ` +
        `${res.output_dimensions.join("×")}`;

      el.downloadBtn.href = res.download_url;
      el.downloadBtn.setAttribute(
        "download",
        res.output_filename || "compressed.jpg"
      );

      el.result.hidden = false;
      el.result.scrollIntoView({ behavior: "smooth", block: "center" });
      toast(`Compressed! Saved ${res.saved_pct}%`, "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      el.compressBtn.disabled = false;
      el.compressBtn.textContent = "→ Compress Now";
    }
  }

  function compressAnother() {
    resetUI();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------- Wiring ---------- */
  function wireEvents() {
    el.pickBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      el.fileInput.click();
    });
    el.dropZone.addEventListener("click", () => el.fileInput.click());
    el.dropZone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        el.fileInput.click();
      }
    });

    el.fileInput.addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      handleFile(f);
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
      if (files && files.length) handleFile(files[0]);
    });

    window.addEventListener("dragover", (e) => e.preventDefault());
    window.addEventListener("drop", (e) => e.preventDefault());

    el.clearBtn.addEventListener("click", resetUI);
    el.compressBtn.addEventListener("click", compress);
    el.compressAnother.addEventListener("click", compressAnother);

    el.newProjectBtn.addEventListener("click", () => {
      if (confirm("Reset this page?")) resetUI();
    });

    wireModeRadios();

    if (el.footerYear) el.footerYear.textContent = new Date().getFullYear();
  }

  document.addEventListener("DOMContentLoaded", wireEvents);
})();