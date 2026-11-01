import logging
import os
import uuid

logger = logging.getLogger(__name__)

import sentry_sdk
from fastapi import Header, HTTPException
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_registry = CollectorRegistry()


def init_logging() -> None:
    env = os.environ.get("ENVIRONMENT", "staging")
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        static_fields={"environment": env, "service": "medicoord-api"},
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = []
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def init_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN_BACKEND")
    if not dsn:
        logger.warning("sentry_disabled", extra={"reason": "SENTRY_DSN_BACKEND not set"})
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ENVIRONMENT", "staging"),
        traces_sample_rate=float(
            os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.2")
        ),
        integrations=[StarletteIntegration(), FastApiIntegration()],
        send_default_pii=False,
    )


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def init_metrics(app) -> Instrumentator:  # type: ignore[type-arg]
    instrumentator = Instrumentator(registry=_registry)
    instrumentator.instrument(app)

    # Metrics are pulled, not pushed: Grafana Cloud scrapes GET /metrics (Metrics Endpoint
    # integration, Bearer METRICS_BEARER_TOKEN). The push thread that used to live here never
    # delivered a sample.
    return instrumentator


def verify_metrics_token(authorization: str = Header(default="")) -> None:
    token = os.environ.get("METRICS_BEARER_TOKEN", "").strip()
    if not token:
        # Fail closed: without a configured token the endpoint would be open to anyone.
        raise HTTPException(status_code=503, detail="Metrics token not configured")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=403, detail="Forbidden")


def init_observability(app) -> None:  # type: ignore[type-arg]
    init_logging()
    init_sentry()
    init_metrics(app)
