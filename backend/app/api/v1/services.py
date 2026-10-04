"""Services endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/services")
async def get_services() -> dict[str, str]:
    """Get service list."""
    return {"message": "Not implemented"}


@router.get("/services/{service}")
async def get_service(service: str) -> dict[str, str]:
    """Get service details."""
    return {"message": "Not implemented"}
