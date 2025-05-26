from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import autorepair

router = APIRouter()

class AutoRepairRequest(BaseModel):
    namespace: str = "argocd"

@router.post("/autorepair")
def repair_apps(req: AutoRepairRequest):
    return autorepair.repair_all(req.namespace)
