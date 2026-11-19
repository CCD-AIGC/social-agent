"""Read the official creator center's note report from a local XLSX file."""

from contextlib import closing
from datetime import datetime, timezone
from io import BytesIO
from math import isfinite
from warnings import catch_warnings, filterwarnings
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from ..errors import SocialAgentError
from ..storage import StateStore

SOURCE = "xiaohongshu-creator-export"
CREATOR_REPORT_URL = "https://creator.xiaohongshu.com/statistics/data-analysis"
REPORT_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_REPORT_BYTES = 2_000_000
MAX_NOTES = 1000
COUNT_COLUMNS = {
    "曝光": "impressions",
    "观看量": "views",
    "点赞": "likes",
    "评论": "comments",
    "收藏": "favorites",
    "涨粉": "followers_gained",
    "分享": "shares",
    "人均观看时长": "average_watch_seconds",
    "弹幕": "danmaku",
}
REQUIRED_COLUMNS = {"笔记标题", "首次发布时间", "体裁", "封面点击率", *COUNT_COLUMNS}


def _number(value, *, ratio=False):
    if value in (None, "", "-", "—", "--"):
        return None
    if isinstance(value, str) and ratio and value.strip().endswith("%"):
        value = float(value.strip()[:-1]) / 100
    number = float(value)
    if not isfinite(number) or number < 0 or (ratio and number > 1):
        raise ValueError("invalid metric")
    if ratio:
        return number
    if not number.is_integer():
        raise ValueError("invalid count")
    return int(number)


def _published_at(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    try:
        return datetime.fromisoformat(value).isoformat(timespec="seconds")
    except ValueError:
        return datetime.strptime(value, "%Y年%m月%d日%H时%M分%S秒").isoformat(timespec="seconds")


def _read_report(raw: bytes) -> tuple[str | None, list[dict]]:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 64 or sum(entry.file_size for entry in entries) > 8_000_000:
                raise ValueError("report exceeds expanded size limit")
        # The creator center exports a single sheet, with a notice above its headers.
        with catch_warnings():
            filterwarnings("ignore", message="Workbook contains no default style", module="openpyxl.styles.stylesheet")
            workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        with closing(workbook) as book:
            sheet = book.worksheets[0]
            rows = sheet.iter_rows(max_col=32, max_row=MAX_NOTES + 6, values_only=True)
            for _ in range(5):
                header = {value: index for index, value in enumerate(next(rows, ())) if isinstance(value, str)}
                if REQUIRED_COLUMNS <= header.keys():
                    break
            else:
                raise ValueError("unrecognized headers")
            notes = []
            for row in rows:
                title = row[header["笔记标题"]]
                if not title and not any(value is not None for value in row):
                    continue
                if not isinstance(title, str) or not title.strip() or len(notes) >= MAX_NOTES:
                    raise ValueError("invalid note")
                metrics = {key: _number(row[header[column]]) for column, key in COUNT_COLUMNS.items()}
                metrics["cover_click_rate"] = _number(row[header["封面点击率"]], ratio=True)
                notes.append({
                    "title": title,
                    "published_at": _published_at(row[header["首次发布时间"]]),
                    "format": str(row[header["体裁"]] or ""),
                    **metrics,
                })
            created = book.properties.created
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return created.isoformat(timespec="seconds") if created else None, notes
    except (BadZipFile, DefusedXmlException, InvalidFileException, IndexError, KeyError, ParseError, TypeError, ValueError) as exc:
        raise SocialAgentError(
            "invalid_xiaohongshu_report",
            "无法读取小红书笔记明细。请选择创作服务平台「内容分析」导出的原始 XLSX。",
        ) from exc


class XiaohongshuAdapter:
    id = "xiaohongshu"

    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    def import_report(self, alias: str, raw: bytes) -> dict:
        alias = alias.strip()
        if not alias or len(alias) > 100:
            raise SocialAgentError("invalid_account", "请输入 1 至 100 个字符的账号名。")
        if len(raw) > MAX_REPORT_BYTES:
            raise SocialAgentError("report_too_large", "笔记明细文件超过 2 MB。请缩短导出日期范围。")
        exported_at, notes = _read_report(raw)
        return self.store.save_note_snapshot(self.id, alias, exported_at, notes)

    def probe(self) -> dict:
        snapshot = self.store.note_snapshot(self.id)
        return {
            "platform": self.id,
            "source": SOURCE,
            "credential_imported": False,
            "status": {
                "logged_in": None,
                "snapshot_available": snapshot is not None,
                "imported_at": snapshot["imported_at"] if snapshot else None,
            },
            "profile": {"name": snapshot["account"]} if snapshot else None,
        }

    def metrics(self, account: str | None = None) -> dict:
        snapshot = self.store.note_snapshot(self.id, account)
        if snapshot is None:
            return {
                "available": False,
                "platform": self.id,
                "account": account,
                "source": SOURCE,
                "reason": "该账号暂无快照，请先导入官方笔记明细。",
            }
        notes = snapshot.pop("notes")
        totals = {}
        for key in ("impressions", "views", "likes", "comments", "favorites", "followers_gained", "shares"):
            values = [note[key] for note in notes]
            totals[key] = sum(values) if None not in values else None
        return {
            "available": True,
            "platform": self.id,
            "source": SOURCE,
            "credential_imported": False,
            "result": {
                **snapshot,
                "note_count": len(notes),
                "totals": totals,
                "notes": notes,
            },
        }
