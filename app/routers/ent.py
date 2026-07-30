"""企业端路由：我的资料、场景机会、我的提交。

config.ENTERPRISE_PORTAL_ENABLED=False 时入口整体关闭（返回提示页），
功能代码完整保留，部署到服务器后改配置即开放。
"""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import auth
import config
import db
from routers.gov import ENTERPRISE_FIELDS
from templating import templates

router = APIRouter(prefix='/ent')


def _u(request: Request):
    user = auth.require(request, 'enterprise', 'admin')
    if not config.ENTERPRISE_PORTAL_ENABLED and user['role'] == 'enterprise':
        raise auth.AuthRedirect('企业端暂未开放，请联系街道工作人员')
    if not user.get('enterprise_id'):
        raise auth.AuthRedirect('该账号未关联企业')
    return user


@router.get('')
def home(request: Request):
    user = _u(request)
    eid = user['enterprise_id']
    with db.get_db() as conn:
        e = db.q1(conn, 'SELECT * FROM enterprises WHERE id=?', (eid,))
        subs = db.q(conn, 'SELECT * FROM submissions WHERE enterprise_id=? ORDER BY id DESC LIMIT 5', (eid,))
    return templates.TemplateResponse(request, 'ent/home.html', {'user': user, 'e': e, 'subs': subs,
        'fields': ENTERPRISE_FIELDS})


@router.post('/profile/submit')
async def profile_submit(request: Request):
    """企业提交资料修改申请（不直接改库，走政府审核）。"""
    user = _u(request)
    form = await request.form()
    payload = {k: (form.get(k) or '').strip() for k in ENTERPRISE_FIELDS if form.get(k)}
    payload.pop('name', None)  # 企业名不允许自改，避免撞库
    with db.get_db() as conn:
        conn.execute('INSERT INTO submissions(enterprise_id, user_id, type, payload) VALUES(?,?,?,?)',
                     (user['enterprise_id'], user['id'], '资料修改',
                      json.dumps(payload, ensure_ascii=False)))
    return RedirectResponse('/ent/submissions', status_code=303)


@router.get('/opportunities')
def opportunities(request: Request, mode: str = 'scenario'):
    """本企业匹配到的场景机会 / 可申报政策。"""
    user = _u(request)
    with db.get_db() as conn:
        scenario_rows = db.q(conn, '''SELECT m.*, s.name AS scen_name, s.source, s.domain,
                    s.landing_area, s.lead_dept, s.intro FROM matches m
            JOIN scenarios s ON s.id=m.scenario_id
            WHERE m.enterprise_id=? AND m.status!='已排除'
            ORDER BY m.total_score DESC LIMIT 30''', (user['enterprise_id'],))
        policy_rows = db.q(conn, '''SELECT pm.*, p.name AS policy_name, p.level,
                    p.category, p.support_type, p.amount_text, p.deadline
               FROM policy_matches pm
               JOIN policies p ON p.id=pm.policy_id
               WHERE pm.enterprise_id=? AND pm.status!='已排除'
                 AND p.status='已发布'
                 AND (p.deadline IS NULL OR p.deadline >= date('now') OR p.deadline='常年受理'
                      OR p.deadline='免申即享')
               ORDER BY pm.reason NOT LIKE '%不满足%' DESC, pm.id LIMIT 30''',
            (user['enterprise_id'],))
    return templates.TemplateResponse(request, 'ent/opportunities.html', {
        'user': user, 'rows': scenario_rows, 'policy_rows': policy_rows, 'mode': mode,
    })


@router.post('/opportunities/intent')
def opportunity_intent(request: Request, scenario_name: str = Form(...),
                       message: str = Form('')):
    """对某场景申报合作意向。"""
    user = _u(request)
    with db.get_db() as conn:
        conn.execute('INSERT INTO submissions(enterprise_id, user_id, type, payload) VALUES(?,?,?,?)',
                     (user['enterprise_id'], user['id'], '合作意向',
                      json.dumps({'场景': scenario_name, '说明': message}, ensure_ascii=False)))
    return RedirectResponse('/ent/submissions', status_code=303)


@router.get('/submissions')
def my_submissions(request: Request):
    user = _u(request)
    with db.get_db() as conn:
        rows = db.q(conn, 'SELECT * FROM submissions WHERE enterprise_id=? ORDER BY id DESC',
                    (user['enterprise_id'],))
    parsed = [(r, json.loads(r['payload'] or '{}')) for r in rows]
    return templates.TemplateResponse(request, 'ent/submissions.html', {'user': user, 'rows': parsed})
