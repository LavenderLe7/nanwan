"""认证与密码：pbkdf2 哈希（标准库）、session 读写、角色守卫。"""
import hashlib
import hmac
import os

from fastapi import Request
from fastapi.responses import RedirectResponse

ITERATIONS = 100_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'{salt}${digest}'


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split('$')
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return hmac.compare_digest(candidate, digest)


# ---------- session ----------

def login_session(request: Request, user: dict):
    request.session['user'] = {
        'id': user['id'],
        'username': user['username'],
        'display_name': user['display_name'] or user['username'],
        'role': user['role'],
        'enterprise_id': user['enterprise_id'],
    }


def logout_session(request: Request):
    request.session.clear()


def current_user(request: Request) -> dict | None:
    return request.session.get('user')


class AuthRedirect(Exception):
    """未登录/越权时抛出，由 app 统一处理为跳转登录页。"""

    def __init__(self, message: str = ''):
        self.message = message


def require(request: Request, *roles: str) -> dict:
    """要求登录且角色在 roles 内；否则抛 AuthRedirect。"""
    user = current_user(request)
    if not user:
        raise AuthRedirect('请先登录')
    if roles and user['role'] not in roles:
        raise AuthRedirect('无权访问该页面')
    return user


def redirect_login(message: str = '') -> RedirectResponse:
    url = '/login'
    if message:
        from urllib.parse import quote
        url += f'?msg={quote(message)}'
    return RedirectResponse(url, status_code=303)
