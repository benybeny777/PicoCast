from fastapi import APIRouter
from core.channel_info import get_channel_info

router = APIRouter(prefix="/api", tags=["channel"])


@router.get("/channel-info")
def api_channel_info():
    return get_channel_info()
