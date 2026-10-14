"""ローカル HTTP の宛先と画面からの変更操作を検証する。"""
import logging
import secrets
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from core.error_codes import format_error

_logger = logging.getLogger(__name__)
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class LocalApiSecurityMiddleware:
    def __init__(self, app, *, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 重複ヘッダーの解釈差で検証を迂回させない。
        headers = {}
        for name, value in scope["headers"]:
            headers.setdefault(name.lower(), []).append(value.decode("latin-1"))

        def single(name):
            values = headers.get(name, [])
            return values[0] if len(values) == 1 else None

        port = scope["server"][1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        host = single(b"host")
        reason = None
        status = 403
        if host not in allowed or scope["scheme"] != "http":
            reason, status = "host", 400
        elif scope["method"] in _WRITE_METHODS:
            origin = single(b"origin")
            # Origin が送られていたら Referer で代替しない。
            source = origin if b"origin" in headers else single(b"referer")
            try:
                parsed = urlsplit(source or "")
                same_origin = (
                    parsed.scheme == "http" and parsed.netloc == host
                    and not parsed.username and not parsed.password
                    and (origin is None or not (parsed.path or parsed.query or parsed.fragment))
                )
            except ValueError:
                same_origin = False
            if not same_origin:
                reason = "origin"
            else:
                token = single(b"x-picocast-token")
                # 任意の非ASCII値にも一定時間比較を適用する。
                if token is None or not secrets.compare_digest(token.encode("latin-1"), self.token.encode("ascii")):
                    reason = "token"

        if reason:
            _logger.warning("E-WEB-REQUEST: ローカル要求を拒否 reason=%s method=%s", reason, scope["method"])
            response = JSONResponse(
                {"detail": format_error("E-WEB-REQUEST", with_fix=True)}, status_code=status,
            )
            await response(scope, receive, send)
            return

        async def protected_send(message):
            if message["type"] == "http.response.start":
                response_headers = message.get("headers", [])
                if any(name == b"content-type" and value.startswith(b"text/html") for name, value in response_headers):
                    # 再起動前のトークンを含むページをキャッシュから使わせない。
                    message = dict(message, headers=[
                        (name, value) for name, value in response_headers if name != b"cache-control"
                    ] + [(b"cache-control", b"no-store")])
            await send(message)

        await self.app(scope, receive, protected_send)
