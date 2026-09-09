from contextlib import asynccontextmanager
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.agent_actions import router as agent_actions_router
from app.api.growth_memory import router as growth_memory_router
from app.api.routes import router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.observability import configure_logging, request_id_context, runtime_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
logger = logging.getLogger(__name__)
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


@app.middleware("http")
async def observe_request(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if _REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status_code = 500
    measure = request.url.path != "/observability/metrics"
    if measure:
        runtime_metrics.http_started()
    try:
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            status_code = 500
            logger.error("unhandled api error", extra={
                "event": "http_unhandled_error", "error_type": type(exc).__name__,
            })
            logger.debug("unhandled api traceback", exc_info=True)
            response = JSONResponse(status_code=500, content={"detail": {
                "error_code": "internal_error", "message": "服务内部错误，请稍后重试",
                "request_id": request_id,
            }})
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        route_object = request.scope.get("route")
        route = getattr(route_object, "path", "__unmatched__")
        if measure:
            runtime_metrics.http_finished(request.method, route, status_code, duration_ms)
        level = logging.WARNING if duration_ms >= settings.slow_request_ms or status_code >= 500 else logging.INFO
        logger.log(level, "request completed", extra={
            "event": "http_request_completed", "method": request.method, "route": route,
            "status_code": status_code, "duration_ms": round(duration_ms, 2),
        })
        request_id_context.reset(token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled api error path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": {
        "error_code": "internal_error", "message": "服务内部错误，请稍后重试",
        "request_id": request_id_context.get(),
    }})


app.include_router(router)
app.include_router(agent_actions_router)
app.include_router(growth_memory_router)
