from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import validate

router = APIRouter()

class ValidateRequest(BaseModel):
    file: str

@router.post("/validate")
def run_validate(req: ValidateRequest):
    validate.run(req.file)
    return {"status": "success"}
