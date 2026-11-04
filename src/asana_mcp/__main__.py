import sys

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import get_settings
from .server import GatewayCredsMiddleware, create_mcp_server


async def health(_: Request) -> JSONResponse:
    # Pure local probe -- never calls Asana, so an Asana outage never flips
    # this container's health check (SOP §1.1).
    return JSONResponse({"status": "ok"})


def build_app() -> tuple[Starlette, "object"]:
    settings = get_settings()
    mcp = create_mcp_server(settings)
    mcp_app = mcp.streamable_http_app()
    mounted = GatewayCredsMiddleware(mcp_app)

    # Mount() does not run a sub-app's lifespan, so the streamable-http session
    # manager's task group would never start ("Task group is not initialized")
    # while /health kept returning 200. Propagate the MCP app's lifespan to the
    # outer app explicitly (SOP §7).
    app = Starlette(
        routes=[Route("/health", health), Mount("/", app=mounted)],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
    return app, settings


def main() -> None:
    import uvicorn

    app, settings = build_app()
    print(
        f"asana-mcp listening on http://{settings.mcp_http_host}:{settings.mcp_http_port}/mcp",
        file=sys.stderr,
    )
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
