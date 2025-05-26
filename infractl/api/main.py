from fastapi import FastAPI
from infractl.api.routes import register, autorepair, summary, autosync, status, sync, bootstrap, diagnose, validate, provision, doctor
from infractl.api.middleware import AuthMiddleware
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()
app.add_middleware(AuthMiddleware)

app.include_router(bootstrap.router)
app.include_router(diagnose.router)
app.include_router(validate.router)
app.include_router(provision.router)
app.include_router(doctor.router)

app.include_router(sync.router)

app.include_router(status.router)

app.include_router(autosync.router)

app.include_router(summary.router)

app.include_router(autorepair.router)

app.include_router(register.router)
