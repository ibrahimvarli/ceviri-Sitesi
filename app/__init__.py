from __future__ import annotations

from flask import Flask

from app.config import Config


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)

    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)
    app.config["EXPORT_FOLDER"].mkdir(parents=True, exist_ok=True)

    from app.routes.web import web_bp

    app.register_blueprint(web_bp)
    return app
