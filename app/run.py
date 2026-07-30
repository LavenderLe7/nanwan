"""应用入口：FastAPI 装配、异常处理、启动初始化。

启动：.venv/bin/python run.py  →  http://127.0.0.1:8000
"""
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import auth
import config
import db
from routers import auth as auth_router
from routers import ent, gov
from templating import templates  # noqa: F401  (确保模板环境初始化)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title='南湾街道政企供需匹配系统', docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.load_secret_key(),
                   session_cookie='nw_session', max_age=8 * 3600, same_site='lax')
app.mount('/static', StaticFiles(directory=config.BASE_DIR / 'static'), name='static')


@app.exception_handler(auth.AuthRedirect)
async def auth_redirect_handler(request: Request, exc: auth.AuthRedirect):
    return auth.redirect_login(exc.message)


@app.get('/')
def index(request: Request):
    user = auth.current_user(request)
    if not user:
        return RedirectResponse('/login', status_code=303)
    if user['role'] == 'enterprise':
        return RedirectResponse('/ent', status_code=303)
    return RedirectResponse('/gov', status_code=303)


app.include_router(auth_router.router)
app.include_router(gov.router)
app.include_router(ent.router)


if __name__ == '__main__':
    uvicorn.run('run:app', host='127.0.0.1', port=8000, reload=False)
