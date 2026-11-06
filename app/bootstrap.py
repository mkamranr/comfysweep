"""
Fixed process internals -- NOT user configuration.

Everything an admin can change lives in the database and is edited in the web
UI. These three values describe the container itself and have sane defaults
that match docker-compose.yml, so no .env file is needed. The environment
overrides exist only for local development and the test suite.
"""
import os

#: Where ComfySweep keeps its own SQLite database. Mounted from ./data.
DATA_DIR = os.environ.get("COMFYSWEEP_DATA_DIR", "/data").strip() or "/data"

#: The host directory tree bind-mounted into the container. Every cleanup
#: folder chosen in the UI must resolve inside it.
HOST_ROOT = os.environ.get("COMFYSWEEP_HOST_ROOT", "/host").strip() or "/host"

#: Listening port inside the container.
PORT = int(os.environ.get("COMFYSWEEP_PORT", "8191") or 8191)


def db_path():
    return os.path.join(DATA_DIR, "comfysweep.db")
