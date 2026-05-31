from __future__ import annotations

import os
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config as _config
from . import core as _core
from . import db as _db
from . import projects as _projects
from . import tools as _tools
from . import dispatch as _dispatch
from . import tasks as _tasks
from . import finance as _finance
from . import routes as _routes

from .core import app, add_no_cache_headers
from .config import *
from .db import *
from .projects import *
from .dispatch import *
from .tasks import *
from .tools import *
from .tools import _TOOL_STATUS_CACHE
from .finance import *
from .routes import *

_PROXY_MODULES = [_config, _db, _projects, _tools, _dispatch, _tasks, _finance, _routes]


def main() -> None:
    init_db()
    debug = os.environ.get("CEO_CONSOLE_DEBUG", "0") == "1"
    app.run(host=get_configured_host(), port=get_configured_port(), debug=debug)


__all__ = [name for name in globals() if not name.startswith("__")]
