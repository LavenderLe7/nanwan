"""外迁风险识别模型：三特征打分（预警类型 × 租赁面积占比 × 行业系数）。

权重从龙岗区 605 条标注数据反向推导（高=2, 中=1, 低=0 加权平均）。
"""
import re

import db

# ===== 特征 1：预警类型基础权重 =====

BASE_WEIGHTS = {
    '限制高消费': 10,
    '异地购地': 10,
    '失信执行': 10,
    '区内租赁临期': 9,
    '舆情动态': 5.5,
    '经营异常': 5,
    '行政处罚': 2.6,
    '异地分支': 2.6,
    '异地投资': 2.6,
    '公开市场融资': 2.6,
}

# ===== 特征 2：租赁面积占比（区内租赁临期专用） =====

def _extract_lease_ratio(warning_info):
    """从预警信息中提取租赁面积占比，如 '占其在龙岗总租赁面积的100.00%' → 100.0。"""
    if not warning_info:
        return None
    m = re.search(r'占其在龙岗总租赁面积的(\d+\.?\d*)%', warning_info)
    return float(m.group(1)) if m else None


LEASE_BONUS = {
    'high': 1.5,   # ≥80% → +1.5
    'low': -1.5,   # <50% → -1.5
}

# ===== 特征 3：行业系数（舆情动态 + 区内租赁临期专用） =====

IND_MULT = {
    '制造业': 1.3,
    '居民服务、修理和其他服务业': 1.3,
    '建筑业': 1.2,
    '交通运输、仓储和邮政业': 1.1,
    '批发和零售业': 1.0,
    '科学研究和技术服务业': 0.8,
    '信息传输、软件和信息技术服务业': 0.7,
    '水利、环境和公共设施管理业': 0.7,
}

# 行业系数生效的预警类型
_IND_SENSITIVE_TYPES = ('舆情动态', '区内租赁临期')

# ===== 分级阈值 =====

def score_to_level(score):
    if score >= 10:
        return '挽留级'
    elif score >= 5:
        return '警示级'
    elif score >= 2.6:
        return '关注级'
    return '无风险'


# ===== 打分函数 =====

def compute_record_score(wtype, warning_info=None, industry=None):
    """单条预警记录 → 加权分数。"""
    base = BASE_WEIGHTS.get(wtype, 2.6)

    # 特征 2：租赁面积占比（仅区内租赁临期）
    if wtype == '区内租赁临期':
        ratio = _extract_lease_ratio(warning_info or '')
        if ratio is not None:
            if ratio >= 80:
                base += LEASE_BONUS['high']
            elif ratio < 50:
                base += LEASE_BONUS['low']

    # 特征 3：行业系数（仅舆情动态 + 区内租赁临期）
    if wtype in _IND_SENSITIVE_TYPES and industry:
        mult = IND_MULT.get(industry, 1.0)
        base *= mult

    return base


def compute_enterprise_risk(conn, enterprise_id):
    """企业所有预警汇总 → (总分, 等级)。无预警返回 (0, None)。"""
    rows = db.q(conn,
        'SELECT warning_type, warning_info, industry FROM relocation_warnings '
        'WHERE enterprise_id=?', (enterprise_id,))
    if not rows:
        return (0, None)

    total = sum(compute_record_score(r['warning_type'], r['warning_info'], r['industry'])
                for r in rows)
    return (total, score_to_level(total))


def compute_all_risk_scores(conn):
    """遍历所有有预警的企业，更新 enterprises.relocation_risk + 每条预警的 warning_score。"""
    # 先逐条更新预警记录的打分
    all_rows = db.q(conn,
        'SELECT id, warning_type, warning_info, industry FROM relocation_warnings')
    for r in all_rows:
        score = compute_record_score(r['warning_type'], r['warning_info'], r['industry'])
        conn.execute('UPDATE relocation_warnings SET warning_score=? WHERE id=?',
                     (round(score, 1), r['id']))
    # 再计算企业级风险等级
    eids = db.q(conn,
        'SELECT DISTINCT enterprise_id FROM relocation_warnings WHERE enterprise_id IS NOT NULL')
    for e in eids:
        total, level = compute_enterprise_risk(conn, e['enterprise_id'])
        conn.execute(
            "UPDATE enterprises SET relocation_risk=?, relocation_score=?, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (level, round(total, 1), e['enterprise_id']),
        )
    return len(eids)
