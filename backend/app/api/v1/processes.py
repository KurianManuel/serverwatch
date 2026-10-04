"""Processes endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/processes")
async def get_processes() -> dict[str, str]:
    """Get process list."""
    return {"message": "Not implemented"}


@router.get("/processes/{pid}")
async def get_process(pid: int) -> dict[str, str]:
    """Get process details."""
    return {"message": "Not implemented"}
