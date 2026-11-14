"""The §5 error envelope."""
from __future__ import annotations


class ApiError(Exception):
    """An error response: ``{"error": {"code", "message"}}`` with an HTTP status."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def malformed(message: str = "the request body is not valid") -> ApiError:
    return ApiError(400, "malformed_request", message)


def invalid(message: str) -> ApiError:
    return ApiError(422, "validation_failed", message)


def unauthenticated() -> ApiError:
    return ApiError(401, "unauthenticated", "a valid bearer token is required")


def not_found(message: str = "no such resource") -> ApiError:
    return ApiError(404, "not_found", message)
