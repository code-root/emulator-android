import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from db.database import create_all_tables
from services.dev_seed import seed_dev_admin_if_configured
from services.scheduler import device_scheduler
from api.routes import (
    auth,
    devices,
    fingerprint,
    fingerprint_hub,
    apps,
    proxy,
    ws,
    ws_h264,
    operation_logs,
    meta_route,
    apk_store,
    device_controls,
    network_inspector,
    frida,
    firmware_route,
)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger.info("Starting Android Emulator Farm API...")

    # Create database tables
    try:
        await create_all_tables()
        logger.info("Database ready")
        await seed_dev_admin_if_configured()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # Ensure upload directory exists
    Path(settings.UPLOADS_DIR).mkdir(parents=True, exist_ok=True)

    # Start scheduler
    device_scheduler.start()
    logger.info("Scheduler started")

    # Log all registered routes
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods = ", ".join(route.methods)
            logger.debug(f"  [{methods:25s}] {route.path}")

    logger.info("Startup complete. Ready to handle requests.")

    yield

    # Shutdown
    logger.info("Shutting down...")
    device_scheduler.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Android Emulator Farm",
    description="API for managing Android emulator instances at scale",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(devices.router, prefix="/api")
app.include_router(fingerprint.router, prefix="/api")
app.include_router(fingerprint_hub.router, prefix="/api")
app.include_router(apps.router, prefix="/api")
app.include_router(proxy.router, prefix="/api")
app.include_router(operation_logs.router, prefix="/api")
app.include_router(meta_route.router, prefix="/api")
app.include_router(apk_store.router, prefix="/api")
app.include_router(device_controls.router, prefix="/api")
app.include_router(network_inspector.router, prefix="/api")
app.include_router(frida.router, prefix="/api")
app.include_router(firmware_route.router, prefix="/api")
app.include_router(ws.router)      # no /api prefix — JPEG streaming
app.include_router(ws_h264.router) # no /api prefix — H.264 binary streaming

# Static file uploads
uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_path)), name="uploads")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "backend": settings.EMULATOR_BACKEND,
        "max_instances": settings.MAX_INSTANCES,
    }


@app.get("/api/scheduler/jobs")
async def get_scheduler_jobs():
    return device_scheduler.get_jobs_info()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
