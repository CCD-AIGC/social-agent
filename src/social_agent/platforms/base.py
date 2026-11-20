from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PlatformInfo:
    id: str
    name: str
    research: tuple[str, ...] = ()
    publish: str = "dry-run-only"
    auth: str = "not-configured"
    notes: str = ""
    mark: str = ""
    creator_url: str = ""
    capabilities: tuple[tuple[str, str, str], ...] = ()


class PlatformAdapter(Protocol):
    id: str

    def research(self, *, limit: int = 10) -> dict[str, Any]: ...
