# PDF Merger Web Application

A production-quality web app to upload multiple PDFs, visually rearrange
individual pages (drag & drop, rotate, duplicate, delete, undo) and merge
them into a single PDF while preserving original page size, orientation
and quality.

**Stack:** Flask · PyMuPDF (fitz) · MongoDB · Vanilla HTML/CSS/JS

---

## 1. Features

- Drag & drop multi-PDF upload with progress bar
- Validation: extension, MIME type and `%PDF-` signature
- Thumbnail grid of **all pages** across **all uploaded PDFs**
- Drag-and-drop page reordering (final PDF follows exact order)
- Rotate left / right (persisted per page)
- Duplicate page · Delete page (soft delete + undo)
- Full-screen page preview with prev/next and zoom in/out
- “+ Add PDF” appends pages to the existing project
- `Merge & Create PDF` → produces downloadable merged PDF
- Responsive UI (desktop & mobile)

---

## 2. Requirements

- Python 3.10+
- MongoDB 5+ (local or Atlas)
- Modern browser (Chrome, Firefox, Edge, Safari)

---

## 3. Setup

### 3.1 Clone and create a virtual environment

**Windows**
```bat
python -m venv venv
venv\Scripts\activate


python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

python.exe -m pip install --upgrade pip

python run.py


Production deployment:::::::

pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 "run:app"
pip uninstall gunicorn -y

OR

pip install waitress
waitress-serve --host=0.0.0.0 --port=8000 --threads=8 run:app
http://localhost:8000


EXE
pip install pyinstaller
pip show pyinstaller

python -m PyInstaller pdf_merger.spec --noconfirm



venv\Scripts\deactivate