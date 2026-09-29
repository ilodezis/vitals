"""One error contract for everything under ``/api/``.

The server-rendered pages answer a failure with a redirect or ``{"detail": ...}``
and their tests pin that. The React client wants a body it can switch on, and a
fetch must never be redirected to a login page — so under ``/api/`` every failure
is ``{"error": <code>, ...}``:

===  =========================================  ================================
401  ``{"error": "unauthenticated"}``            no session (``NotAuthenticated``)
404  ``{"error": "module_disabled"}``            ``ModuleDisabled``
404  ``{"error": "not_found"}``                  no such path / row
409  ``{"error": "conflict", "violations"}``     ``ConflictBlocked`` — see below
400  ``{"error": "invalid", "message"}``         ``ValueError`` from a service
422  FastAPI's own ``{"detail": [...]}``         the request did not parse
===  =========================================  ================================

The first three come from the app's exception handlers (``web/main.py``), which
ask :func:`is_api_request` before choosing a body. 409 and 400 are mapped here, on
the route class, so an endpoint just calls its service and lets the exception
through instead of repeating the same ``try/except``.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import pydantic
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from vitals.services.conflict_engine import ConflictBlocked
from web.api.schemas.errors import ConflictBody, InvalidBody
from web.config import API_PATH_PREFIX

# For the ``responses=`` of an endpoint that writes: lands in the OpenAPI schema,
# so the generated client types the 400 and 409 bodies.
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_400_BAD_REQUEST: {"model": InvalidBody},
    status.HTTP_409_CONFLICT: {"model": ConflictBody},
}


def is_api_request(request: Request) -> bool:
    return request.url.path.startswith(API_PATH_PREFIX)


def unauthenticated() -> JSONResponse:
    return JSONResponse({"error": "unauthenticated"}, status_code=status.HTTP_401_UNAUTHORIZED)


def module_disabled() -> JSONResponse:
    return JSONResponse({"error": "module_disabled"}, status_code=status.HTTP_404_NOT_FOUND)


def not_found() -> JSONResponse:
    return JSONResponse({"error": "not_found"}, status_code=status.HTTP_404_NOT_FOUND)


class ApiRoute(APIRoute):
    """Turns the two exceptions every write can raise into their JSON bodies."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except ConflictBlocked as exc:
                return JSONResponse(
                    {
                        "error": "conflict",
                        "violations": [v.to_dict() for v in exc.violations],
                    },
                    status_code=status.HTTP_409_CONFLICT,
                )
            except pydantic.ValidationError:
                # A ``ValueError`` too, but a malformed model inside the endpoint
                # is a defect, not the caller's mistake.
                raise
            except ValueError as exc:
                return JSONResponse(
                    {"error": "invalid", "message": str(exc)},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        return guarded


def _operation_id(route: APIRoute) -> str:
    return route.name


class ApiRouter(APIRouter):
    """``APIRouter`` for ``/api/v1`` endpoints: the error mapping above, and
    operation ids that are the function names (``read_session``, not
    ``read_session_api_v1_session_get``), which is what the generated client
    exposes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", ApiRoute)
        kwargs.setdefault("generate_unique_id_function", _operation_id)
        super().__init__(*args, **kwargs)
