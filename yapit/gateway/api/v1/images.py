from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from yapit.gateway.deps import SettingsDep

router = APIRouter(prefix="/images", tags=["Images"])


@router.get("/{doc_hash}/{filename}")
async def get_image(doc_hash: str, filename: str, settings: SettingsDep) -> FileResponse:
    """Serve extracted document images (local storage only, unused with R2)."""
    if not settings.images_dir:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image storage not configured")
    images_dir = Path(settings.images_dir)
    file_path = images_dir / doc_hash / filename

    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    if not file_path.resolve().is_relative_to(images_dir.resolve()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    return FileResponse(file_path)
