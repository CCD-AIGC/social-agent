import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from ..credentials import CredentialStore
from ..errors import SocialAgentError

CREDENTIAL_KEY = "official-api"
MAX_COVER_BYTES = 64 * 1024
API_ROOT = "https://api.weixin.qq.com/cgi-bin/"


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Article:
    title: str
    content: str
    digest: str
    cover: bytes

    @property
    def content_hash(self) -> str:
        return article_text_hash(self.title, self.content)


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "br", "div"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"p", "div"}:
            self.parts.append(" ")


def article_text_hash(title: str, content: str) -> str:
    parser = ArticleParser()
    parser.feed(content)
    normalized = json.dumps([title.strip(), " ".join("".join(parser.parts).split())], ensure_ascii=False)
    return hashlib.sha256(normalized.encode()).hexdigest()


def prepare_article(target: dict) -> Article:
    title = target["title"].strip()
    if len(title) > 32:
        raise SocialAgentError("invalid_wechat_title", "公众号标题最多 32 字。")
    body = target["body"].strip()
    if target.get("ai_generated") and "AI 辅助" not in body:
        body += "\n\n本内容为 AI 辅助制作的原创动画。"
    content = "".join(f"<p>{html.escape(line.strip())}</p>" for line in body.splitlines() if line.strip())
    if len(content) > 20_000 or len(content.encode()) > 1_000_000:
        raise SocialAgentError("invalid_wechat_body", "公众号正文超出接口限制。")
    if not target.get("cover"):
        raise SocialAgentError("cover_required", "公众号图文草稿需要 JPEG 封面。", "在草稿中指定 64 KiB 以内的 JPEG。")
    try:
        with Path(target["cover"]).expanduser().open("rb") as stream:
            cover = stream.read(MAX_COVER_BYTES + 1)
    except OSError as exc:
        raise SocialAgentError("missing_media", "无法读取公众号封面。") from exc
    if not 4 <= len(cover) <= MAX_COVER_BYTES or not (cover.startswith(b"\xff\xd8\xff") and cover.endswith(b"\xff\xd9")):
        raise SocialAgentError("invalid_cover", "公众号封面必须是 64 KiB 以内的 JPEG。")
    return Article(title, content, " ".join(body.split())[:54], cover)


def save_credentials(alias: str, app_id: str, secret: str, store: CredentialStore | None = None) -> None:
    if not re.fullmatch(r"wx[0-9a-fA-F]{16}", app_id):
        raise SocialAgentError("invalid_app_id", "请输入公众号后台显示的 AppID。")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
        raise SocialAgentError("invalid_app_secret", "请输入公众号后台显示的 AppSecret。")
    (store or CredentialStore()).set("wechat_mp", alias, json.dumps([app_id, secret]), CREDENTIAL_KEY)


class WechatMPAdapter:
    id = "wechat_mp"

    def __init__(self, credentials: CredentialStore | None = None, opener=None):
        self.credentials = credentials or CredentialStore()
        self.opener = opener or build_opener(NoRedirects())

    def connect(self, alias: str):
        raw = self.credentials.get(self.id, alias, CREDENTIAL_KEY)
        if not raw:
            raise SocialAgentError(
                "credential_required", "该账号未设置公众号接口凭证。",
                "在平台接入 → 微信公众号录入 AppID 与 AppSecret。",
            )
        try:
            app_id, secret = json.loads(raw)
            if not isinstance(app_id, str) or not isinstance(secret, str):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise SocialAgentError("invalid_credentials", "钥匙串中的公众号凭证格式不正确。") from exc
        return WechatMPSession(app_id, secret, self.opener)


class WechatMPSession:
    def __init__(self, app_id: str, secret: str, opener):
        self.account_id = app_id
        self._secret = secret
        self._opener = opener
        self._token: str | None = None

    def _request(self, endpoint: str, data=None, *, query=None, media: bytes | None = None, writing=False):
        url = API_ROOT + endpoint
        if query:
            url += "?" + urlencode(query)
        headers = {"Accept": "application/json"}
        body = None
        if media is not None:
            boundary = uuid4().hex
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            body = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="media"; filename="cover.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode() + media + f"\r\n--{boundary}--\r\n".encode()
        elif data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        attempts = 1 if writing else 2
        for attempt in range(attempts):
            try:
                with self._opener.open(Request(url, data=body, headers=headers), timeout=18) as response:
                    result = json.loads(response.read(2_000_001))
                if not isinstance(result, dict):
                    raise ValueError
                break
            except (URLError, OSError, ValueError) as exc:
                if not writing and attempt + 1 < attempts and (
                    not isinstance(exc, HTTPError) or exc.code >= 500
                ):
                    time.sleep(0.4)
                    continue
                raise SocialAgentError(
                    "write_unconfirmed" if writing else "wechat_network",
                    "公众号写入结果待核对。" if writing else "公众号接口未返回可读结果。",
                    "先查草稿箱，避免重复创建。" if writing else "请检查当前网络并重试。",
                ) from None
        code = result.get("errcode", 0)
        if code != 0:
            errors = {
                -1: ("wechat_busy", "微信服务繁忙。"),
                40001: ("invalid_credentials", "公众号凭证或令牌无效。"),
                40002: ("invalid_credentials", "公众号令牌请求类型无效。"),
                40013: ("invalid_credentials", "公众号 AppID 无效。"),
                40007: ("remote_not_found", "当前账号找不到这个草稿或素材。"),
                41001: ("invalid_credentials", "公众号令牌缺失。"),
                42001: ("invalid_credentials", "公众号令牌已过期。"),
                40164: ("ip_not_allowed", "当前出口 IP 未加入公众号接口白名单。"),
                45009: ("rate_limited", "公众号接口达到每日调用上限。"),
                45011: ("rate_limited", "公众号接口调用过于频繁。"),
                48001: ("permission_required", "当前公众号未获此接口权限。"),
            }
            name, message = errors.get(code, ("wechat_rejected", "公众号拒绝了本次请求。"))
            safe_code = str(code) if isinstance(code, int) else "未知"
            raise SocialAgentError(name, message + f" 微信错误码 {safe_code}。")
        return result

    def _access_token(self) -> str:
        if self._token is None:
            response = self._request("stable_token", {
                "grant_type": "client_credential", "appid": self.account_id,
                "secret": self._secret, "force_refresh": False,
            })
            token = response.get("access_token")
            if not isinstance(token, str) or not token:
                raise SocialAgentError("wechat_network", "公众号接口未返回可用令牌。")
            self._token = token
        return self._token

    def call(self, endpoint: str, data=None, *, media=None, writing=False):
        query = {"access_token": self._access_token()}
        if media is not None:
            query["type"] = "thumb"
        return self._request(endpoint, data, query=query, media=media, writing=writing)

    def probe(self) -> dict:
        result = self.call("draft/count")
        count = result.get("total_count")
        if not isinstance(count, int):
            raise SocialAgentError("wechat_network", "公众号接口未返回草稿数量。")
        return {"logged_in": True, "draft_count": count}

    def upload_cover(self, cover: bytes) -> str:
        return self._media_id(self.call("material/add_material", media=cover, writing=True))

    def save_article(self, article: Article, cover_id: str) -> str:
        return self._media_id(self.call("draft/add", {"articles": [{
            "article_type": "news", "title": article.title, "digest": article.digest,
            "content": article.content, "thumb_media_id": cover_id,
        }]}, writing=True))

    def read_article(self, reference: str) -> dict:
        response = self.call("draft/get", {"media_id": reference})
        articles = response.get("news_item")
        if articles is None and isinstance(response.get("content"), dict):
            articles = response["content"].get("news_item")
        if not isinstance(articles, list) or len(articles) != 1 or not isinstance(articles[0], dict):
            raise SocialAgentError("draft_mismatch", "平台返回的稿件结构与单篇图文草稿不符。")
        return articles[0]

    @staticmethod
    def _media_id(response: dict) -> str:
        reference = response.get("media_id")
        if not isinstance(reference, str) or not reference.strip():
            raise SocialAgentError("write_unconfirmed", "平台写入未返回可用的素材或草稿编号。")
        return reference
