from fastapi import APIRouter, Query
from infractl.modules import diagnose

router = APIRouter()

@router.get("/diagnose")
def run_diagnose(component: str = Query("argocd")):
    diagnose.run(component)
    return {"status": "success"}
