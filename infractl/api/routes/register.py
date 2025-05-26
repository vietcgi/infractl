from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import register

router = APIRouter()

class RegisterClusterRequest(BaseModel):
    file: str

@router.post("/register-cluster")
def register_cluster(req: RegisterClusterRequest):
    return register.register_cluster(req.file)
