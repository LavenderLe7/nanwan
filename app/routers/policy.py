"""政策轨路由：政策 CRUD、匹配重算、匹配工作台 API。"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import auth
import db
from matching import policy_engine
from templating import templates

router = APIRouter()  # 由 gov.router 通过 include_router 挂载，不设独立 prefix

PAGE_SIZE = 20

POLICY_FIELDS = ['name', 'level', 'category', 'support_type', 'amount_text',
                 'deadline', 'source_url', 'status']


def _u(request: Request):
    return auth.require(request, 'admin', 'gov')


# ---------- 政策列表 ----------

@router.get('/policies')
def policies(request: Request, kw: str = '', level: str = '', category: str = '',
             status: str = '', page: int = 1):
    user = _u(request)
    where, args = ['1=1'], []
    if kw:
        where.append('name LIKE ?')
        args.append(f'%{kw}%')
    if level:
        where.append('level=?')
        args.append(level)
    if category:
        where.append('category=?')
        args.append(category)
    if status:
        where.append('status=?')
        args.append(status)
    cond = ' AND '.join(where)
    with db.get_db() as conn:
        total = db.q1(conn, f'SELECT COUNT(*) c FROM policies WHERE {cond}', args)['c']
        rows = db.q(conn,
            f'SELECT p.*, (SELECT COUNT(*) FROM policy_matches WHERE policy_id=p.id) AS match_count '
            f'FROM policies p WHERE {cond} ORDER BY p.updated_at DESC LIMIT ? OFFSET ?',
            (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE))
    return templates.TemplateResponse(request, 'gov/policies.html', {
        'user': user, 'rows': rows, 'kw': kw, 'level': level,
        'category': category, 'status': status,
        'page': page, 'pages': max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        'total': total, 'active': 'policy',
    })


# ---------- 政策新建 ----------

@router.get('/policies/new')
def policy_new(request: Request):
    user = _u(request)
    return templates.TemplateResponse(request, 'gov/policy_edit.html', {
        'user': user, 'p': {}, 'clauses': [], 'action': '/gov/policies/new',
        'active': 'policy',
    })


@router.post('/policies/new')
async def policy_create(request: Request):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in POLICY_FIELDS}
    if not data['name']:
        return RedirectResponse('/gov/policies', status_code=303)
    data['status'] = data['status'] or '已发布'
    with db.get_db() as conn:
        cur = conn.execute(
            f"INSERT INTO policies({', '.join(POLICY_FIELDS)}) VALUES({', '.join('?' * len(POLICY_FIELDS))})",
            tuple(data[k] for k in POLICY_FIELDS),
        )
        pid = cur.lastrowid
        # 条款
        _upsert_clauses(conn, pid, form)
    return RedirectResponse(f'/gov/policies/{pid}', status_code=303)


# ---------- 政策详情 ----------

@router.get('/policies/{pid}')
def policy_detail(request: Request, pid: int):
    user = _u(request)
    with db.get_db() as conn:
        p = db.q1(conn, 'SELECT * FROM policies WHERE id=?', (pid,))
        if not p:
            return RedirectResponse('/gov/policies', status_code=303)
        clauses = db.q(conn,
            'SELECT * FROM policy_clauses WHERE policy_id=? ORDER BY sort_order, id', (pid,))
        matches = db.q(conn,
            '''SELECT pm.*, e.name AS ent_name, e.category_bucket,
               e.registered_capital, e.employee_count
               FROM policy_matches pm
               JOIN enterprises e ON e.id=pm.enterprise_id
               WHERE pm.policy_id=? AND pm.status!='已排除'
               ORDER BY pm.reason NOT LIKE '%不满足%' DESC, pm.id''', (pid,))
    return templates.TemplateResponse(request, 'gov/policy_detail.html', {
        'user': user, 'p': p, 'clauses': clauses, 'matches': matches,
        'active': 'policy',
    })


# ---------- 政策编辑 ----------

@router.get('/policies/{pid}/edit')
def policy_edit(request: Request, pid: int):
    user = _u(request)
    with db.get_db() as conn:
        p = db.q1(conn, 'SELECT * FROM policies WHERE id=?', (pid,))
        if not p:
            return RedirectResponse('/gov/policies', status_code=303)
        clauses = db.q(conn,
            'SELECT * FROM policy_clauses WHERE policy_id=? ORDER BY sort_order, id', (pid,))
    return templates.TemplateResponse(request, 'gov/policy_edit.html', {
        'user': user, 'p': p, 'clauses': clauses,
        'action': f'/gov/policies/{pid}/edit', 'active': 'policy',
    })


@router.post('/policies/{pid}/edit')
async def policy_update(request: Request, pid: int):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in POLICY_FIELDS}
    with db.get_db() as conn:
        sets = ', '.join(f'{k}=?' for k in POLICY_FIELDS)
        conn.execute(
            f"UPDATE policies SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
            (*[data[k] for k in POLICY_FIELDS], pid),
        )
        # 条款：先删后插
        conn.execute('DELETE FROM policy_clauses WHERE policy_id=?', (pid,))
        _upsert_clauses(conn, pid, form)
    return RedirectResponse(f'/gov/policies/{pid}', status_code=303)


# ---------- 删除 ----------

@router.post('/policies/{pid}/delete')
def policy_delete(request: Request, pid: int):
    _u(request)
    with db.get_db() as conn:
        conn.execute('DELETE FROM policy_matches WHERE policy_id=?', (pid,))
        conn.execute('DELETE FROM policy_clauses WHERE policy_id=?', (pid,))
        conn.execute('DELETE FROM policies WHERE id=?', (pid,))
    return RedirectResponse('/gov/policies', status_code=303)


# ---------- 条款处理 ----------

def _upsert_clauses(conn, policy_id: int, form):
    """从表单中提取条款数组，批量插入。表单字段名：clause_type_N / clause_content_N。"""
    i = 0
    while True:
        ct_key = f'clause_type_{i}'
        cc_key = f'clause_content_{i}'
        if ct_key not in form and cc_key not in form:
            break
        ct = (form.get(ct_key) or '').strip()
        cc = (form.get(cc_key) or '').strip()
        if ct and cc:
            conn.execute(
                'INSERT INTO policy_clauses(policy_id, clause_type, content, sort_order) '
                'VALUES(?, ?, ?, ?)',
                (policy_id, ct, cc, i),
            )
        i += 1


# ---------- 匹配重算 ----------

@router.post('/policies/{pid}/recompute')
def policy_recompute(request: Request, pid: int):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse(f'/gov/policies/{pid}', status_code=303)
    with db.get_db() as conn:
        n = policy_engine.recompute_policy_matches(conn, pid)
        matches = db.q(conn,
            '''SELECT pm.*, e.name AS ent_name, e.category_bucket,
               e.registered_capital, e.employee_count
               FROM policy_matches pm
               JOIN enterprises e ON e.id=pm.enterprise_id
               WHERE pm.policy_id=? AND pm.status!='已排除'
               ORDER BY pm.reason NOT LIKE '%不满足%' DESC, pm.id''', (pid,))
    return templates.TemplateResponse(request, 'gov/_policy_match_rows.html', {
        'matches': matches, 'policy_id': pid, 'user': user,
    })


@router.post('/policies/recompute-all')
def policy_recompute_all(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov/policies', status_code=303)
    with db.get_db() as conn:
        stats = policy_engine.recompute_all_policies(conn)
    return templates.TemplateResponse(request, 'gov/_policy_recompute_done.html', {
        'stats': stats,
    })


# ---------- 匹配状态 ----------

@router.post('/api/policy-matches/{mid}/status')
def policy_match_status(request: Request, mid: int, status: str = Form(...)):
    _u(request)
    if status not in ('候选', '已对接', '已排除'):
        status = '候选'
    with db.get_db() as conn:
        conn.execute('UPDATE policy_matches SET status=? WHERE id=?', (status, mid))
    return {'ok': True}


# ---------- 匹配工作台 API ----------

@router.get('/api/policy-matches/{pid}')
def api_policy_matches(request: Request, pid: int):
    _u(request)
    with db.get_db() as conn:
        p = db.q1(conn, 'SELECT * FROM policies WHERE id=?', (pid,))
        matches = db.q(conn,
            '''SELECT pm.*, e.name AS ent_name, e.category_bucket,
               e.registered_capital, e.employee_count
               FROM policy_matches pm
               JOIN enterprises e ON e.id=pm.enterprise_id
               WHERE pm.policy_id=? AND pm.status!='已排除'
               ORDER BY pm.reason NOT LIKE '%不满足%' DESC, pm.id''', (pid,))
    return templates.TemplateResponse(request, 'gov/_policy_match_results.html', {
        'matches': matches, 'target': p, 'user': {'role': 'gov'},
    })
