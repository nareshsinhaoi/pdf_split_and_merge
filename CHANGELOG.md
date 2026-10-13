# Changelog

All notable changes to the **PDF Merger** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- *(nothing yet)*

### Changed
- *(nothing yet)*

### Fixed
- *(nothing yet)*

---

## [1.6.0] — 2026-10-12

### Added — Sidebar with editable page titles and drag-and-drop reorder

A right-hand, sticky sidebar that lists every page in the current project
and lets the user rename pages and reorder them without touching the
main grid.

#### Frontend

- **New script** `app/static/js/sidebar.js`
  - Standalone IIFE, no dependencies on `app.js` internals.
  - Reads the current page list via the existing
    `GET /api/projects/<id>/pages` endpoint.
  - Renders one row per page with:
    - drag handle (`⋮⋮`)
    - index badge
    - **editable title input** (Enter to save, Esc to cancel)
    - jump-to-page button (`→`) that scrolls the corresponding grid card
      into view and flashes it.
  - Native HTML5 drag-and-drop to reorder rows, persisted via the existing
    `PUT /api/projects/<id>/pages/reorder` endpoint.
  - Drop position (before / after) is decided by which half of the target
    row the cursor is over.
  - Optimistic render: the list updates immediately, then the server call
    runs; on failure, the list reloads from the server.
  - Dispatches a `pages:refresh` custom event so `app.js` re-fetches and
    re-renders the grid with the new order.
  - Exposes a small public API on `window.PageSidebar`:
    - `setProject(projectId)`
    - `setPages(pages)`
    - `reload()`
    - `clear()`

- **Sidebar UI** in `app/templates/index.html`
  - New `<aside id="pageSidebar">` element placed **outside `<main>`**,
    as a sibling in a new `.page-shell` grid wrapper.
  - Sidebar sits on the **right** of the main content on desktop.
  - Contains: header with page count, empty-state message, `<ul>` list,
    hint line.
  - Mobile-only toggle button `☰ Pages` (`#sidebarToggle`) added inside
    `<main>` so it appears above the upload area on small screens.

- **New styles** in `app/static/css/style.css`
  - `.page-shell` — 2-column grid: `minmax(0, 1fr) 320px`.
  - `.page-sidebar` — `position: sticky; top: 84px;` so it stays in view
    while scrolling long page lists.
  - `.sidebar-row` — grid layout `14px 22px 1fr 26px`, hover/selected states,
    drag-over-top / drag-over-bottom indicators.
  - `.sidebar-title` — input styled to look like plain text until hovered or
    focused.
  - `.page-card.flash` — pulse animation used when jumping from the sidebar.
  - Responsive rules:
    - ≤ 1024 px → sidebar column shrinks to 280 px.
    - ≤ 900 px → sidebar stacks below main content, collapsed by default,
      revealed by the `☰ Pages` toggle.
    - ≤ 640 px → tighter row spacing, smaller title font.

- **`title` field** on the `pages` document (`app/models/page.py`)
  - `create_page()` now initializes `"title": None`.
  - Auto-generated display title is derived on the client from
    `file_name` + `original_page_number` when `title` is null.

#### Backend

- **`PUT /api/pages/<page_id>`** (`app/routes/page_routes.py`)
  - Now accepts an optional `title` field (string, up to 200 chars, trimmed).
  - Passing `title: null` clears the custom title and reverts to the
    auto-generated label.

#### Wiring changes in `app.js`

Five small additions only — the merge pipeline and all existing behavior
are untouched:

- `syncSidebar(pages)` helper that forwards the current list to
  `window.PageSidebar.setPages()`.
- `renderPages()` now calls `syncSidebar(...)` in both the empty and
  populated branches, so the sidebar stays in sync on every upload,
  delete, undo, split, duplicate, and reorder.
- `ensureProject()` calls `window.PageSidebar.setProject(id)` after
  creating a new project.
- `newProject()` calls `window.PageSidebar.clear()`.
- A `pages:refresh` listener re-fetches pages and re-renders the grid when
  the sidebar reports a reorder.

### Changed

- **`app/templates/index.html`**
  - `<main>` no longer wraps the sidebar; a new `<div class="page-shell">`
    wraps both `<main>` and `<aside id="pageSidebar">`.
  - Added `<script src="{{ url_for('static', filename='js/sidebar.js') }}">`
    after `app.js`.
  - Footer version bumped to `v1.6.0`.

- **`app/static/css/style.css`**
  - Replaced the old `.workspace` wrapper rules with `.page-shell`.
  - `.main-content` zeroes out `<main>`'s own padding since `.page-shell`
    now handles horizontal spacing.
  - Sidebar becomes the right column of the grid on desktop; collapses
    below 900 px.

### Fixed

- Sidebar stays correctly aligned when the pages grid scrolls — `position:
  sticky` with `top: 84px` (matching the 64 px sticky header plus margin).
- Editable title inputs no longer trigger row drag when clicked or while
  being edited (`mousedown` and `dragstart` are stopped on the input).
- Renaming a page and immediately dragging another row no longer races —
  the title save is awaited on blur before any reorder request fires.

### Known limitations (this release)

- Sidebar titles are **not** used as bookmarks in the merged PDF (the
  merge pipeline ignores them). Rendering titles as PDF outline entries is
  planned for a future release.
- No bulk-select / bulk-delete from the sidebar yet — one page at a time.
- The `↩ Undo Delete` button and the sidebar are independent; undoing a
  delete refreshes the sidebar via `syncSidebar()` but the sidebar's own
  selection state (if any) is cleared.

---

## [1.5.0] — 2026-10-10

### Added — Compress Image feature

A complete Smallpdf-style image compression tool, accessible as a second
top-level product alongside PDF merging.

#### Backend
- **New service** `app/services/compress_image_service.py`
  - Pillow-based compression pipeline with six modes:
    - `less`         — high quality, small savings (q=90, no resize)
    - `recommended`  — balanced (q=75, max dimension 2400 px) **[default]**
    - `extreme`      — aggressive (q=50, max dimension 1600 px)
    - `lossless`     — no quality loss (q=95, optimize + progressive)
    - `target_size`  — binary-search on quality to hit a target KB
    - `quality`      — user-chosen JPEG quality 0–100
  - EXIF orientation normalization (`ImageOps.exif_transpose`).
  - Automatic alpha-flattening for RGBA / LA / P images.
  - Progressive + optimized JPEG output.
  - Target size clamped to `100–5000 KB`.
  - Custom quality clamped to `10–100`.
  - `ImageCompressError` for user-facing failures.

- **New blueprint** `app/routes/compress_image_routes.py`
  - `POST /api/images/upload`
    - Accepts `multipart/form-data` with a single `file` field.
    - Validates extension against `{.jpg, .jpeg, .png, .webp, .bmp, .tiff, .tif}`.
    - Persists file to `IMAGES_FOLDER` with a UUID-based name.
    - Inserts a job record into the new `image_jobs` collection.
    - Returns `{ job_id, original_filename, file_size, file_size_kb }`.
  - `POST /api/images/<job_id>/compress`
    - Body: `{ mode, target_kb?, custom_quality? }`.
    - Runs the compression, updates the job doc with stats and output path.
    - Returns `{ input_size, output_size, saved_bytes, saved_pct, mode,
      original_dimensions, output_dimensions, download_url }`.
  - `GET /api/images/<job_id>/download`
    - Serves the compressed file with `Content-Disposition: attachment`.
    - Download name derived from the original upload
      (`compressed_<original-stem>.jpg`).
  - `GET /api/images/<job_id>/preview`
    - Serves the compressed file inline (no `Content-Disposition`) for use
      in the result panel.

- **New template** `app/templates/compress.html`
  - Smallpdf-equivalent layout: two-column (upload left, settings right).
  - Header nav shared with the merge page.
  - Radio-card UI for compression mode selection.
  - Live range sliders for `target_kb` and `custom_quality` with value labels.
  - Before → After → Saved result stats card.
  - Download button and "Compress another image" reset action.

- **New stylesheet** `app/static/css/compress.css`
  - Orange accent (`#e8622c`) matching the reference screenshots.
  - Radio-card styles with `RECOMMENDED` / `BEST COMPRESSION` pills.
  - Range-slider ticks (`0% 20% 40% 60% 80% 100%`).
  - Responsive collapse to single-column below 900 px.

- **New script** `app/static/js/compress.js`
  - Local thumbnail preview immediately on file pick (before upload).
  - XHR upload with success/error toast feedback.
  - Mode-change listeners that enable/disable the relevant sliders.
  - Row-click delegation so clicking anywhere on the card selects the radio.
  - Result rendering with proper KB/MB formatting.

#### Backend — infrastructure
- **New config key** `Config.IMAGES_FOLDER` — defaults to `<root>/images/`,
  overridable via `IMAGES_FOLDER` env var.
- **New Mongo collection** `image_jobs`:
  - `_id`, `original_filename`, `stored_filename`, `file_path`, `file_size`,
    `uploaded_at`, `status`, `result`, `compressed_at`.
- **New indexes** on `image_jobs.uploaded_at` and `image_jobs.status`.
- `create_app()` now:
  - Creates `IMAGES_FOLDER` on startup.
  - Registers the `image_bp` blueprint.
  - Serves `/compress` from `compress.html`.

#### Frontend — header navigation
- **Shared nav tabs** added to the app header on both pages:
  - `Merge PDF` (links to `/`)
  - `Compress Image` (links to `/compress`)
- Active tab visually distinguished (indigo background, primary text).
- Collapses to a full-width row on mobile (≤ 640 px).
- Both `index.html` and `compress.html` share the same `.app-nav` markup.

#### Dependencies
- Added `Pillow>=10.0.0` to `requirements.txt`.

### Changed
- **`app/__init__.py`**
  - Imports and registers `image_bp` from `app.routes.compress_image_routes`.
  - Creates `IMAGES_FOLDER` alongside `UPLOAD_FOLDER` and `OUTPUT_FOLDER`.
  - Moved `/compress` route next to `/` for readability.
  - Fixed typo in 404 handler (`"Not @ found"` → `"Not found"`).

- **`app/templates/index.html`**
  - Replaced header title `📄 PDF Merger` with `📄 PDF Toolkit`.
  - Added `.app-nav` with `Merge PDF` (active) and `Compress Image` links.

- **`app/static/css/style.css`**
  - Added shared `.app-nav` / `.nav-link` rules used by both pages.

### Fixed
- Duplicate view-function definitions (`compress_project`, `download_compressed`)
  in `app/routes/merge_routes.py` that caused Flask to raise
  `AssertionError: View function mapping is overwriting an existing endpoint function`.

### Known limitations (this release)
- Compression is synchronous; a large image will block the request thread.
- No batch / multi-file compression yet (single image per job).
- Cloud import (Google Drive / Dropbox / OneDrive) is not implemented — the
  reference UI shows these buttons but they are stubs.
- No cleanup TTL on `image_jobs` — records and files persist indefinitely.
- "How was your experience?" and "Want to support us?" sections from the
  reference UI are **intentionally omitted** (marked not required).

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
  - `POST   /api/projects`                       – create project
  - `GET    /api/projects`                       – list projects
  - `GET    /api/projects/<id>`                  – project state (files + ordered pages)
  - `DELETE /api/projects/<id>`                  – cascade delete
  - `POST   /api/projects/<id>/upload`           – upload PDFs, create one Page per PDF page
  - `GET    /api/projects/<id>/files`
  - `GET    /api/projects/<id>/pages`
  - `PUT    /api/pages/<id>`                     – update rotation / deleted
  - `DELETE /api/pages/<id>`                     – soft delete
  - `POST   /api/pages/<id>/duplicate`
  - `GET    /api/pages/<id>/thumbnail`
  - `GET    /api/pages/<id>/preview`
  - `GET    /api/pages/<id>/size`
  - `POST   /api/projects/<id>/merge`
  - `GET    /api/projects/<id>/download`
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

| Version    | Date         | Theme                                          |
|------------|--------------|------------------------------------------------|
| 1.0.0      | 2026-10-01   | Initial release                                |
| 1.1.0      | 2026-10-02   | Split, preview, duplicate, reorder             |
| 1.2.0      | 2026-10-02   | Grid layout + critical JS syntax fix           |
| 1.3.0      | 2026-10-02   | CropBox fix + rotate/split interaction         |
| 1.4.0      | 2026-10-02   | Compress PDF feature                           |
| 1.5.0      | 2026-10-10   | Compress Image feature + header nav            |
| 1.6.0      | 2026-10-12   | Sidebar with editable titles + DnD reorder     |
| unreleased | —            | —                                              |

---

## Known issues / backlog

### Merge pipeline
- **Compression efficacy**: `_compress_page_images()` inserts a JPEG *overlay*
  instead of replacing the original XObject, so `garbage=4` cannot drop the
  original image and the file may grow. Two candidate fixes:
  - *Option A*: rewrite `xreflist` to replace the image stream in-place.
  - *Option B*: rasterize each page and rebuild the PDF (smaller but loses text).
- **Mixed-orientation sources**: magazine PDFs (portrait page box with a
  landscape spread printed inside) require content-bbox detection to normalize
  correctly. Current merge uses page-box orientation, which is wrong for these
  sources.
- **Blank / junk pages**: scanned magazines often contain pages that are just a
  page number or OCR digit noise. These are currently merged as-is. Should be
  filtered at upload time using an ink-ratio check.
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

### Sidebar (new in 1.6.0)
- **Sidebar titles are not bookmarked in the merged PDF** — the merge pipeline
  ignores the `title` field. Rendering titles as PDF outline entries is
  planned for a future release.
- **No bulk-select / bulk-delete from the sidebar** yet.
- **Sidebar selection state** is not synced with the grid's `state.selected`
  set; the `✓ Select` action still lives only on the page cards.
- **Sidebar order is not undoable** — once reordered, the previous order is
  lost unless the user manually drags back. A "reset order" or undo stack
  could be added later.

### Compress Image (new in 1.5.0)
- **Batch mode not implemented** — one image per job.
- **Cloud import stubs** — the reference UI shows Google Drive / Dropbox /
  OneDrive buttons; they are visual only.
- **No TTL cleanup** — `image_jobs` records and files persist forever. A cron
  or Mongo TTL index is needed before production.
- **No batch-download ZIP** — compress one file at a time.
- **Format preservation** — all output is JPEG (even if input was PNG/WEBP).
  A future version should keep PNG for images with alpha or line art.
- **Lossless mode is really "near-lossless"** — uses JPEG q=95, not true
  lossless re-encoding. For true lossless, PNG output would be required.
- **Feedback widgets omitted** — "How was your experience?" and "Want to
  support us?" from the reference UI are intentionally not built.