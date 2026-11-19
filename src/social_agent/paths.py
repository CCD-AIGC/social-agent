import os
import sys
from pathlib import Path


def app_home() -> Path:
    override = os.environ.get("SOCIAL_AGENT_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "social-agent"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "social-agent"


def config_path() -> Path:
    return app_home() / "config.yaml"


def database_path() -> Path:
    return app_home() / "state.sqlite3"


def logs_path() -> Path:
    return app_home() / "logs"


def drafts_path() -> Path:
    return app_home() / "drafts"


def secure_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
