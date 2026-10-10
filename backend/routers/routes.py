"""POST /routes: travel routes from the caller's position to up to three candidate facilities."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import config
from cache import get_cached_facilities
from middleware.auth import get_actor
from models import RoutesRequest, RoutesResponse
from services import routing
from services.rate_limit import busy_response, check_rate_limit, client_ip

router = APIRouter(tags=["routes"])


@router.post("/routes", response_model=RoutesResponse)
async def post_routes(
    body: RoutesRequest, request: Request, actor: object = Depends(get_actor)
) -> RoutesResponse | JSONResponse:
    if body.mode not in config.modes_enabled():
        raise HTTPException(422, "Travel mode not enabled")

    if getattr(actor, "is_guest", False):
        retry_after = await run_in_threadpool(
            check_rate_limit,
            str(actor.id),  # type: ignore[attr-defined]
            client_ip(request),
            bucket="routes",
        )
        if retry_after is not None:
            return busy_response(retry_after)

    cached, _ = get_cached_facilities()
    if not cached:
        raise HTTPException(503, "Facilities unavailable")
    # The request carries ids only: coordinates come from our own list, so this endpoint cannot be
    # used to route between arbitrary points on our Geoapify quota.
    by_id = {str(facility["id"]): facility for facility in cached}
    if any(facility_id not in by_id for facility_id in body.facility_ids):
        raise HTTPException(404, "Unknown facility")
    candidates = [by_id[facility_id] for facility_id in body.facility_ids]

    try:
        routes = await routing.routes_for(body.origin.model_dump(), candidates, body.mode)
    except routing.RoutingNotConfigured as exc:
        raise HTTPException(503, "Routing unavailable") from exc

    fastest = routing.fastest_facility_id(routes)
    if fastest is None:
        raise HTTPException(502, "No route found")
    return RoutesResponse(mode=body.mode, routes=routes, fastest_facility_id=fastest)
