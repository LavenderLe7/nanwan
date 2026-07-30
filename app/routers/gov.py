"""政府端路由：工作台、企业库、场景库、匹配工作台、项目跟踪、审核中心、数据管理、用户管理。"""
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import auth
import config
import db
from ingest import excel_import
from matching import embed, engine
from routers import policy
from templating import templates

router = APIRouter(prefix='/gov')
router.include_router(policy.router)

PAGE_SIZE = 20

ENTERPRISE_FIELDS = ['name', 'category_bucket', 'category_raw', 'intro', 'capability',
                     'applicable_scenes', 'qualifications', 'positioning', 'main_business',
                     'core_products', 'core_tech', 'clients_cases']
SCENARIO_FIELDS = ['name', 'domain', 'intro', 'landing_area', 'lead_dept',
                   'main_tech', 'ref_case', 'potential_enterprises', 'source', 'status']


def _u(request: Request):
    return auth.require(request, 'admin', 'gov')


# ---------- 工作台 ----------

@router.get('')
def dashboard(request: Request):
    user = _u(request)
    with db.get_db() as conn:
        stats = {
            'enterprises': db.q1(conn, 'SELECT COUNT(*) c FROM enterprises')['c'],
            'scenes25': db.q1(conn, "SELECT COUNT(*) c FROM scenarios WHERE source='南湾25'")['c'],
            'scenes_reserve': db.q1(conn, "SELECT COUNT(*) c FROM scenarios WHERE source='储备库'")['c'],
            'projects_active': db.q1(conn, "SELECT COUNT(*) c FROM projects WHERE status IN ('对接中','推进中')")['c'],
            'policies': db.q1(conn, "SELECT COUNT(*) c FROM policies WHERE status='已发布'")['c'],
            'pending_subs': db.q1(conn, "SELECT COUNT(*) c FROM submissions WHERE status='待审核'")['c'],
            'matched25': db.q1(conn, '''SELECT COUNT(DISTINCT s.id) c FROM scenarios s
                LEFT JOIN matches m ON m.scenario_id=s.id AND m.status!='已排除'
                LEFT JOIN projects p ON p.scenario_id=s.id
                WHERE s.source='南湾25' AND (m.id IS NOT NULL OR p.id IS NOT NULL)''')['c'],
        }
        recent_logs = db.q(conn, '''SELECT l.*, p.title, e.name AS ent_name FROM progress_logs l
            JOIN projects p ON p.id=l.project_id JOIN enterprises e ON e.id=p.enterprise_id
            ORDER BY l.id DESC LIMIT 8''')
        pending = db.q(conn, '''SELECT s.*, e.name AS ent_name FROM submissions s
            JOIN enterprises e ON e.id=s.enterprise_id
            WHERE s.status='待审核' ORDER BY s.id DESC LIMIT 5''')
    return templates.TemplateResponse(request, 'gov/dashboard.html', {'user': user, 'stats': stats,
        'recent_logs': recent_logs, 'pending': pending,
        'semantic_ok': embed.available(), 'semantic_hint': embed.unavailable_reason(),
    })


# ---------- 企业库 ----------

@router.get('/enterprises')
def enterprises(request: Request, kw: str = '', bucket: str = '', page: int = 1):
    user = _u(request)
    where, args = ['1=1'], []
    if kw:
        where.append('(name LIKE ? OR intro LIKE ? OR capability LIKE ?)')
        args += [f'%{kw}%'] * 3
    if bucket:
        where.append('category_bucket=?')
        args.append(bucket)
    cond = ' AND '.join(where)
    with db.get_db() as conn:
        total = db.q1(conn, f'SELECT COUNT(*) c FROM enterprises WHERE {cond}', args)['c']
        rows = db.q(conn, f'SELECT * FROM enterprises WHERE {cond} ORDER BY updated_at DESC LIMIT ? OFFSET ?',
                    (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE))
        buckets = db.q(conn, 'SELECT DISTINCT category_bucket b FROM enterprises WHERE b IS NOT NULL AND b!="" ORDER BY b')
    return templates.TemplateResponse(request, 'gov/enterprises.html', {'user': user, 'rows': rows, 'kw': kw, 'bucket': bucket,
        'buckets': [b['b'] for b in buckets], 'page': page,
        'pages': max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE), 'total': total,
    })


@router.get('/enterprises/new')
def enterprise_new(request: Request):
    user = _u(request)
    return templates.TemplateResponse(request, 'gov/enterprise_edit.html', {'user': user, 'e': {}, 'action': '/gov/enterprises/new'})


@router.post('/enterprises/new')
async def enterprise_create(request: Request):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in ENTERPRISE_FIELDS}
    if not data['name']:
        return RedirectResponse('/gov/enterprises', status_code=303)
    from ingest.normalize import norm_name
    with db.get_db() as conn:
        cur = conn.execute(
            f"INSERT INTO enterprises(name_norm, {', '.join(ENTERPRISE_FIELDS)}) VALUES(?, {', '.join('?' * len(ENTERPRISE_FIELDS))})",
            (norm_name(data['name']), *[data[k] for k in ENTERPRISE_FIELDS]))
        engine.refresh_entity(conn, 'enterprise', cur.lastrowid)
    return RedirectResponse('/gov/enterprises', status_code=303)


@router.get('/enterprises/{eid}')
def enterprise_detail(request: Request, eid: int):
    user = _u(request)
    with db.get_db() as conn:
        e = db.q1(conn, 'SELECT * FROM enterprises WHERE id=?', (eid,))
        if not e:
            return RedirectResponse('/gov/enterprises', status_code=303)
        matches = db.q(conn, '''SELECT m.*, s.name AS scen_name, s.source, s.domain FROM matches m
            JOIN scenarios s ON s.id=m.scenario_id
            WHERE m.enterprise_id=? AND m.status!='已排除' ORDER BY m.total_score DESC LIMIT 10''', (eid,))
        policy_matches = db.q(conn, '''SELECT pm.*, p.name AS policy_name, p.level, p.category,
                    p.support_type, p.amount_text, p.deadline
               FROM policy_matches pm
               JOIN policies p ON p.id=pm.policy_id
               WHERE pm.enterprise_id=? AND pm.status!='已排除'
               ORDER BY pm.reason NOT LIKE '%不满足%' DESC, pm.id LIMIT 20''', (eid,))
        projects = db.q(conn, 'SELECT * FROM projects WHERE enterprise_id=? ORDER BY id DESC', (eid,))
        subs = db.q(conn, 'SELECT * FROM submissions WHERE enterprise_id=? ORDER BY id DESC LIMIT 5', (eid,))
    return templates.TemplateResponse(request, 'gov/enterprise_detail.html', {'user': user, 'e': e, 'matches': matches,
        'policy_matches': policy_matches, 'projects': projects, 'subs': subs})


@router.get('/enterprises/{eid}/edit')
def enterprise_edit(request: Request, eid: int):
    user = _u(request)
    with db.get_db() as conn:
        e = db.q1(conn, 'SELECT * FROM enterprises WHERE id=?', (eid,))
    return templates.TemplateResponse(request, 'gov/enterprise_edit.html', {'user': user, 'e': e or {}, 'action': f'/gov/enterprises/{eid}/edit'})


@router.post('/enterprises/{eid}/edit')
async def enterprise_update(request: Request, eid: int):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in ENTERPRISE_FIELDS}
    from ingest.normalize import norm_name
    with db.get_db() as conn:
        sets = ', '.join(f'{k}=?' for k in ENTERPRISE_FIELDS)
        conn.execute(f"UPDATE enterprises SET {sets}, name_norm=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (*[data[k] for k in ENTERPRISE_FIELDS], norm_name(data['name']), eid))
        engine.refresh_entity(conn, 'enterprise', eid)
    return RedirectResponse(f'/gov/enterprises/{eid}', status_code=303)


@router.post('/enterprises/{eid}/delete')
def enterprise_delete(request: Request, eid: int):
    _u(request)
    with db.get_db() as conn:
        conn.execute('DELETE FROM matches WHERE enterprise_id=?', (eid,))
        conn.execute('DELETE FROM embeddings WHERE owner_type="enterprise" AND owner_id=?', (eid,))
        conn.execute('DELETE FROM projects WHERE enterprise_id=?', (eid,))
        conn.execute('DELETE FROM submissions WHERE enterprise_id=?', (eid,))
        conn.execute('DELETE FROM enterprises WHERE id=?', (eid,))
    return RedirectResponse('/gov/enterprises', status_code=303)


# ---------- 场景库 ----------

@router.get('/scenarios')
def scenarios(request: Request, source: str = '南湾25', kw: str = '', domain: str = '', page: int = 1):
    user = _u(request)
    where, args = ['source=?'], [source]
    if kw:
        where.append('(name LIKE ? OR intro LIKE ?)')
        args += [f'%{kw}%'] * 2
    if domain:
        where.append('domain=?')
        args.append(domain)
    cond = ' AND '.join(where)
    with db.get_db() as conn:
        total = db.q1(conn, f'SELECT COUNT(*) c FROM scenarios WHERE {cond}', args)['c']
        rows = db.q(conn, f'SELECT * FROM scenarios WHERE {cond} ORDER BY id LIMIT ? OFFSET ?',
                    (*args, PAGE_SIZE, (page - 1) * PAGE_SIZE))
        domains = db.q(conn, 'SELECT DISTINCT domain d FROM scenarios WHERE source=? AND d IS NOT NULL AND d!="" ORDER BY d',
                       (source,))
        counts = {r['source']: r['c'] for r in db.q(conn, 'SELECT source, COUNT(*) c FROM scenarios GROUP BY source')}
    return templates.TemplateResponse(request, 'gov/scenarios.html', {'user': user, 'rows': rows, 'source': source, 'kw': kw,
        'domain': domain, 'domains': [d['d'] for d in domains], 'counts': counts,
        'page': page, 'pages': max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE), 'total': total})


@router.get('/scenarios/new')
def scenario_new(request: Request):
    user = _u(request)
    return templates.TemplateResponse(request, 'gov/scenario_edit.html', {'user': user, 's': {}, 'action': '/gov/scenarios/new'})


@router.post('/scenarios/new')
async def scenario_create(request: Request):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in SCENARIO_FIELDS}
    if not data['name']:
        return RedirectResponse('/gov/scenarios', status_code=303)
    data['source'] = data['source'] or '储备库'
    data['status'] = data['status'] or '储备'
    with db.get_db() as conn:
        cur = conn.execute(
            f"INSERT INTO scenarios({', '.join(SCENARIO_FIELDS)}) VALUES({', '.join('?' * len(SCENARIO_FIELDS))})",
            tuple(data[k] for k in SCENARIO_FIELDS))
        engine.refresh_entity(conn, 'scenario', cur.lastrowid)
    return RedirectResponse('/gov/scenarios?source=' + data['source'], status_code=303)


@router.get('/scenarios/{sid}')
def scenario_detail(request: Request, sid: int):
    user = _u(request)
    with db.get_db() as conn:
        s = db.q1(conn, 'SELECT * FROM scenarios WHERE id=?', (sid,))
        if not s:
            return RedirectResponse('/gov/scenarios', status_code=303)
        linked = db.q1(conn, 'SELECT id, name, source FROM scenarios WHERE id=?', (s['linked_scenario_id'],)) \
            if s['linked_scenario_id'] else None
        matches = db.q(conn, '''SELECT m.*, e.name AS ent_name, e.category_bucket FROM matches m
            JOIN enterprises e ON e.id=m.enterprise_id
            WHERE m.scenario_id=? AND m.status!='已排除' ORDER BY m.total_score DESC LIMIT 15''', (sid,))
        projects = db.q(conn, '''SELECT p.*, e.name AS ent_name FROM projects p
            JOIN enterprises e ON e.id=p.enterprise_id WHERE p.scenario_id=? ORDER BY p.id DESC''', (sid,))
    return templates.TemplateResponse(request, 'gov/scenario_detail.html', {'user': user, 's': s, 'linked': linked,
        'matches': matches, 'projects': projects})


@router.get('/scenarios/{sid}/edit')
def scenario_edit(request: Request, sid: int):
    user = _u(request)
    with db.get_db() as conn:
        s = db.q1(conn, 'SELECT * FROM scenarios WHERE id=?', (sid,))
    return templates.TemplateResponse(request, 'gov/scenario_edit.html', {'user': user, 's': s or {}, 'action': f'/gov/scenarios/{sid}/edit'})


@router.post('/scenarios/{sid}/edit')
async def scenario_update(request: Request, sid: int):
    user = _u(request)
    form = await request.form()
    data = {k: (form.get(k) or '').strip() for k in SCENARIO_FIELDS}
    with db.get_db() as conn:
        sets = ', '.join(f'{k}=?' for k in SCENARIO_FIELDS)
        conn.execute(f"UPDATE scenarios SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                     (*[data[k] for k in SCENARIO_FIELDS], sid))
        engine.refresh_entity(conn, 'scenario', sid)
    return RedirectResponse(f'/gov/scenarios/{sid}', status_code=303)


@router.post('/scenarios/{sid}/delete')
def scenario_delete(request: Request, sid: int):
    _u(request)
    with db.get_db() as conn:
        conn.execute('DELETE FROM matches WHERE scenario_id=?', (sid,))
        conn.execute('DELETE FROM embeddings WHERE owner_type="scenario" AND owner_id=?', (sid,))
        conn.execute('DELETE FROM scenarios WHERE id=?', (sid,))
    return RedirectResponse('/gov/scenarios', status_code=303)


# ---------- 匹配工作台 ----------

@router.get('/match')
def match_workbench(request: Request, mode: str = 'scenario'):
    user = _u(request)
    with db.get_db() as conn:
        scen_list = db.q(conn, 'SELECT id, name, source, domain FROM scenarios ORDER BY source, id')
        ent_list = db.q(conn, 'SELECT id, name, category_bucket FROM enterprises ORDER BY name')
        policy_list = db.q(conn, "SELECT id, name, category FROM policies WHERE status='已发布' ORDER BY category, id")
    return templates.TemplateResponse(request, 'gov/match.html', {'user': user, 'mode': mode,
        'scen_list': scen_list, 'ent_list': ent_list, 'policy_list': policy_list,
        'semantic_ok': embed.available(), 'semantic_hint': embed.unavailable_reason()})


@router.get('/api/match/scenario/{sid}')
def api_match_scenario(request: Request, sid: int):
    _u(request)
    with db.get_db() as conn:
        rows = db.q(conn, '''SELECT m.*, e.name AS ent_name, e.category_bucket, e.qualifications
            FROM matches m JOIN enterprises e ON e.id=m.enterprise_id
            WHERE m.scenario_id=? ORDER BY m.total_score DESC''', (sid,))
        scen = db.q1(conn, 'SELECT * FROM scenarios WHERE id=?', (sid,))
    return templates.TemplateResponse(request, 'gov/_match_results.html', {'rows': rows, 'target': scen, 'mode': 'scenario'})


@router.get('/api/match/enterprise/{eid}')
def api_match_enterprise(request: Request, eid: int):
    _u(request)
    with db.get_db() as conn:
        rows = db.q(conn, '''SELECT m.*, s.name AS scen_name, s.source, s.domain, s.lead_dept
            FROM matches m JOIN scenarios s ON s.id=m.scenario_id
            WHERE m.enterprise_id=? ORDER BY m.total_score DESC''', (eid,))
        ent = db.q1(conn, 'SELECT * FROM enterprises WHERE id=?', (eid,))
    return templates.TemplateResponse(request, 'gov/_match_results.html', {'rows': rows, 'target': ent, 'mode': 'enterprise'})


@router.post('/api/match/{mid}/status')
def api_match_status(request: Request, mid: int, status: str = Form(...)):
    _u(request)
    if status not in ('候选', '已对接', '已排除'):
        status = '候选'
    with db.get_db() as conn:
        conn.execute('UPDATE matches SET status=? WHERE id=?', (status, mid))
    return {'ok': True}


@router.post('/api/match/{mid}/to_project')
def api_match_to_project(request: Request, mid: int):
    _u(request)
    with db.get_db() as conn:
        m = db.q1(conn, 'SELECT * FROM matches WHERE id=?', (mid,))
        if not m:
            return {'ok': False}
        s = db.q1(conn, 'SELECT * FROM scenarios WHERE id=?', (m['scenario_id'],))
        conn.execute('''INSERT INTO projects(enterprise_id, scenario_id, title, planned_scene,
                        dock_dept, status) VALUES(?,?,?,?,?, '对接中')''',
                     (m['enterprise_id'], m['scenario_id'],
                      s['name'] if s else '', s['landing_area'] if s else '',
                      s['lead_dept'] if s else ''))
        conn.execute("UPDATE matches SET status='已对接' WHERE id=?", (mid,))
    return {'ok': True}


@router.post('/match/recompute')
def match_recompute(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov/match', status_code=303)
    with db.get_db() as conn:
        stats = engine.recompute_all(conn)
    return templates.TemplateResponse(request, 'gov/_recompute_done.html', {'stats': stats})


# ---------- 项目跟踪 ----------

@router.get('/projects')
def projects(request: Request):
    user = _u(request)
    with db.get_db() as conn:
        rows = db.q(conn, '''SELECT p.*, e.name AS ent_name, s.name AS scen_name FROM projects p
            JOIN enterprises e ON e.id=p.enterprise_id
            LEFT JOIN scenarios s ON s.id=p.scenario_id
            ORDER BY p.updated_at DESC''')
        ents = db.q(conn, 'SELECT id, name FROM enterprises ORDER BY name')
    board = {st: [r for r in rows if r['status'] == st] for st in ('对接中', '推进中', '已落地', '搁置')}
    return templates.TemplateResponse(request, 'gov/projects.html', {'user': user, 'board': board, 'ents': ents})


@router.post('/projects/new')
def project_create(request: Request, enterprise_id: int = Form(...), title: str = Form(''),
                   planned_scene: str = Form(''), dock_dept: str = Form(''),
                   followers: str = Form(''), progress: str = Form('')):
    _u(request)
    with db.get_db() as conn:
        scenario_id = None
        if planned_scene:
            sc = db.q1(conn, 'SELECT id FROM scenarios WHERE name=? OR ? LIKE "%"||name||"%" LIMIT 1',
                       (planned_scene, planned_scene))
            scenario_id = sc['id'] if sc else None
        conn.execute('''INSERT INTO projects(enterprise_id, scenario_id, title, planned_scene,
                        dock_dept, followers, progress) VALUES(?,?,?,?,?,?,?)''',
                     (enterprise_id, scenario_id, title, planned_scene, dock_dept, followers, progress))
    return RedirectResponse('/gov/projects', status_code=303)


@router.get('/projects/{pid}')
def project_detail(request: Request, pid: int):
    user = _u(request)
    with db.get_db() as conn:
        p = db.q1(conn, '''SELECT p.*, e.name AS ent_name, s.name AS scen_name FROM projects p
            JOIN enterprises e ON e.id=p.enterprise_id
            LEFT JOIN scenarios s ON s.id=p.scenario_id WHERE p.id=?''', (pid,))
        if not p:
            return RedirectResponse('/gov/projects', status_code=303)
        logs = db.q(conn, 'SELECT * FROM progress_logs WHERE project_id=? ORDER BY id DESC', (pid,))
    return templates.TemplateResponse(request, 'gov/project_detail.html', {'user': user, 'p': p, 'logs': logs})


@router.post('/projects/{pid}/status')
def project_status(request: Request, pid: int, status: str = Form(...)):
    _u(request)
    if status in ('对接中', '推进中', '已落地', '搁置'):
        with db.get_db() as conn:
            conn.execute("UPDATE projects SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (status, pid))
    return RedirectResponse(f'/gov/projects/{pid}', status_code=303)


@router.post('/projects/{pid}/logs')
def project_add_log(request: Request, pid: int, note: str = Form(...)):
    user = _u(request)
    note = note.strip()
    if note:
        with db.get_db() as conn:
            conn.execute('INSERT INTO progress_logs(project_id, note, created_by) VALUES(?,?,?)',
                         (pid, note, user['display_name']))
            conn.execute("UPDATE projects SET progress=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (note.split('\n')[0][:120], pid))
    return RedirectResponse(f'/gov/projects/{pid}', status_code=303)


# ---------- 审核中心 ----------

@router.get('/submissions')
def submissions(request: Request, status: str = '待审核'):
    user = _u(request)
    with db.get_db() as conn:
        rows = db.q(conn, '''SELECT s.*, e.name AS ent_name FROM submissions s
            JOIN enterprises e ON e.id=s.enterprise_id
            WHERE s.status=? ORDER BY s.id DESC''', (status,))
    parsed = [(r, json.loads(r['payload'] or '{}')) for r in rows]
    return templates.TemplateResponse(request, 'gov/submissions.html', {'user': user, 'rows': parsed, 'status': status})


@router.post('/submissions/{sid}/review')
def submission_review(request: Request, sid: int, action: str = Form(...), note: str = Form('')):
    user = _u(request)
    status = '已通过' if action == 'approve' else '已驳回'
    with db.get_db() as conn:
        sub = db.q1(conn, 'SELECT * FROM submissions WHERE id=?', (sid,))
        if sub and action == 'approve' and sub['type'] == '资料修改':
            payload = json.loads(sub['payload'] or '{}')
            fields = {k: v for k, v in payload.items() if k in ENTERPRISE_FIELDS and v}
            if fields:
                sets = ', '.join(f'{k}=?' for k in fields)
                conn.execute(f"UPDATE enterprises SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                             (*fields.values(), sub['enterprise_id']))
                engine.refresh_entity(conn, 'enterprise', sub['enterprise_id'])
        conn.execute('''UPDATE submissions SET status=?, review_note=?, reviewed_by=?,
                        reviewed_at=datetime('now','localtime') WHERE id=?''',
                     (status, note, user['display_name'], sid))
    return RedirectResponse('/gov/submissions', status_code=303)


# ---------- 词库管理（admin） ----------

@router.get('/lexicon')
def lexicon_page(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    from matching import rules
    with db.get_db() as conn:
        rules.load_lexicon(conn)
        source = rules.lexicon_source(conn)
    lex = rules.get_lexicon()
    return templates.TemplateResponse(request, 'gov/lexicon.html', {
        'user': user, 'lex': lex, 'source': source,
        'aliases': rules.DOMAIN_ALIAS})


@router.post('/lexicon/add')
async def lexicon_add(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    from matching import rules
    form = await request.form()
    domain = (form.get('domain') or '').strip()
    term = (form.get('term') or '').strip()
    new_domain = (form.get('new_domain') or '').strip()
    if new_domain:
        domain = new_domain
    if domain and term:
        with db.get_db() as conn:
            # 首次自定义时先把内置默认灌入，再追加（保证“自定义=默认+改动”的直觉）
            n = db.q1(conn, 'SELECT COUNT(*) c FROM lexicon_terms')['c']
            if n == 0:
                for d, ts in rules.DOMAIN_LEXICON.items():
                    conn.executemany('INSERT OR IGNORE INTO lexicon_terms(domain, term) VALUES(?,?)',
                                     [(d, t) for t in ts])
            conn.execute('INSERT OR IGNORE INTO lexicon_terms(domain, term) VALUES(?,?)', (domain, term))
            rules.load_lexicon(conn)
    return RedirectResponse('/gov/lexicon', status_code=303)


@router.post('/lexicon/delete')
async def lexicon_delete(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    from matching import rules
    form = await request.form()
    domain = (form.get('domain') or '').strip()
    term = (form.get('term') or '').strip()
    with db.get_db() as conn:
        conn.execute('DELETE FROM lexicon_terms WHERE domain=? AND term=?', (domain, term))
        rules.load_lexicon(conn)
    return RedirectResponse('/gov/lexicon', status_code=303)


@router.post('/lexicon/reset')
def lexicon_reset(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    from matching import rules
    with db.get_db() as conn:
        conn.execute('DELETE FROM lexicon_terms')
        rules.load_lexicon(conn)
    return RedirectResponse('/gov/lexicon', status_code=303)


# ---------- 数据管理与用户管理（admin） ----------

@router.get('/import')
def import_page(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    report = None
    rp = config.DATA_DIR / 'last_import.json'
    if rp.exists():
        report = json.loads(rp.read_text(encoding='utf-8'))
    found = excel_import.discover_files()
    files = {k: (p.name if p else None) for k, p in found.items()}
    return templates.TemplateResponse(request, 'gov/import.html', {'user': user, 'report': report,
        'files': files, 'labels': excel_import.FILE_LABELS,
        'headers': excel_import.EXPECTED_HEADERS})


@router.post('/import')
def import_run(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    report = excel_import.run_import()
    with db.get_db() as conn:
        engine.recompute_all(conn)
    found = excel_import.discover_files()
    files = {k: (p.name if p else None) for k, p in found.items()}
    return templates.TemplateResponse(request, 'gov/import.html', {'user': user, 'report': report,
        'files': files, 'labels': excel_import.FILE_LABELS,
        'headers': excel_import.EXPECTED_HEADERS, 'done': True})


@router.get('/users')
def users(request: Request):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    with db.get_db() as conn:
        rows = db.q(conn, '''SELECT u.*, e.name AS ent_name FROM users u
            LEFT JOIN enterprises e ON e.id=u.enterprise_id ORDER BY u.id''')
        ents = db.q(conn, 'SELECT id, name FROM enterprises ORDER BY name')
    return templates.TemplateResponse(request, 'gov/users.html', {'user': user, 'rows': rows, 'ents': ents})


@router.post('/users/new')
def user_create(request: Request, username: str = Form(...), password: str = Form(...),
                display_name: str = Form(''), role: str = Form('gov'),
                enterprise_id: int = Form(0)):
    user = _u(request)
    if user['role'] != 'admin':
        return RedirectResponse('/gov', status_code=303)
    if role not in ('admin', 'gov', 'enterprise') or not username.strip() or len(password) < 6:
        return RedirectResponse('/gov/users', status_code=303)
    with db.get_db() as conn:
        try:
            conn.execute('INSERT INTO users(username, password_hash, display_name, role, enterprise_id) VALUES(?,?,?,?,?)',
                         (username.strip(), auth.hash_password(password), display_name.strip(),
                          role, enterprise_id or None))
        except Exception:
            pass  # 用户名重复等，静默忽略
    return RedirectResponse('/gov/users', status_code=303)


@router.post('/users/{uid}/toggle')
def user_toggle(request: Request, uid: int):
    user = _u(request)
    if user['role'] != 'admin' or uid == user['id']:
        return RedirectResponse('/gov/users', status_code=303)
    with db.get_db() as conn:
        conn.execute('UPDATE users SET active=1-active WHERE id=?', (uid,))
    return RedirectResponse('/gov/users', status_code=303)


@router.post('/users/{uid}/reset')
def user_reset(request: Request, uid: int, password: str = Form(...)):
    user = _u(request)
    if user['role'] != 'admin' or len(password) < 6:
        return RedirectResponse('/gov/users', status_code=303)
    with db.get_db() as conn:
        conn.execute('UPDATE users SET password_hash=? WHERE id=?',
                     (auth.hash_password(password), uid))
    return RedirectResponse('/gov/users', status_code=303)


@router.post('/users/{uid}/delete')
def user_delete(request: Request, uid: int):
    user = _u(request)
    if user['role'] != 'admin' or uid == user['id']:
        return RedirectResponse('/gov/users', status_code=303)
    with db.get_db() as conn:
        conn.execute('DELETE FROM users WHERE id=?', (uid,))
    return RedirectResponse('/gov/users', status_code=303)
