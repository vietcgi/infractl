from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import autosync

router = APIRouter()

class AutoSyncRequest(BaseModel):
    namespace: str = "argocd"
    label_selector: str = "auto-sync=on"

@router.post("/autosync")
def sync_all(req: AutoSyncRequest):
    return autosync.sync_all_labeled(req.namespace, req.label_selector)
