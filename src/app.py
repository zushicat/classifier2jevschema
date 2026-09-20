from routes import jev_route, root_route

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from auth import bearer_auth_dependency

app = FastAPI(dependencies=[Depends(bearer_auth_dependency)])

# src/app.py — add one import and one middleware right after `app = FastAPI(...)`


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],  # local dev proxy; the game calls it from http://localhost:6999
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
app.include_router(root_route.router)
app.include_router(jev_route.router)
