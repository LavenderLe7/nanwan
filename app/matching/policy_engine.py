"""政策轨匹配引擎：条款逐条判定，不依赖 BGE 或场景轨。

核心逻辑：
- 每条条款独立判定：满足 / 不满足 / 数据不足
- 任一条款明确不满足 → 企业从本条政策候选列表中排除
- 数据不足的条款不导致排除，在匹配结果中说明缺少哪些数据
- 全部条款不可判定 → 不列入候选
- 不设权重、不设得分，按已确认满足的条款数降序排列
"""
import re

import db

# ===== 数值提取工具 =====

def _extract_threshold(content: str):
    """从条款内容中提取比较方向和阈值。"""
    m = re.search(r'注册资本\s*[≥>=]+\s*([\d.]+)\s*万', content)
    if m:
        return ('registered_capital', '>=', float(m.group(1)),
                '注册资本≥%s万元' % m.group(1))
    m = re.search(r'员工人数\s*[≥>=]+\s*([\d]+)\s*人', content)
    if m:
        return ('employee_count', '>=', int(m.group(1)),
                '员工人数≥%s人' % m.group(1))
    return (None, None, None, content)


# ===== 条款判定函数 =====
# 签名: (enterprise: sqlite3.Row, target: str) -> str
# 返回值以 满足 / 不满足 / 数据不足 开头

def _judge_qualification(ent, target: str):
    """资质类：在企业 qualifications 文本中搜索条款关键词。

    不追求精确匹配——去掉前缀、括号、引号后，取核心词，在资质文本中检查。
    同时生成多个变体（去级别前缀、去"企业"尾缀、去括号内容）依次尝试，
    任一命中即通过。
    """
    quals = (ent['qualifications'] or '')
    if not quals.strip():
        return '数据不足：企业资质信息为空，无法判定'

    keyword = target.strip()
    # 去掉前缀
    for prefix in ['获评', '属于', '须为', '已获评', '获']:
        if keyword.startswith(prefix):
            keyword = keyword[len(prefix):]
    # 去掉中文/英文引号
    keyword = keyword.strip('"').strip('"').strip()

    # 构建候选匹配词列表
    candidates = [keyword]

    # 去掉括号内容，如 "（证书有效期内）" → 纯核心词
    no_paren = re.sub(r'[（(][^）)]*[）)]', '', keyword).strip()
    if no_paren and no_paren != keyword:
        candidates.append(no_paren)

    # 去级别前缀 "国家级/省级/市级/区级"
    for lvl in ['国家级', '省级', '市级', '区级']:
        if keyword.startswith(lvl):
            candidates.append(keyword[len(lvl):])

    # 去尾缀 "企业"
    if keyword.endswith('企业') and len(keyword) > 3:
        candidates.append(keyword[:-2])

    # 取后半段（如"专精特新小巨人企业" → 也试"小巨人企业"和"小巨人"）
    # 在常见中间分隔点切开：特新/科技/制造/工业 等
    for sep in ['特新', '科技', '制造', '工业', '优势']:
        idx = keyword.find(sep)
        if idx > 0:
            tail = keyword[idx + len(sep):]
            if tail:
                candidates.append(tail)
            break

    # 依次尝试（去重保序）
    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if cand in quals:
            return '满足：企业资质信息含"%s"' % cand

    return '不满足：企业资质信息中未找到与"%s"匹配的资质' % candidates[0]


def _judge_industry(ent, target: str):
    """行业类：企业 category_bucket 是否命中条款中的行业关键词。"""
    bucket = (ent['category_bucket'] or '').split('/')
    if not bucket or bucket == ['']:
        return '数据不足：企业行业分类为空，无法判定'

    industries = []
    for kw in ['制造业', '服务业', '工业', '战略性新兴产业', '生物医药', '集成电路',
               '人工智能', '无人机', '节能环保', '通信技术', '芯片设计', '工程服务',
               '数字创意', '智能制造', '新能源', '新材料', '信息技术']:
        if kw in target:
            industries.append(kw)

    if not industries:
        return '数据不足：条款中未提取到明确的行业关键词'

    matched = [ind for ind in industries if any(ind in b for b in bucket)]
    if matched:
        return '满足：企业行业属"%s"，符合条款限定' % '、'.join(matched)
    else:
        return '不满足：企业行业为"%s"，不满足条款行业限定' % (ent['category_bucket'] or '')


def _judge_scale(ent, target: str):
    """规模类：数值比较（注册资本 / 员工人数）。"""
    field, op, threshold, display = _extract_threshold(target)
    if field is None:
        return '数据不足：无法从条款"%s"中提取数值判定条件' % target

    value = ent[field]
    if value is None:
        field_name = '注册资本' if field == 'registered_capital' else '员工人数'
        return '数据不足：企业缺少%s数据，无法判定"%s"' % (field_name, display)

    if op == '>=' and value >= threshold:
        return '满足：企业%s（当前%s）' % (display, value)
    elif op == '>=' and value < threshold:
        return '不满足：企业%s（当前%s）' % (display, value)
    else:
        return '满足：企业%s（当前%s）' % (display, value)


def _judge_region(ent, target: str):
    """地域类：所有企业均属南湾街道辖区，默认通过。"""
    return '满足：企业属于南湾街道辖区，默认满足地域要求'


def _judge_credit(ent, target: str):
    """信用类：检查企业是否在经营异常名录中。"""
    anomaly = ent['biz_anomaly']
    if anomaly is None:
        return '数据不足：企业缺少经营异常数据，无法判定'
    if '未见异常' in str(anomaly) or '无' in str(anomaly):
        return '满足：企业经营异常记录为空，信用良好'
    else:
        return '不满足：企业存在经营异常记录（%s）' % anomaly


CLAUSE_JUDGES = {
    '资质': _judge_qualification,
    '行业': _judge_industry,
    '规模': _judge_scale,
    '地域': _judge_region,
    '信用': _judge_credit,
}


# ===== 核心匹配 =====

def match_policy_to_enterprise(conn, policy_id: int, enterprise_id: int) -> tuple:
    """单条政策+单个企业的条款逐条判定。

    Returns: (candidate: bool, reason: str, satisfied: int, judgeable: int)
    """
    clauses = db.q(conn,
        'SELECT * FROM policy_clauses WHERE policy_id=? ORDER BY sort_order, id',
        (policy_id,))
    if not clauses:
        return (False, '该政策暂无申报条款', 0, 0)

    ent = db.q1(conn, 'SELECT * FROM enterprises WHERE id=?', (enterprise_id,))
    if not ent:
        return (False, '企业不存在', 0, 0)

    results = []
    satisfied = 0
    judgeable = 0

    for cl in clauses:
        ct = cl['clause_type']
        judge_fn = CLAUSE_JUDGES.get(ct)
        if judge_fn is None:
            results.append('未知条款类型"%s"：%s' % (ct, cl['content']))
            continue

        verdict = judge_fn(ent, cl['content'])
        results.append(verdict)

        if verdict.startswith('满足'):
            satisfied += 1
            judgeable += 1
        elif verdict.startswith('不满足'):
            judgeable += 1

    # 全部不可判定 → 不列入候选
    if judgeable == 0:
        return (False, '\n'.join(results), satisfied, judgeable)

    # 有明确不满足 → 排除
    for r in results:
        if r.startswith('不满足'):
            return (False, '\n'.join(results), satisfied, judgeable)

    return (True, '\n'.join(results), satisfied, judgeable)


def recompute_policy_matches(conn, policy_id: int) -> int:
    """重算单条政策全部企业匹配，写入 policy_matches。

    仅删除 status='候选' 行，已对接/已排除的人工标记保留。
    """
    enterprises = db.q(conn, 'SELECT id FROM enterprises')

    conn.execute("DELETE FROM policy_matches WHERE policy_id=? AND status='候选'",
                 (policy_id,))

    results = []
    for e in enterprises:
        candidate, reason, sat, _ = match_policy_to_enterprise(
            conn, policy_id, e['id'])
        if candidate:
            results.append((e['id'], reason, sat))

    results.sort(key=lambda x: x[2], reverse=True)

    n = 0
    for eid, reason, _ in results:
        conn.execute(
            '''INSERT INTO policy_matches(policy_id, enterprise_id, reason)
               VALUES(?, ?, ?)
               ON CONFLICT(policy_id, enterprise_id) DO UPDATE SET
               reason=excluded.reason, updated_at=datetime('now','localtime')''',
            (policy_id, eid, reason),
        )
        n += 1
    return n


def recompute_all_policies(conn) -> dict:
    """重算所有已发布政策的匹配结果。"""
    policies = db.q(conn, "SELECT id, name FROM policies WHERE status='已发布'")
    total = 0
    for p in policies:
        n = recompute_policy_matches(conn, p['id'])
        total += n
    return {'policies': len(policies), 'matches': total}
