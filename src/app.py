from routes import jev_route, root_route

from fastapi import FastAPI, Depends

from auth import bearer_auth_dependency

app = FastAPI(dependencies=[Depends(bearer_auth_dependency)])


# Import and include routers
app.include_router(root_route.router)
app.include_router(jev_route.router)
