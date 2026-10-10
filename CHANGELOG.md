# Changelog

All notable changes to the **PDF Merger** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Version history document (`CHANGELOG.md`).

### Fixed
- Duplicate view-function definitions (`compress_project`, `download_compressed`)
  in `app/routes/merge_routes.py` that caused Flask to raise
  `AssertionError: View function mapping is overwriting an existing endpoint function`.

### Changed
- Pending decision on compression strategy:
  - **Option A** – keep existing PyMuPDF image-XObject rewrite (keeps text, may grow file).
  - **Option B** – replace with page-rasterization pipeline (guaranteed smaller, kills text/search).

---

## [1.4.0] — 2026-10-02

### Added
- **Compress PDF** feature.
  - New `app/services/compress_service.py` with four presets:
    `low`, `medium`, `high`, `extreme`.
  - Backend routes in `app/routes/merge_routes.py`:
    - `POST /api/projects/<id>/compress`
    - `GET  /api/projects/<id>/download-compressed`
  - Project model extended with `compressed_filename` and `compressed_path`.
  - Frontend button `🗜 Compress PDF` added next to `🔗 Merge & Create PDF`.
  - Button is hidden by default and revealed after a successful merge.
  - Interactive preset chooser via `prompt()`.
  - Success panel reports input size, output size, and percentage saved.

### Fixed
- `compressBtn` was defined but never wired to `compressProject()`;
  the click listener is now attached in `wireEvents()`.
- `compressBtn` was never un-hidden after a merge — now revealed on success.
- `compressBtn` was not reset in `newProject()` — now hidden again.
- Null-guards (`if (el.compressBtn)`) added so the UI doesn't crash if the
  button is missing from the HTML.

---

## [1.3.0] — 2026-10-02

### Fixed
- **`CropBox not in MediaBox`** runtime error during merge.
  - Root cause: `_apply_crop()` was calling `page.set_mediabox(clamped)` on the
    *source* page before `insert_pdf()`, which propagated a shrunken MediaBox
    into the output page. A second `set_cropbox()` on the output page then
    referenced a MediaBox that no longer matched the stored crop coordinates.
  - Resolution:
    - Removed all calls to `set_mediabox()`.
    - `_apply_crop()` now uses `page.mediabox` (normalized) exclusively.
    - Crop rect is clamped *strictly inside* the MediaBox with a 0.5 pt epsilon.
    - Crop is applied to the **source** page before `insert_pdf()`; the output
      page is no longer re-cropped.
    - Malformed or out-of-bounds crops are skipped with a warning instead of
      aborting the entire merge.

### Changed
- `pdf_service.py` rewritten around a canonical `_apply_crop()` that:
  - Accepts multiple crop dict shapes
    (`{x0,y0,x1,y1}`, `{left,top,right,bottom}`, `{x,y,w,h}`, normalized `{l,t,r,b}`).
  - Normalizes `Rect` ordering (`x0 < x1`, `y0 < y1`).
  - Never mutates `MediaBox`.
- `merge_pages()` reordered: **crop → rotate → insert**.
  This makes crop rectangles survive `insert_pdf(rotate=N)` correctly, fixing
  the "split then rotate" bug where a cropped half appeared in the wrong region
  after rotation.
- Switched imports from deprecated `fitz` to `pymupdf`.

---

## [1.2.0] — 2026-10-02

### Changed (UI / CSS)
- **Pages grid now shows exactly 5 cards per row** on desktop
  (`repeat(5, minmax(0, 1fr))` instead of `auto-fill, minmax(160px, 1fr)`).
- **Exactly 1 page-card per row on mobile** (≤ 640 px).
- Responsive column counts:
  | Viewport      | Columns |
  |---------------|---------|
  | > 1024 px     | 5       |
  | ≤ 1024 px     | 4       |
  | ≤ 900 px      | 4       |
  | ≤ 768 px      | 3       |
  | ≤ 640 px      | 1       |
  | ≤ 480 px      | 1       |
  | ≤ 380 px      | 1       |
- Mobile full-width cards:
  - Thumbnail height fixed (`340px → 280px → 240px` by breakpoint) so the
    action row stays visible.
  - Action buttons share the row equally with ≥ 40 px tap targets.
- `main.container { min-height: 720px }` moved out of inline HTML into CSS and
  overridden to `min-height: 0` below 768 px.
- Removed `overflow-x: clip` (kept `overflow-x: hidden`) for consistent iOS Safari behavior.
- Added `object-fit: contain` to `.page-thumb` so rotated thumbnails no longer overflow.

### Fixed (JavaScript)
- **Critical**: `app.js` had a syntax error at the bottom of the file — the
  footer code block was placed outside `wireEvents()` with an orphan `}`
  after it. This caused *no* JS to execute on *any* device.
- Wired `compressBtn` click handler.
- Moved footer-link setup inside `wireEvents()`.

---

## [1.1.0] — 2026-10-02

### Added
- **Split page** feature.
  - `POST /api/pages/<page_id>/split` endpoint.
  - `app/services/split_service.py` with `split_page()` and `undo_split()`.
  - `pdf_service.compute_split_crops()` computes vertical / horizontal halves
    from the *unrotated* MediaBox, with optional gutter trimming.
  - Split halves inherit the parent's rotation and crop.
  - Original page is soft-deleted; two new pages replace it, preserving order
    via `shift_positions_from()`.
- Frontend split dialog: prompt-driven direction, ratio, and gutter selection.
  Auto-picks default direction from page aspect ratio (landscape → vertical split).
- **Preview modal** with previous/next navigation and zoom in/out (0.4× – 3×).
- **Duplicate page** action.
- **Undo delete** button (single-step undo buffer).
- **Drag-and-drop reordering** of page cards; order persisted to MongoDB.
- **Page thumbnails** rendered server-side at 90 DPI; preview at 150 DPI.

### Added (Model)
- `Page.parent_page_id` to link split children to their original.
- `Page.crop` field stores `{x0, y0, x1, y1}` (points, MediaBox-relative).
- `Page.rotation` restricted to `{0, 90, 180, 270}`.

---

## [1.0.0] — 2026-10-01

### Added
- Initial release.
- Flask application factory (`app/__init__.py`) with MongoDB connection singleton.
- Project / File / Page repository layer (`app/models/`).
- Upload endpoint with PDF validation:
  - Extension check (`.pdf`).
  - MIME-type check (`application/pdf`, `application/x-pdf`, `application/octet-stream`).
  - Magic-byte signature check (`%PDF-`).
  - 100 MB total upload cap.
- Endpoints:
  - `POST /api/projects` – create project
  - `GET  /api/projects` – list projects
  - `GET  /api/projects/<id>` – project state (files + ordered pages)
  - `DELETE /api/projects/<id>` – cascade delete
  - `POST /api/projects/<id>/upload` – upload PDFs, create one Page per PDF page
  - `GET  /api/projects/<id>/files`
  - `GET  /api/projects/<id>/pages`
  - `PUT  /api/pages/<id>` – update rotation / deleted
  - `DELETE /api/pages/<id>` – soft delete
  - `POST /api/pages/<id>/duplicate`
  - `GET  /api/pages/<id>/thumbnail`
  - `GET  /api/pages/<id>/preview`
  - `GET  /api/pages/<id>/size`
  - `POST /api/projects/<id>/merge`
  - `GET  /api/projects/<id>/download`
- **Merge pipeline** (`pdf_service.merge_pages`) via PyMuPDF.
- Frontend:
  - Drag-and-drop upload zone.
  - Progress bar with `XMLHttpRequest.upload.onprogress`.
  - Page grid with thumbnails, index badge, filename.
  - Rotate left / right, duplicate, select, delete per page.
  - Merge & Create PDF button.
  - Success panel with direct download link.
  - Toast notifications (success / error).
  - Footer with dynamic year.
- Config:
  - `.env` loading via `python-dotenv`.
  - PyInstaller-aware `APP_ROOT` / `WRITABLE_ROOT` (uploads/outputs next to `.exe`).
  - `MAX_CONTENT_LENGTH` env override.
- MongoDB indexes on `projects.created_at`, `files.project_id`,
  `pages.(project_id, position)`, `pages.file_id`.

---

## Version-numbering key

| Version | Date         | Theme                                     |
|---------|--------------|-------------------------------------------|
| 1.0.0   | 2026-10-01   | Initial release                           |
| 1.1.0   | 2026-10-02   | Split, preview, duplicate, reorder        |
| 1.2.0   | 2026-10-02   | Grid layout + critical JS syntax fix      |
| 1.3.0   | 2026-10-02   | CropBox fix + rotate/split interaction    |
| 1.4.0   | 2026-10-02   | Compress PDF feature                      |
| unreleased | —         | Changelog file, duplicate-route fix       |

---

## Known issues / backlog

- **Compression efficacy**: current `_compress_page_images()` inserts a JPEG
  *overlay* instead of replacing the original XObject, so `garbage=4` cannot
  drop the original image and the file may grow. Two candidate fixes:
  - *Option A*: rewrite `xreflist` to replace the image stream in-place.
  - *Option B*: rasterize each page and rebuild the PDF (smaller but loses text).
- **"Save all arrangement" button** was requested but not yet implemented —
  awaiting clarification on desired semantics (persist snapshot vs. rename of
  Merge vs. named versions).
- **Undo split** endpoint exists in `split_service.py` but is not exposed as an
  HTTP route nor wired to the UI.
- **Compression is synchronous**; large PDFs will block the request thread.
  Consider background task + polling for future versions.
- **No authentication / multi-user isolation** — every project in the database
  is visible to every client. Fine for a local desktop tool, not for a server.
- **No tests** — unit tests for `pdf_service`, `split_service`, and
  `compress_service` are on the roadmap.
- **No CSP / X-Frame-Options headers** — worth adding for the packaged build.