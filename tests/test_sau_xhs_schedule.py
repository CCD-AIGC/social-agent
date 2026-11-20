import asyncio
from datetime import datetime, timedelta

import pytest

from social_agent.platforms import sau
from social_agent.platforms import sau_xhs_schedule as xhs
from social_agent.errors import SocialAgentError


def test_xhs_requires_explicit_target_and_future_schedule():
    video = {"title": "Test", "body": "", "tags": [], "video": "/tmp/test.mp4", "cover": None}
    scheduled = sau.normalize_schedule(sau.default_schedule())
    with pytest.raises(SocialAgentError, match="昵称"):
        sau.video_args("xiaohongshu", "local", video, scheduled)


def test_guarded_submit_rejects_different_scheduler_value(monkeypatch):
    class Base:
        title = "Test"
        file_path = "/tmp/test.mp4"
        thumbnail_path = None
        expected_account = "Test owner"
        publish_date = datetime.now() + timedelta(days=6)

        async def fill_meta(self, _page):
            pass

        async def set_schedule_time_xiaohongshu(self, _page, _date):
            pass

    class FakePage:
        def __init__(self):
            self.clicks = 0

        def locator(self, _selector):
            return self

        def get_by_role(self, *_args, **_kwargs):
            return self

        async def goto(self, *_args, **_kwargs):
            pass

        async def set_input_files(self, *_args, **_kwargs):
            pass

        async def wait_for(self, **_kwargs):
            pass

        async def press(self, *_args, **_kwargs):
            pass

        async def input_value(self, **_kwargs):
            return "2025-01-01 08:00"

        async def click(self, **_kwargs):
            self.clicks += 1

    async def creator_status(*_args):
        return {"account": "Test owner", "found": False}

    monkeypatch.setattr(xhs, "creator_status", creator_status)
    page = FakePage()
    uploader = xhs.guarded_uploader(Base, {"_build_xhs_creator_url": lambda path: path})()
    with pytest.raises(xhs.PreflightError, match="排期"):
        asyncio.run(uploader.upload_video_content(page))
    assert page.clicks == 0
