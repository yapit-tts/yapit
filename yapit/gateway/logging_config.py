"""Logging configuration: loguru setup, standard logging interception, request context."""

import logging
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from yapit.gateway.metrics import log_error


class InterceptHandler(logging.Handler):
    """Route standard library logging to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding loguru level
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller frame (skip logging internals)
        frame, depth = sys._getframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(log_dir: Path) -> None:
    """Configure loguru with stdout + JSON file, intercept standard logging."""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "gateway.jsonl",
        format="{message}",
        level="INFO",
        serialize=True,
        rotation="100 MB",
        retention=100,
        compression="gz",
    )

    # Intercept standard logging → loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Add request_id to logging context for correlation."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id

        with logger.contextualize(request_id=request_id):
            response = await call_next(request)

        return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unhandled exceptions with request context."""
    request_id = getattr(request.state, "request_id", None)
    user_id = getattr(request.state, "user_id", None)

    context_parts = [f"{request.method} {request.url.path}"]
    if request_id:
        context_parts.append(f"request_id={request_id}")
    if user_id:
        context_parts.append(f"user_id={user_id}")

    context = " ".join(context_parts)
    logger.exception(f"Unhandled exception on {context}: {exc}")

    await log_error(
        f"Unhandled 500: {exc}",
        method=request.method,
        path=request.url.path,
        request_id=request_id,
        user_id=user_id,
    )

    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
