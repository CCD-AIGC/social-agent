from dataclasses import dataclass

from .errors import SocialAgentError

SERVICE_NAME = "social-agent"


def keyring_username(platform: str, alias: str, key: str = "session") -> str:
    return f"{platform}:{alias}:{key}"


@dataclass
class CredentialStore:
    backend: object | None = None

    def _keyring(self):
        if self.backend is not None:
            return self.backend
        try:
            import keyring
        except ImportError as exc:
            raise SocialAgentError(
                "keyring_unavailable", "未安装 Keychain 依赖", "运行 uv sync 后重试。"
            ) from exc
        return keyring

    def set(self, platform: str, alias: str, secret: str, key: str = "session") -> None:
        if not secret:
            raise SocialAgentError("empty_secret", "凭证不能为空")
        try:
            self._keyring().set_password(SERVICE_NAME, keyring_username(platform, alias, key), secret)
        except Exception as exc:
            raise SocialAgentError(
                "keychain_error", "无法写入系统凭证库", "检查 macOS 登录钥匙串是否已解锁。"
            ) from exc

    def get(self, platform: str, alias: str, key: str = "session") -> str | None:
        try:
            return self._keyring().get_password(SERVICE_NAME, keyring_username(platform, alias, key))
        except Exception as exc:
            raise SocialAgentError(
                "keychain_error", "无法读取系统凭证库", "检查 macOS 登录钥匙串是否已解锁。"
            ) from exc

    def delete(self, platform: str, alias: str, key: str = "session") -> None:
        try:
            self._keyring().delete_password(SERVICE_NAME, keyring_username(platform, alias, key))
        except Exception as exc:
            raise SocialAgentError("keychain_error", "无法删除系统凭证") from exc

    def backend_name(self) -> str:
        try:
            backend = self._keyring()
            if hasattr(backend, "get_keyring"):
                backend = backend.get_keyring()
            return type(backend).__name__
        except Exception as exc:
            return f"unavailable: {type(exc).__name__}"
