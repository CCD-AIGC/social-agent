from pathlib import Path
from typing import Any

import yaml

from .paths import app_home, config_path, secure_mkdir

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "default_timezone": "Asia/Shanghai",
    "platforms": {
        "bilibili": {"research": True, "publishing": "dry-run-only"},
        "xiaohongshu": {"publishing": "dry-run-only"},
        "douyin": {"publishing": "dry-run-only"},
        "zhihu": {"publishing": "dry-run-only"},
        "youtube": {"publishing": "dry-run-only"},
    },
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    target = path or config_path()
    if not target.exists():
        return DEFAULT_CONFIG.copy()
    try:
        loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取配置 {target}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("配置根节点必须是 YAML 映射")
    return {**DEFAULT_CONFIG, **loaded}


def write_default_config() -> Path:
    secure_mkdir(app_home())
    target = config_path()
    if target.exists():
        return target
    content = yaml.safe_dump(DEFAULT_CONFIG, allow_unicode=True, sort_keys=False)
    target.write_text(content, encoding="utf-8")
    target.chmod(0o600)
    return target
