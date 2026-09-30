"""Flask application factory."""
import logging
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template

from app.config import Config


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder=config_class.TEMPLATE_FOLDER,
        static_folder=config_class.STATIC_FOLDER,
        static_url_path="/static",
    )
    app.config.from_object(config_class)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["OUTPUT_FOLDER"]).mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from app.routes.project_routes import project_bp
    from app.routes.upload_routes import upload_bp
    from app.routes.page_routes import page_bp
    from app.routes.merge_routes import merge_bp

    app.register_blueprint(project_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(page_bp)
    app.register_blueprint(merge_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": "File too large"}), 413

    @app.errorhandler(500)
    def server_error(e):
        app.logger.exception("Internal server error")
        return jsonify({"error": "Internal server error"}), 500

    return app