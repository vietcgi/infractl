from fastapi import APIRouter
from infractl.modules import doctor

router = APIRouter()

@router.get("/doctor")
def run_doctor():
    result = doctor.run()
    return result
