"""Project CRUD endpoints."""
from flask import Blueprint, jsonify, request

from app.models import serialize_doc
from app.models import project as project_repo
from app.services.project_service import build_project_state

project_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@project_bp.route("", methods=["POST"])
def create_project():
    data = request.get_json(silent=True) or {}
    name = (data.get("project_name") or "Untitled Project").strip()[:120]
    project = project_repo.create_project(name)
    return jsonify(serialize_doc(project)), 201


@project_bp.route("", methods=["GET"])
def list_projects():
    projects = project_repo.list_projects()
    return jsonify(serialize_doc(projects)), 200


@project_bp.route("/<project_id>", methods=["GET"])
def get_project(project_id):
    try:
        state = build_project_state(project_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if not state:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(serialize_doc(state)), 200


@project_bp.route("/<project_id>", methods=["DELETE"])
def delete_project(project_id):
    try:
        project_repo.delete_project(project_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"message": "Project deleted"}), 200