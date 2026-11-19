from importlib.metadata import entry_points

from .base import PlatformInfo

PLATFORMS = (
    PlatformInfo(
        "xiaohongshu",
        "小红书",
        auth="official-creator-export",
        notes="支持从官方 XLSX 导入已发布笔记及基础指标；发布预览可用。",
    ),
    PlatformInfo("douyin", "抖音", notes="读写适配器待实现；发布预览可用。"),
    PlatformInfo("zhihu", "知乎", notes="读写适配器待实现；发布预览可用。"),
    PlatformInfo("youtube", "YouTube", notes="官方 OAuth/API 适配器待实现；发布预览可用。"),
    PlatformInfo(
        "bilibili",
        "B 站",
        research=("hot_search",),
        auth="optional-existing-bili-cli-session",
        notes="热搜通过已安装 bili-cli 只读读取；发布仍为预览。",
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
    for ep in entry_points(group="social_agent.platforms"):
        if ep.name == platform_id:
            factory = ep.load()
            return factory()
    raise KeyError(platform_id)
