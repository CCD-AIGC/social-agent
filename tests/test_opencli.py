import json
from types import SimpleNamespace

import pytest

from social_agent.errors import SocialAgentError
from social_agent.platforms import opencli


def test_opencli_only_uses_public_research_commands(monkeypatch):
    def run(args, **kwargs):
        assert args == ["opencli", "hackernews", "top", "--limit", "3", "-f", "json"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True, "data": [
            {"title": "First", "score": 12, "url": "https://example.com/first"},
            {"title": "Second", "url": "javascript:alert(1)"},
        ]}))

    monkeypatch.setattr(opencli, "executable", lambda: ["opencli"])
    monkeypatch.setattr(opencli.subprocess, "run", run)
    rows = opencli.OpenCLIResearch("hackernews").research(limit=3)["items"]
    assert rows[0]["heat"] == 12
    assert rows[0]["url"] == "https://example.com/first"
    assert rows[1]["url"] is None
    with pytest.raises(SocialAgentError, match="25"):
        opencli.OpenCLIResearch("github-trending").research(limit=30)
