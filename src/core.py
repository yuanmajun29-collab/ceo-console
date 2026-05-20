from __future__ import annotations

from flask import Flask
from flask import Response

from .config import APP_DIR

app = Flask(__name__, template_folder=str(APP_DIR / "templates"))


@app.after_request
def add_no_cache_headers(resp: Response) -> Response:
    # Avoid stale frontend HTML/API cache that can leave dashboard stuck on
    # "加载中..." when browser serves old script/state.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp
