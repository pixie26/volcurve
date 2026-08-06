"""Global normalized, redacted browser error boundary."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.error_actions import action_for
from app.clients.cortex.errors import CortexError, ErrorCode
from app.config import ConfigError
from app.domain.responses import ErrorResponse
from app.security.redaction import redact

logger = logging.getLogger("volcurve.api")

_STATUS = {
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.ENTITLEMENT_DENIED: 403,
    ErrorCode.INSTRUMENT_NOT_FOUND: 404,
    ErrorCode.NO_DATA: 404,
    ErrorCode.UPSTREAM_RATE_LIMITED: 429,
    ErrorCode.AMBIGUOUS_DUPLICATE_DATE: 409,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.INVALID_SCHEMA: 502,
    ErrorCode.SCHEMA_CHANGED: 502,
    ErrorCode.PARSE_FAILED: 502,
    ErrorCode.NORMALIZATION_FAILED: 500,
    ErrorCode.STORAGE_FAILED: 500,
    ErrorCode.CORRUPTED_RAW_CACHE: 500,
    ErrorCode.CALCULATION_FAILED: 500,
    ErrorCode.CONFIGURATION_ERROR: 503,
}

_STAGE = {
    ErrorCode.INVALID_REQUEST: "validation",
    ErrorCode.AUTHENTICATION_FAILED: "authentication",
    ErrorCode.ENTITLEMENT_DENIED: "authentication",
    ErrorCode.INSTRUMENT_NOT_FOUND: "instrument",
    ErrorCode.UPSTREAM_RATE_LIMITED: "fetch",
    ErrorCode.UPSTREAM_UNAVAILABLE: "fetch",
    ErrorCode.NO_DATA: "fetch",
    ErrorCode.INVALID_SCHEMA: "schema",
    ErrorCode.SCHEMA_CHANGED: "schema",
    ErrorCode.AMBIGUOUS_DUPLICATE_DATE: "normalization",
    ErrorCode.PARSE_FAILED: "normalization",
    ErrorCode.NORMALIZATION_FAILED: "normalization",
    ErrorCode.STORAGE_FAILED: "storage",
    ErrorCode.CORRUPTED_RAW_CACHE: "storage",
    ErrorCode.CALCULATION_FAILED: "analytics",
    ErrorCode.CONFIGURATION_ERROR: "configuration",
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _response(request: Request, code: ErrorCode, message: str) -> JSONResponse:
    payload = ErrorResponse(
        requestId=_request_id(request),
        code=code.value,
        message=redact(message),
        stage=_STAGE[code],
        suggestedAction=action_for(code),
    )
    return JSONResponse(status_code=_STATUS[code], content=payload.model_dump(mode="json"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        return _response(
            request,
            ErrorCode.INVALID_REQUEST,
            "请求未通过字段、类型或坐标组合校验；请根据 capabilities 使用合法值。",
        )

    @app.exception_handler(CortexError)
    async def cortex_error(request: Request, exc: CortexError):
        return _response(request, exc.code, exc.message)

    @app.exception_handler(ConfigError)
    async def configuration_error(request: Request, _exc: ConfigError):
        return _response(request, ErrorCode.CONFIGURATION_ERROR, "服务配置缺失或无效。")

    @app.exception_handler(ValueError)
    async def value_error(request: Request, _exc: ValueError):
        return _response(request, ErrorCode.INVALID_REQUEST, "请求参数组合无效。")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception(
            "Unhandled API error requestId=%s type=%s",
            _request_id(request),
            type(exc).__name__,
        )
        return _response(
            request,
            ErrorCode.CALCULATION_FAILED,
            "服务器处理请求时发生内部错误；未返回上游响应或实现细节。",
        )
