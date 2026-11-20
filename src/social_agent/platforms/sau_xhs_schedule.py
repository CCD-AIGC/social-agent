"""Run the pinned SAU video uploader with an account check and a single scheduled submission."""

import argparse
from datetime import datetime, timedelta
import json
import os
import re
from urllib.parse import urlsplit


RECEIPT = "SOCIAL_AGENT_XHS_RECEIPT "
PREFLIGHT = "SOCIAL_AGENT_XHS_PREFLIGHT "
UNCONFIRMED = "SOCIAL_AGENT_XHS_UNCONFIRMED "


class PreflightError(Exception):
    pass


def schedule_digits(value: str) -> str:
    return "".join(re.findall(r"[0-9]", value))


async def capture_diagnostic(page, stage: str) -> None:
    prefix = os.environ.get("SOCIAL_AGENT_XHS_DIAGNOSTIC")
    if prefix:
        try:
            await page.screenshot(path=f"{prefix}-{stage}.png", full_page=True, timeout=5_000)
        except Exception:
            pass


async def creator_status(page, build_url, expected_account, title):
    await page.goto(build_url("/new/note-manager"), wait_until="domcontentloaded")
    try:
        account = page.locator(".user-info > span").first
        await account.wait_for(timeout=15_000)
        actual = (await account.inner_text()).strip()
        if actual != expected_account:
            raise PreflightError("扫码账号与指定的目标小红书账号不一致。")
        await page.get_by_text(re.compile(r"^全部(?:\s*\d+)?$")).first.wait_for(timeout=15_000)
    except PreflightError:
        raise
    except Exception:
        raise PreflightError("无法从小红书创作后台核对扫码账号或读取笔记列表。") from None
    match = page.get_by_text(title, exact=True).first
    if not await match.is_visible():
        return {"account": actual, "found": False}
    context = await match.evaluate(r"""(el) => {
        for (let node = el; node && node.innerText?.length < 700; node = node.parentElement) {
            if (/20\d{2}[-年]\d{1,2}[-月]\d{1,2}日?\s+\d{1,2}:\d{2}/.test(node.innerText)) {
                return node.innerText;
            }
        }
        return el.innerText;
    }""")
    scheduled = re.search(r"\b20\d\d[-年]\d{1,2}[-月]\d{1,2}日?\s+\d{1,2}:\d\d", context)
    return {"account": actual, "found": True, "has_schedule": "定时" in context,
            "displayed_time": scheduled.group(0) if scheduled else None}


async def read_draft_panel(page, title, *, after_save=False):
    video_tab = page.get_by_text(re.compile(r"^视频笔记\s*[（(]\s*\d+\s*[）)]$")).first
    if after_save:
        await video_tab.wait_for(timeout=15_000)
    elif not await video_tab.is_visible():
        library = page.get_by_text(re.compile(r"^草稿箱\s*[（(]\s*\d+\s*[）)]$")).first
        await library.wait_for(timeout=15_000)
        if re.search(r"[（(]\s*0\s*[）)]", await library.inner_text()):
            return False
        await library.click(timeout=5_000)
        await video_tab.wait_for(timeout=10_000)
    match = page.get_by_text(title, exact=True).first
    try:
        await match.wait_for(timeout=8_000)
        return True
    except Exception:
        return False


def guarded_uploader(base, settings):
    class GuardedVideo(base):
        async def upload(self, playwright):
            if not self.save_draft:
                await super().upload(playwright)
                return
            await self.validate_upload_args()
            browser = await playwright.chromium.launch(headless=self.headless, channel="chromium")
            try:
                context = await browser.new_context(storage_state=self.account_file)
                context = await settings["set_init_script"](context)
                page = await context.new_page()
                await self.upload_video_content(page)
                await context.storage_state(path=self.account_file, indexed_db=True)
            finally:
                await browser.close()

        async def upload_video_content(self, page):
            observed = await creator_status(page, settings["_build_xhs_creator_url"], self.expected_account, self.title)
            if observed["found"]:
                raise PreflightError("该账号的笔记列表已有同名作品，请先核对已有条目。")
            print("SOCIAL_AGENT_XHS_ACCOUNT_VERIFIED", flush=True)

            url = settings["_build_xhs_creator_url"]("/publish/publish?from=homepage&target=video")
            await page.goto(url, wait_until="domcontentloaded")
            file_input = page.locator("div[class^='upload-content'] input.upload-input")
            await file_input.set_input_files(self.file_path, timeout=20_000)
            await page.locator('input[placeholder*="填写标题"]').wait_for(timeout=120_000)
            await self.fill_meta(page)
            if self.thumbnail_path:
                await self.set_thumbnail(page, self.thumbnail_path)
            print("SOCIAL_AGENT_XHS_MEDIA_PREPARED", flush=True)

            if getattr(self, "save_draft", False):
                button = page.get_by_role("button", name="暂存离开", exact=True)
                try:
                    await button.click(trial=True, timeout=20_000)
                except Exception:
                    await capture_diagnostic(page, "draft-preflight")
                    raise PreflightError("小红书暂存按钮当前不可操作。") from None
                try:
                    await capture_diagnostic(page, "draft-ready")
                    await button.click(timeout=10_000)
                    found = await read_draft_panel(page, self.title, after_save=True)
                except Exception:
                    await capture_diagnostic(page, "draft-unconfirmed")
                    print(UNCONFIRMED + "暂存动作已尝试，草稿箱没有返回可核验条目。", flush=True)
                    raise
                if not found:
                    await capture_diagnostic(page, "draft-unconfirmed")
                    print(UNCONFIRMED + "暂存后在草稿箱未找到这条视频。", flush=True)
                    raise RuntimeError("draft list verification failed")
                await capture_diagnostic(page, "draft-visible")
                print(RECEIPT + json.dumps({
                    "account": self.expected_account, "title": self.title,
                    "evidence": "creator_draft_panel",
                }, ensure_ascii=False), flush=True)
                return

            schedule_button = page.get_by_role("button", name="定时发布", exact=True)
            try:
                await self.set_schedule_time_xiaohongshu(page, self.publish_date)
                date_input = page.locator(".d-datepicker-input-filter input.d-text")
                await date_input.press("Tab", timeout=8_000)
                requested = self.publish_date.strftime("%Y%m%d%H%M")
                displayed = schedule_digits(await date_input.input_value(timeout=8_000))
                if displayed != requested:
                    raise PreflightError("小红书页面回读的排期与请求时间不一致。")
                if self.publish_date <= datetime.now() + timedelta(hours=2):
                    raise PreflightError("临近发布时间，平台已无法安全提交这条排期。")
                await schedule_button.wait_for(timeout=15_000)
                await schedule_button.click(trial=True, timeout=10_000)
            except PreflightError:
                await capture_diagnostic(page, "preflight")
                raise
            except Exception:
                await capture_diagnostic(page, "preflight")
                raise PreflightError("创作页未能确认定时时间或定时按钮不可操作。") from None

            await capture_diagnostic(page, "ready")
            # A click may succeed even if the next page is slow. Leave ambiguous results to readback.
            try:
                await schedule_button.click(timeout=10_000)
                await page.wait_for_url(re.compile(r"/publish/success(?:[?#]|$)"), timeout=25_000)
            except Exception:
                await capture_diagnostic(page, "unconfirmed")
                print(UNCONFIRMED + "定时操作发出后未看到创作后台成功页，请核对笔记管理。", flush=True)
                raise
            if not urlsplit(page.url).path.endswith("/publish/success"):
                return
            await capture_diagnostic(page, "success")
            print(RECEIPT + json.dumps({
                "account": self.expected_account, "title": self.title,
                "scheduled_local": self.publish_date.strftime("%Y-%m-%d %H:%M"),
                "evidence": "creator_success_page",
            }, ensure_ascii=False), flush=True)

    return GuardedVideo


def main() -> int:
    from sau_commands.arguments import resolve_account_file, parse_tags
    from uploader.xiaohongshu_uploader import main as xhs
    import asyncio

    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["xiaohongshu"])
    parser.add_argument("action", choices=["upload-video", "inspect"])
    for name in ("account", "title", "expected-account"):
        parser.add_argument(f"--{name}", required=True)
    for name in ("file", "schedule", "desc", "tags", "thumbnail"):
        parser.add_argument(f"--{name}")
    parser.add_argument("--proof")
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--reopen", action="store_true")
    args = parser.parse_args()
    account_file = str(resolve_account_file(args.platform, args.account))
    if args.action == "inspect":
        async def inspect():
            async with xhs.async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True, channel="chromium")
                try:
                    context = await browser.new_context(storage_state=account_file)
                    page = await context.new_page()
                    result = await creator_status(page, xhs._build_xhs_creator_url, args.expected_account, args.title)
                    if args.draft:
                        await page.goto(xhs._build_xhs_creator_url("/publish/publish?from=homepage&target=video"),
                                        wait_until="domcontentloaded")
                        result["found"] = await read_draft_panel(page, args.title)
                    if args.proof and result["found"]:
                        await page.screenshot(path=args.proof)
                    if args.reopen and args.draft and result["found"]:
                        title = page.get_by_text(args.title, exact=True).first
                        card = title.locator('xpath=ancestor::div[.//*[normalize-space(text())="编辑"]][1]')
                        await card.get_by_text("编辑", exact=True).click(timeout=10_000)
                        field = page.locator('input[placeholder*="填写标题"]').first
                        await field.wait_for(timeout=15_000)
                        result["reopened"] = (await field.input_value()) == args.title
                        clip = page.locator("video").first
                        result["video_loaded"] = (await clip.count()) > 0
                        if result["video_loaded"]:
                            result["duration_seconds"] = await clip.evaluate("(el) => el.duration || null")
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                finally:
                    await browser.close()

        try:
            asyncio.run(inspect())
        except PreflightError as exc:
            print(PREFLIGHT + str(exc), flush=True)
            return 4
        return 0
    if not args.file or bool(args.schedule) == args.draft:
        parser.error("upload-video requires --file and one of --schedule/--draft")
    video_type = guarded_uploader(xhs.XiaoHongShuVideo, vars(xhs))
    uploader = video_type(
        title=args.title, file_path=args.file, desc=args.desc, tags=parse_tags(args.tags),
        publish_date=datetime.strptime(args.schedule, "%Y-%m-%d %H:%M") if args.schedule else 0,
        account_file=account_file,
        thumbnail_path=args.thumbnail, publish_strategy=(xhs.XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE
            if args.draft else xhs.XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED),
        debug=False,
    )
    uploader.expected_account = args.expected_account
    uploader.save_draft = args.draft
    try:
        asyncio.run(uploader.main())
    except PreflightError as exc:
        print(PREFLIGHT + str(exc), flush=True)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
