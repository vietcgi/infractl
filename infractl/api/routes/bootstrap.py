from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import bootstrap
from infractl.modules.utils import logger

router = APIRouter()

class BootstrapRequest(BaseModel):
    cluster_path: str
    clean: bool = False

@router.post("/bootstrap")
def run_bootstrap(req: BootstrapRequest):
    logger.info(f"[BOOTSTRAP] Cluster={req.cluster_path}, Clean={req.clean}")
    bootstrap.run(req.cluster_path, req.clean)
    return {"status": "success"}
