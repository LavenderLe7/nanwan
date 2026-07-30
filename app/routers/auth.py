"""登录/登出/改密。"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import auth
import db
from templating import templates

router = APIRouter()


@router.get('/login')
def login_page(request: Request, msg: str = ''):
    return templates.TemplateResponse(request, 'login.html', {'msg': msg})


@router.post('/login')
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with db.get_db() as conn:
        row = db.q1(conn, 'SELECT * FROM users WHERE username=? AND active=1', (username.strip(),))
    if not row or not auth.verify_password(password, row['password_hash']):
        return auth.redirect_login('账号或密码错误')
    auth.login_session(request, dict(row))
    return RedirectResponse('/', status_code=303)


@router.get('/logout')
def logout(request: Request):
    auth.logout_session(request)
    return RedirectResponse('/login', status_code=303)


@router.post('/passwd')
def passwd(request: Request, old: str = Form(...), new: str = Form(...)):
    user = auth.require(request, 'admin', 'gov', 'enterprise')
    if len(new) < 6:
        return auth.redirect_login('新密码至少6位')
    with db.get_db() as conn:
        row = db.q1(conn, 'SELECT * FROM users WHERE id=?', (user['id'],))
        if not row or not auth.verify_password(old, row['password_hash']):
            return auth.redirect_login('原密码错误')
        conn.execute('UPDATE users SET password_hash=? WHERE id=?',
                     (auth.hash_password(new), user['id']))
    return RedirectResponse('/?msg=密码已修改', status_code=303)
