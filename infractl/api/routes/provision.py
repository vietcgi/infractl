from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import provision

router = APIRouter()

class ProvisionRequest(BaseModel):
    inventory: str = "ansible/hosts.ini"
    playbook: str = "ansible/playbook.yml"

@router.post("/provision")
def run_provision(req: ProvisionRequest):
    result = provision.run(req.inventory, req.playbook)
    return result
