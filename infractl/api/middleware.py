from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import os

class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.token = os.getenv("INFRACTL_API_KEY", "infractl-secret")

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/docs") or request.url.path.startswith("/openapi.json"):
            return await call_next(request)

        auth_header = request.headers.get("X-API-Key")
        if auth_header != self.token:
            raise HTTPException(status_code=403, detail="Unauthorized")
        return await call_next(request)
