"""Higher-level project logic combining repositories and services."""
from app.models import file as file_repo
from app.models import page as page_repo
from app.models import project as project_repo
from app.services import pdf_service


def build_project_state(project_id: str) -> dict:
    """Return project with its files and ordered, non-deleted pages."""
    project = project_repo.get_project(project_id)
    if not project:
        return None

    files = file_repo.list_files(project_id)
    files_by_id = {str(f["_id"]): f for f in files}

    pages = page_repo.list_pages(project_id)
    enriched_pages = []
    for p in pages:
        f = files_by_id.get(str(p["file_id"]))
        enriched_pages.append({
            **p,
            "file_name": f["original_filename"] if f else None,
        })

    return {
        "project": project,
        "files": files,
        "pages": enriched_pages,
    }