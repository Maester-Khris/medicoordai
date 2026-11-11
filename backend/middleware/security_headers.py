"""Adds baseline response headers to every response. Plain ASGI, so streamed (SSE) bodies pass through unbuffered."""
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# nosniff: stop browsers guessing a content type. CORP same-origin covers no-cors loads only;
# the web app's CORS fetches are unaffected.
_HEADERS = ((b"x-content-type-options", b"nosniff"), (b"cross-origin-resource-policy", b"same-origin"))


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)
