from fastapi import APIRouter
from pydantic import BaseModel
from infractl.modules import summary
from infractl.modules.utils import send_slack_alert

router = APIRouter()

class SummaryRequest(BaseModel):
    namespace: str = "argocd"

@router.post("/summary")
def get_sync_summary(req: SummaryRequest):
    result = summary.get_summary(req.namespace)
    webhook = os.getenv("INFRACTL_SLACK_WEBHOOK")
    if webhook:
        msg = f"[Sync Summary] Total: {result['total']}, Synced: {result['synced']}, OutOfSync: {result['out_of_sync']}, Healthy: {result['healthy']}, Degraded: {result['degraded']}"
        send_slack_alert(webhook, msg)
    return result
