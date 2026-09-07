from starlette.responses import JSONResponse

from app.core.config import get_settings


class RequestProtection:
    """Bound request bodies before multipart parsing and require same-origin writes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        settings = get_settings()
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            allowed = (
                {settings.public_url.rstrip("/")}
                if settings.production
                else set(settings.cors_origins)
            )
            if (
                headers.get(b"origin", b"").decode() not in allowed
                or headers.get(b"x-requested-with") != b"email-checker"
            ):
                return await JSONResponse({"detail": "Invalid request origin."}, 403)(
                    scope, receive, send
                )
        limit = (
            settings.max_upload_bytes + 128 * 1024
            if scope["path"] == "/api/batch"
            else 64 * 1024
        )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse({"detail": "Request is too large."}, 413)(
                    scope, receive, send
                )
            if not message.get("more_body"):
                break
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        async def protected_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        await self.app(scope, replay, protected_send)
