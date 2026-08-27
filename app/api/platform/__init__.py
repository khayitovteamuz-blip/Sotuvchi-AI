"""
Platform API — the service operator's control panel.

Every route here reads or writes data belonging to other people's businesses, so
authorisation is attached to the router itself rather than to each endpoint: a
route added later inherits the check instead of silently shipping without one.

Split into one submodule per concern (auth, dashboard, tenants, ai, plans,
users, support, admins, billing, reports) once this crossed 1,300 lines as a
single file — the split is purely organisational, every route keeps its exact
path and behaviour. `router` is assembled here from the submodules' bare
sub-routers, so parent-level dependencies (auth) still apply everywhere.

`auth_router` stays separate: it must be reachable *before* there is a session.
"""
from fastapi import APIRouter, Depends

from app.api.platform import admins, ai, billing, dashboard, plans, reports, support, tenants, users
from app.api.platform.auth import auth_router
from app.core.platform_auth import require_platform_admin

router = APIRouter(
    prefix="/api/platform",
    tags=["Platform"],
    dependencies=[Depends(require_platform_admin)],
)
for module in (dashboard, tenants, ai, plans, users, support, admins, billing, reports):
    router.include_router(module.router)

__all__ = ["router", "auth_router"]
