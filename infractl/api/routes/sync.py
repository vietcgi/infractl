from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import sync

router = APIRouter()

class SyncRequest(BaseModel):
    app_name: str
    namespace: str = "argocd"

@router.post("/sync")
def sync_application(req: SyncRequest):
    return sync.trigger_sync(req.app_name, req.namespace)
