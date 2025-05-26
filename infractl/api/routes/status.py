from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import status

router = APIRouter()

class StatusRequest(BaseModel):
    app_name: str
    namespace: str = "argocd"

@router.post("/status")
def app_status(req: StatusRequest):
    return status.check_status(req.app_name, req.namespace)
