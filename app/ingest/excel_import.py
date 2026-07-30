"""7 张源 Excel → SQLite 导入器。

导入策略：按自然键 upsert（企业=name_norm，场景=name+source，项目=企业+标题前30字），
重导不产生重复行，也不覆盖系统内人工维护的 status 字段。
文件按序号前缀发现（多版本取文件名日期最新者）；打开时校验表头，
版型不符则拒绝导入该文件并在报告中说明——绝不默默导错数据。
文件1 历史上是 WPS 伪 .xlsx（OLE2），读取按魔数自动识别 xlrd/openpyxl。
导入报告写入 data/last_import.json 供“数据管理”页展示。
"""
import json
import re

import openpyxl
import xlrd

import config
import db
from ingest.normalize import (clean_display_name, clean_multiline, clean_text,
                              merge_quals, merge_segments, norm_name, split_category)

# 文件发现前缀（序号+空格）与期望表头（版型约定，CLAUDE.md 有案）
FILE_PREFIXES = {
    'responsibility': '1 ',
    'capability': '2 ',
    'scenarios25': '3 ',
    'reserve': '4 ',
    'profiles': '5 ',
    'biz_info': '6 ',
    'policies': '7 ',
}
EXPECTED_HEADERS = {
    'responsibility': ['序号', '公司名称', '企业与产品简介', '场景能力', '类别',
                       '场景项目介绍', '街道计划落地应用场景', '建议对接部门', '推进情况', '场景全周期落地跟进人'],
    'capability': ['序号', '公司名称', '企业与产品简介', '场景能力', '可应用落地场景', '类别', '企业资质'],
    'scenarios25': ['序号', '应用领域', '应用场景名称', '场景简介', '拟落地应用区域', '牵头部门'],
    'reserve': ['序号', '应用领域', '场景名称', '场景简介', '主要技术', '参考案例', '潜在企业及产品'],
    'profiles': ['企业名称', '核心定位', '主营业务', '核心产品', '核心技术', '资质与荣誉', '典型客户/案例'],
    'biz_info': ['企业名称', '注册资本（万元）', '员工人数', '近一年营收（万元）', '经营异常'],
    'policies': ['序号', '政策名称', '级别', '类别', '扶持方式', '扶持金额', '申报截止日期', '条款类型', '条款内容', '来源链接'],
}
FILE_LABELS = {
    'responsibility': '文件1 责任清单', 'capability': '文件2 能力清单',
    'scenarios25': '文件3 南湾25场景', 'reserve': '文件4 储备库', 'profiles': '文件5 深度画像',
    'biz_info': '文件6 企业工商信息',
    'policies': '文件7 惠企政策种子数据',
}


class ImportFormatError(Exception):
    pass


def discover_files() -> dict:
    """按前缀发现源文件，返回 {key: Path|None}（多版本取最新）。"""
    found = {}
    for key, prefix in FILE_PREFIXES.items():
        matches = sorted(config.EXCEL_DIR.glob(f'{prefix}*.xlsx'))
        found[key] = matches[-1] if matches else None
    return found


def _norm_header(v) -> str:
    return re.sub(r'\s+', '', str(v or ''))


def _is_ole2(path) -> bool:
    """WPS 老格式（OLE2）魔数 D0CF11E0；真 xlsx 是 ZIP。"""
    with open(path, 'rb') as f:
        return f.read(4) == b'\xd0\xcf\x11\xe0'


def _read_rows(path, key):
    """统一读取：自动识别 OLE2/xlsx，校验表头，返回数据行列表。

    文件1 版型：第0行合并标题、第1行表头；其余文件表头在第0行。
    """
    if _is_ole2(path):
        book = xlrd.open_workbook(str(path))
        sh = book.sheet_by_index(0)
        header = [sh.cell_value(1, c) for c in range(sh.ncols)]
        rows = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(2, sh.nrows)]
    else:
        wb = openpyxl.load_workbook(path, read_only=True)
        all_rows = list(wb.worksheets[0].iter_rows(values_only=True))
        wb.close()
        header = list(all_rows[0]) if all_rows else []
        rows = [list(r) for r in all_rows[1:]]

    expected = EXPECTED_HEADERS[key]
    actual = [_norm_header(h) for h in header[:len(expected)]]
    if actual != [_norm_header(h) for h in expected]:
        raise ImportFormatError(
            f'{path.name} 表头与约定不符（期望：{"|".join(expected[:4])}…，'
            f'实际：{"|".join(str(h) for h in header[:4])}…）。'
            '请沿用原模板列结构更新数据，或由开发人员调整导入器。')
    return rows


# ---------- 企业 ----------

def _upsert_enterprise(conn, e):
    """e: dict，按 name_norm upsert；只更新非空字段，不触碰系统字段。
    name（展示名）先到先得：文件2 是主表，其写法最规范，后续文件不覆盖。"""
    existing = db.q1(conn, 'SELECT id FROM enterprises WHERE name_norm=?', (e['name_norm'],))
    fields = [k for k in e if k not in ('name', 'name_norm') and e[k]]
    if existing:
        if fields:
            sets = ', '.join(f'{k}=?' for k in fields)
            conn.execute(
                f"UPDATE enterprises SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                (*[e[k] for k in fields], existing['id']),
            )
        return existing['id'], False
    cur = conn.execute(
        f"INSERT INTO enterprises(name, name_norm, {', '.join(k for k in fields)}) VALUES(?, ?, {', '.join('?' * len(fields))})"
        if fields else 'INSERT INTO enterprises(name, name_norm) VALUES(?, ?)',
        (e['name'], e['name_norm'], *[e[k] for k in fields]),
    )
    return cur.lastrowid, True


def import_capability(conn, report, path):
    """文件2：场景能力清单（企业主表）。

    同一家企业可能按业务线登记多行（类别/能力不同）：先按归一化名分组做字段级合并
    （简介取最长、能力/适用场景/资质切段去重拼接、类别串去重并列），再 upsert，
    避免后行吞并前行数据。
    """
    groups = {}
    for r in _read_rows(path, 'capability'):
        if not r or not r[1]:
            continue
        nn = norm_name(r[1])
        if not nn:
            continue
        groups.setdefault(nn, []).append(r)

    n_new = n_upd = 0
    for nn, rs in groups.items():
        buckets_raw = [split_category(r[5]) for r in rs]
        bucket = next((b for b, _ in buckets_raw if b), '')
        raw_cat = '；'.join(dict.fromkeys(raw for _, raw in buckets_raw if raw))
        intro = max((clean_multiline(r[2]) for r in rs), key=len, default='')
        e = {
            'name': clean_display_name(rs[0][1]), 'name_norm': nn,
            'intro': intro,
            'capability': merge_segments(*[r[3] for r in rs]),
            'applicable_scenes': merge_segments(*[r[4] for r in rs]),
            'category_bucket': bucket, 'category_raw': raw_cat,
            'qualifications': merge_quals(*[r[6] for r in rs]),
        }
        _, is_new = _upsert_enterprise(conn, e)
        n_new, n_upd = n_new + is_new, n_upd + (not is_new)
    report['capability'] = {'rows': n_new + n_upd, 'new': n_new, 'updated': n_upd,
                            'merged_dupes': sum(len(rs) - 1 for rs in groups.values())}


def import_profiles(conn, report, path):
    """文件5：深度画像（合并进企业档；文件2 没有的企业也建档）。"""
    n_new = n_upd = 0
    for r in _read_rows(path, 'profiles'):
        if not r or not r[0]:
            continue
        nn = norm_name(r[0])
        if not nn:
            continue
        old = db.q1(conn, 'SELECT qualifications FROM enterprises WHERE name_norm=?', (nn,))
        e = {
            'name': clean_display_name(r[0]), 'name_norm': nn,
            'positioning': clean_text(r[1]), 'main_business': clean_multiline(r[2]),
            'core_products': clean_multiline(r[3]), 'core_tech': clean_multiline(r[4]),
            'qualifications': merge_quals(old['qualifications'] if old else '', clean_text(r[5])),
            'clients_cases': clean_multiline(r[6]),
        }
        _, is_new = _upsert_enterprise(conn, e)
        n_new, n_upd = n_new + is_new, n_upd + (not is_new)
    report['profiles'] = {'rows': n_new + n_upd, 'new': n_new, 'updated': n_upd}


# ---------- 场景 ----------

def _upsert_scenario(conn, s):
    existing = db.q1(conn, 'SELECT id FROM scenarios WHERE name=? AND source=?', (s['name'], s['source']))
    fields = [k for k in s if k not in ('name', 'source') and s[k]]
    if existing:
        if fields:
            sets = ', '.join(f'{k}=?' for k in fields)
            conn.execute(
                f"UPDATE scenarios SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
                (*[s[k] for k in fields], existing['id']),
            )
        return existing['id'], False
    cur = conn.execute(
        f"INSERT INTO scenarios(name, source{', ' if fields else ''}{', '.join(fields)}) VALUES(?, ?{', ' if fields else ''}{', '.join('?' * len(fields))})",
        (s['name'], s['source'], *[s[k] for k in fields]),
    )
    return cur.lastrowid, True


def import_scenarios25(conn, report, path):
    """文件3：南湾25场景。"""
    n = 0
    for r in _read_rows(path, 'scenarios25'):
        if not r or not r[2]:
            continue
        _upsert_scenario(conn, {
            'name': clean_text(r[2]), 'domain': clean_text(r[1]),
            'intro': clean_multiline(r[3]), 'landing_area': clean_text(r[4]),
            'lead_dept': clean_text(r[5]), 'source': '南湾25',
        })
        n += 1
    report['scenarios25'] = {'rows': n}


def import_reserve(conn, report, path):
    """文件4：通用场景储备库。"""
    n = 0
    for r in _read_rows(path, 'reserve'):
        if not r or not r[2]:
            continue
        _upsert_scenario(conn, {
            'name': clean_text(r[2]), 'domain': clean_text(r[1]),
            'intro': clean_multiline(r[3]), 'main_tech': clean_text(r[4]),
            'ref_case': clean_multiline(r[5]), 'potential_enterprises': clean_multiline(r[6]),
            'source': '储备库',
        })
        n += 1
    report['reserve'] = {'rows': n}


def link_duplicate_scenarios(conn, report):
    """文件3/4 重名场景互链（同名不同源）。"""
    linked = 0
    pairs = db.q(conn, '''
        SELECT a.id AS id25, b.id AS idr FROM scenarios a
        JOIN scenarios b ON a.name = b.name AND a.source='南湾25' AND b.source='储备库'
    ''')
    for p in pairs:
        conn.execute('UPDATE scenarios SET linked_scenario_id=? WHERE id=?', (p['idr'], p['id25']))
        conn.execute('UPDATE scenarios SET linked_scenario_id=? WHERE id=?', (p['id25'], p['idr']))
        linked += 1
    report['linked_scenarios'] = linked


# ---------- 项目（文件1 责任清单） ----------

def import_responsibility(conn, report, path):
    """文件1：责任清单 → projects；企业不在库中的顺带建档（文件1 自带简介/能力/类别）。

    注意：一企多项目时公司名只在首行填写（视觉上纵向合并），延续行需沿用上一行公司名。
    """
    n_proj = n_ent = n_unmatched_scene = 0
    last_name_raw = ''
    for r in _read_rows(path, 'responsibility'):
        if len(r) < 2:
            continue
        name_raw = r[1]
        if str(name_raw or '').strip():
            last_name_raw = name_raw
        else:
            name_raw = last_name_raw  # 延续行：沿用上一行公司名
        nn = norm_name(name_raw)
        if not nn:
            continue
        bucket, raw = split_category(r[4] if len(r) > 4 else '')
        ent_id, is_new = _upsert_enterprise(conn, {
            'name': clean_display_name(name_raw), 'name_norm': nn,
            'intro': clean_multiline(r[2]), 'capability': clean_multiline(r[3]),
            'category_bucket': bucket, 'category_raw': raw,
        })
        n_ent += is_new

        title = clean_multiline(r[5] if len(r) > 5 else '')
        planned = clean_text(r[6] if len(r) > 6 else '')
        # planned_scene 尝试关联场景库：场景名是其子串即认为对应
        scenario_id = None
        if planned:
            for sc in db.q(conn, 'SELECT id, name FROM scenarios'):
                if sc['name'] and (sc['name'] in planned or planned in sc['name']):
                    scenario_id = sc['id']
                    break
            if scenario_id is None:
                n_unmatched_scene += 1

        key = title[:30]
        existing = db.q1(
            conn, 'SELECT id FROM projects WHERE enterprise_id=? AND substr(COALESCE(title,\'\'),1,30)=?',
            (ent_id, key),
        )
        vals = (title, planned, clean_text(r[7] if len(r) > 7 else ''),
                clean_multiline(r[8] if len(r) > 8 else ''), clean_text(r[9] if len(r) > 9 else ''),
                scenario_id)
        if existing:
            conn.execute('''UPDATE projects SET title=?, planned_scene=?, dock_dept=?,
                            progress=COALESCE(NULLIF(?, ''), progress), followers=?,
                            scenario_id=COALESCE(?, scenario_id),
                            updated_at=datetime('now','localtime') WHERE id=?''',
                         (*vals, existing['id']))
        else:
            conn.execute('''INSERT INTO projects(enterprise_id, title, planned_scene, dock_dept,
                            progress, followers, scenario_id) VALUES(?,?,?,?,?,?,?)''',
                         (ent_id, *vals))
            n_proj += 1
    report['responsibility'] = {
        'projects_new': n_proj, 'enterprises_created': n_ent,
        'planned_scene_unmatched': n_unmatched_scene,
    }


# ---------- 企业工商信息（文件6） ----------

def import_biz_info(conn, report, path):
    """文件6：企业基础工商信息（注册资本/员工人数/经营异常）→ upsert 到 enterprises 表。"""
    n = 0
    for r in _read_rows(path, 'biz_info'):
        if not r or not r[0]:
            continue
        nn = norm_name(r[0])
        if not nn:
            continue
        existing = db.q1(conn, 'SELECT id FROM enterprises WHERE name_norm=?', (nn,))
        if not existing:
            continue
        cap = r[1] if isinstance(r[1], (int, float)) and r[1] != '' else None
        emp = r[2] if isinstance(r[2], (int, float)) and r[2] != '' else None
        anomaly = str(r[4]).strip() if r[4] and str(r[4]).strip() != '' else '未见异常'
        conn.execute(
            "UPDATE enterprises SET registered_capital=?, employee_count=?, biz_anomaly=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (cap, emp, anomaly, existing['id']),
        )
        n += 1
    report['biz_info'] = {'rows': n}


def import_policies(conn, report, path):
    """文件7：惠企政策种子数据 → policies + policy_clauses。按政策名称 upsert。"""
    rows = _read_rows(path, 'policies')
    policy_list = []
    current = None
    for r in rows:
        if not r or all(v is None for v in r):
            continue
        seq = r[0]
        # 有序号 → 新政策
        if seq is not None:
            if current is not None:
                policy_list.append(current)
            current = {
                'name': (r[1] or '').strip(),
                'level': (r[2] or '').strip(),
                'category': (r[3] or '').strip(),
                'support_type': (r[4] or '').strip(),
                'amount_text': (r[5] or '').strip(),
                'deadline': (r[6] or '').strip(),
                'source_url': (r[9] or '').strip(),
                'clauses': [],
            }
        # 无序号但 current 存在 → 该行的条款数据
        clause_type = (r[7] or '').strip()
        clause_content = (r[8] or '').strip()
        if current is not None and clause_type and clause_content:
            current['clauses'].append((clause_type, clause_content))
    if current is not None:
        policy_list.append(current)

    n = 0
    for p in policy_list:
        if not p['name']:
            continue
        existing = db.q1(conn, 'SELECT id FROM policies WHERE name=?', (p['name'],))
        if existing:
            pid = existing['id']
            conn.execute(
                "UPDATE policies SET level=?, category=?, support_type=?, amount_text=?, "
                "deadline=?, source_url=?, updated_at=datetime('now','localtime') WHERE id=?",
                (p['level'], p['category'], p['support_type'], p['amount_text'],
                 p['deadline'], p['source_url'], pid),
            )
        else:
            cur = conn.execute(
                "INSERT INTO policies(name, level, category, support_type, amount_text, "
                "deadline, source_url, status) VALUES(?,?,?,?,?,?,?,'已发布')",
                (p['name'], p['level'], p['category'], p['support_type'],
                 p['amount_text'], p['deadline'], p['source_url']),
            )
            pid = cur.lastrowid
        # 条款：先删后插（旧条款覆盖）
        conn.execute('DELETE FROM policy_clauses WHERE policy_id=?', (pid,))
        for ci, (ct, cc) in enumerate(p['clauses']):
            conn.execute(
                'INSERT INTO policy_clauses(policy_id, clause_type, content, sort_order) '
                'VALUES(?,?,?,?)', (pid, ct, cc, ci),
            )
        n += 1
    report['policies'] = {'rows': n, 'clauses': sum(len(p['clauses']) for p in policy_list)}


# ---------- 入口 ----------

_IMPORTERS = [
    ('capability', import_capability),
    ('profiles', import_profiles),
    ('scenarios25', import_scenarios25),
    ('reserve', import_reserve),
    ('responsibility', import_responsibility),
    ('biz_info', import_biz_info),
    ('policies', import_policies),
]


def run_import():
    """全量导入，返回报告 dict（同时落盘 data/last_import.json）。

    单文件失败（缺失/版型不符）不影响其余文件导入，错误体现在报告中。
    """
    report = {}
    paths = discover_files()
    report['files'] = {k: (p.name if p else None) for k, p in paths.items()}
    with db.get_db() as conn:
        for key, func in _IMPORTERS:
            path = paths[key]
            if not path:
                report[key] = {'error': f'未找到源文件（前缀「{FILE_PREFIXES[key]}*.xlsx」）'}
                continue
            try:
                func(conn, report, path)
            except ImportFormatError as e:
                report[key] = {'error': str(e)}
        if not any('error' in report.get(k, {}) for k in ('scenarios25', 'reserve')):
            link_duplicate_scenarios(conn, report)
        else:
            report['linked_scenarios'] = '跳过（场景文件有错误）'
        # 汇总对账
        report['totals'] = {
            'enterprises': db.q1(conn, 'SELECT COUNT(*) c FROM enterprises')['c'],
            'scenarios_25': db.q1(conn, "SELECT COUNT(*) c FROM scenarios WHERE source='南湾25'")['c'],
            'scenarios_reserve': db.q1(conn, "SELECT COUNT(*) c FROM scenarios WHERE source='储备库'")['c'],
            'projects': db.q1(conn, 'SELECT COUNT(*) c FROM projects')['c'],
            'enterprises_no_profile': db.q1(conn, 'SELECT COUNT(*) c FROM enterprises WHERE positioning IS NULL')['c'],
            'policies': db.q1(conn, 'SELECT COUNT(*) c FROM policies')['c'],
            'policy_clauses': db.q1(conn, 'SELECT COUNT(*) c FROM policy_clauses')['c'],
        }
    (config.DATA_DIR / 'last_import.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    db.init_db()
    print(json.dumps(run_import(), ensure_ascii=False, indent=2))
