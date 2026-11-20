from importlib.metadata import entry_points

from .base import PlatformInfo
from .opencli import PUBLIC_SOURCES, OpenCLIResearch

PLATFORMS = (
    PlatformInfo(
        "xiaohongshu", "小红书", auth="official-creator-export",
        notes="导入官方 XLSX 查看笔记和指标。视频草稿经创作中心交接，保存后重新打开核对。",
        mark="红", creator_url="https://creator.xiaohongshu.com/statistics/data-analysis",
        capabilities=(("metrics.read", "官方 XLSX", "import"), ("draft.handoff", "视频草稿交接", "browser"),
                      ("schedule.video", "SAU 视频定时", "sau_browser")),
    ),
    PlatformInfo("wechat_mp", "微信公众号", auth="official-api-keychain",
        notes="用公众号 AppID 和接口凭证检查草稿权限。图文与可播放视频分别验证。",
        mark="公", creator_url="https://mp.weixin.qq.com/",
        capabilities=(("account.probe", "公众号接口权限", "official_api"),
                      ("draft.save", "图文草稿", "official_api"), ("draft.get", "图文草稿回读", "official_api"),
                      ("draft.handoff", "视频稿交接", "browser"))),
    PlatformInfo("wechat_channels", "微信视频号", auth="creator-login",
        notes="用视频号助手核对账号和已有草稿。保存后重新打开视频再登记结果。",
        mark="视", creator_url="https://channels.weixin.qq.com/",
        capabilities=(("draft.handoff", "视频草稿交接", "browser"),
                      ("draft.save.video", "SAU 视频草稿", "sau_browser"))),
    PlatformInfo("douyin", "抖音", notes="支持本地草稿预览。",
                 mark="抖", creator_url="https://creator.douyin.com/"),
    PlatformInfo("zhihu", "知乎", notes="支持本地草稿预览。",
                 mark="知", creator_url="https://www.zhihu.com/creator"),
    PlatformInfo("youtube", "YouTube", notes="支持本地草稿预览。",
                 mark="YT", creator_url="https://studio.youtube.com/"),
    PlatformInfo(
        "bilibili", "B 站", research=("hot_search",), auth="optional-existing-bili-cli-session",
        notes="工作台通过 bili-cli 读取账号和数据；投稿与定时已通过本机 bili-cli 验证。",
        mark="B", creator_url="https://space.bilibili.com/",
        capabilities=(("account.probe", "账号状态", "bili-cli"), ("research", "热搜", "bili-cli"),
                      ("works.list", "稿件列表", "bili-cli"), ("metrics.read", "账号概览", "bili-cli"),
                      ("publish", "本机 CLI 投稿", "external_cli"), ("schedule", "本机 CLI 定时投稿", "external_cli")),
    ),
)


def list_platforms() -> list[dict[str, object]]:
    result = []
    for platform in PLATFORMS:
        result.append(
            {
                "id": platform.id,
                "name": platform.name,
                "research": list(platform.research),
                "publish": platform.publish,
                "auth": platform.auth,
                "notes": platform.notes,
                "mark": platform.mark,
                "url": platform.creator_url,
                "capabilities": [{"action": action, "label": label, "transport": transport}
                                 for action, label, transport in platform.capabilities],
            }
        )
    for ep in entry_points(group="social_agent.platforms"):
        if any(item["id"] == ep.name for item in result):
            continue
        result.append(
            {
                "id": ep.name,
                "name": ep.name,
                "research": [],
                "publish": "plugin-defined",
                "auth": "plugin-defined",
                "notes": "由已安装的 social_agent.platforms 插件提供。",
            }
        )
    return result


def get_adapter(platform_id: str):
    if platform_id == "bilibili":
        from .bilibili import BilibiliAdapter

        return BilibiliAdapter()
    if platform_id == "xiaohongshu":
        from .xiaohongshu import XiaohongshuAdapter

        return XiaohongshuAdapter()
    if platform_id == "wechat_mp":
        from .wechat_mp import WechatMPAdapter

        return WechatMPAdapter()
    if platform_id in PUBLIC_SOURCES:
        return OpenCLIResearch(platform_id)
    for ep in entry_points(group="social_agent.platforms"):
        if ep.name == platform_id:
            factory = ep.load()
            return factory()
    raise KeyError(platform_id)
