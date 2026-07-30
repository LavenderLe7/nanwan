"""规则匹配：企业类别桶 → 应用领域映射 + 领域词库命中。

规则分 = 0.5 × 类别映射 + 0.5 × 领域词命中（3 词饱和）。
词库按 19 个领域组织（DOMAIN_LEXICON），词条经语料循证策展：
  - 每个词须是"该领域的专属证据"（在企业文本中出现即指向本领域）；
  - 泛词（监测/治理/智能/自动化/传感器 等）不进入任何词单，
    跨领域相关性由类别映射与 BGE 语义路承担；
  - 领域边界允许模糊：场景可同时被文本打上多个领域标签（多标签设计）。
"""
import re

# 企业类别桶 → 场景应用领域（两套分类法的人工映射，来自对文件2类别与文件3领域的对照）
CATEGORY_DOMAIN_MAP = {
    '人工智能': ['人工智能', '数字政府', '智慧安防', '智慧园区', '智慧治理', '智慧商务'],
    '无人机': ['低空经济', '智慧应急', '智慧安防'],
    '节能环保': ['智慧水务', '智慧治理'],
    '通信技术': ['智慧园区', '智慧安防', '智慧交通', '数字政府', '智慧治理'],
    '制造业成品': ['智慧应急', '智慧文旅', '智慧养老', '智慧医疗'],
    '工业零部件': ['智慧园区', '人工智能'],
    '芯片设计': ['人工智能', '数字政府'],
    '数字创意': ['智慧文旅', '智慧教育', '智慧商务'],
    '工程服务': ['智慧水务', '智慧交通', '智慧园区'],
    '生物医药': ['智慧医疗', '智慧养老'],
    '其他': [],
}

# 领域词库（v2，2026-07 循证策展）：键 = 领域，值 = 该领域专属证据词
DOMAIN_LEXICON = {
    '智慧交通': ['交通', '违停', '车流', '停车', '信号灯', '斑马线', '拥堵',
                 '车路协同', '电子警察', '交通诱导', '公交'],
    '智慧安防': ['安防', '视频监控', '摄像', '人脸', '车牌', '门禁', '高空抛物',
                 '周界', '行为识别', '巡更', '安检'],
    '智慧应急': ['应急', '消防', '火灾', '烟感', '燃气', '安全生产', '隐患',
                 '救援', '防汛', '地质灾害', '一氧化碳'],
    '智慧水务': ['水务', '水质', '水位', '管网', '污水', '河道', '水库',
                 '排涝', '供水', '漏损', '直饮水', '排水'],
    '智慧养老': ['养老', '失能', '体征', '陪护', '助餐', '跌倒', '护理', '老人'],
    '智慧医疗': ['医疗', '问诊', '健康监测', '慢病', '辅助诊断', '体检', '医院', '医药'],
    '智慧教育': ['教育', '学生', '校园', '课堂', '作业', '批改', '虚拟仿真', '实验'],
    # 注：'作业'会把"施工作业/环卫作业"类场景误打上教育标签，但实测保留它召回更好——
    # 场景侧误打的标签只是多查几个极少命中的词，代价近似零；漏标才是真实损失。
    '智慧文旅': ['文旅', '夜游', '光影', '灯光', '景区', '文创', '全息', '投影'],
    '智慧商务': ['商圈', '消费', '电商', '供应链', '跨境', '品牌', '零售', '金融'],
    '智慧园区': ['园区', '楼宇', '招商', '物业', '孵化器', '能耗'],
    '智慧治理': ['网格', '基层治理', '社区治理', '一网统管', '事件分拨', '巡查',
                 '数字乡村', '乡村振兴'],
    '数字政府': ['政务', '一网通办', '数据要素', '区块链', '信用', '便民',
                 '自助', '民生', '群众'],
    '人工智能': ['AI', '大模型', '机器视觉', '图像识别', '语音识别', '深度学习',
                 '知识图谱', '智能体', '算法'],
    '低空经济': ['无人机', '低空', '起降', '反制', '系留', '飞手', '物流末端', '空域'],
    '智慧环保': ['环保', '环卫', '垃圾分类', '清扫', '扬尘', '噪声', '空气', '消杀'],
    '智慧能源': ['光伏', '储能', '充电桩', '电网', '能耗', '双碳', '光储', '节能', '碳排'],
    '机器人':   ['机器人', '具身智能', '机械臂', 'AGV', '分拣'],
    '芯片半导体': ['芯片', '半导体', '集成电路', 'MEMS', '封装'],
    '数字创意': ['AR', 'VR', '数字孪生', '全息', '互动投影', '裸眼3D', '元宇宙'],
}

# 文件4 细粒度领域标签 → 词库领域（文件3 标签与词库键一致，无需别名）
DOMAIN_ALIAS = {
    '人工智能/大模型': '人工智能', '人工智能/计算机视觉': '人工智能', '人工智能/语音识别': '人工智能',
    '具身智能/机器人': '机器人', '无人系统': '低空经济', '区块链/Web3': '数字政府',
    '数字孪生/元宇宙': '数字创意', '智慧产业': '智慧园区', '智慧农业/乡村振兴': '智慧治理',
    '智慧医疗/养老': '智慧养老', '智慧商圈/文旅': '智慧商务', '智慧垃圾分类': '智慧环保',
    '智慧政务': '数字政府', '智慧环保/环卫': '智慧环保', '智慧社区/基层治理': '智慧治理',
    '智慧能源/低碳': '智慧能源', '量子科技': '数字政府', '生物技术/合成生物': '智慧医疗',
    '生物技术/脑机接口': '人工智能',
}

# 命中 3 个领域词即满分（2 词会造成大量并列、Top1 反降，经标准答案评估确定）
DOMAIN_HIT_SATURATE = 3

# ---------- 词库装载：数据库优先，内置默认兜底 ----------
# 业务口在“词库管理”页在线增删词条（写入 lexicon_terms 表），无需改本文件、无需重启；
# 表为空时回落到上面的内置词库（即“恢复出厂默认”）。
_active_lexicon = None   # dict[str, list[str]] | None
_ascii_kw = {}


def _rebuild_ascii_guard(lexicon):
    """纯英文缩写词要求字母边界，避免 AI 命中 OPENAI 这类误配。"""
    global _ascii_kw
    terms = {t for ts in lexicon.values() for t in ts}
    _ascii_kw = {kw: re.compile(rf'(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])')
                 for kw in terms if kw.isascii()}


def load_lexicon(conn=None):
    """从数据库装载词库到内存缓存；空表则用内置默认。engine 重算与管理页保存后调用。"""
    global _active_lexicon
    lex = None
    if conn is not None:
        rows = conn.execute('SELECT domain, term FROM lexicon_terms').fetchall()
        if rows:
            lex = {}
            for r in rows:
                lex.setdefault(r['domain'], []).append(r['term'])
    if lex is None:
        lex = {d: list(ts) for d, ts in DOMAIN_LEXICON.items()}
    _active_lexicon = lex
    _rebuild_ascii_guard(lex)
    return lex


def get_lexicon() -> dict:
    if _active_lexicon is None:
        load_lexicon(None)
    return _active_lexicon


def lexicon_source(conn=None) -> str:
    """当前生效词库来源：数据库（自定义）/ 内置默认。"""
    if conn is not None:
        n = conn.execute('SELECT COUNT(*) c FROM lexicon_terms').fetchone()['c']
        return '数据库自定义' if n > 0 else '内置默认'
    return '数据库自定义' if _active_lexicon is not None and _active_lexicon != DOMAIN_LEXICON else '内置默认'


_rebuild_ascii_guard(DOMAIN_LEXICON)


def _kw_in(kw: str, text: str) -> bool:
    if kw in _ascii_kw:
        return bool(_ascii_kw[kw].search(text))
    return kw in text


def _text(*parts) -> str:
    return ' '.join(p for p in parts if p)


def _detect_domains(text: str) -> set:
    """从文本检测领域标签（当前仅用于场景侧；企业侧不预先打标，只按场景词单查词）。"""
    lex = get_lexicon()
    return {d for d, terms in lex.items() if any(_kw_in(t, text) for t in terms)}


def rule_score(enterprise: dict, scenario: dict) -> tuple[float, list[str]]:
    """返回 (0~1 规则分, 理由片段列表)。"""
    reasons = []

    # 1) 类别映射（权重 0.5）：企业类别桶 → 场景 domain 字段
    cat_hit = 0.0
    bucket = enterprise.get('category_bucket') or ''
    s_domain = scenario.get('domain') or ''
    if bucket and s_domain:
        hit_domains = [d for d in CATEGORY_DOMAIN_MAP.get(bucket, [])
                       if d in s_domain or s_domain in d]
        if hit_domains:
            cat_hit = 1.0
            reasons.append(f'类别映射：{bucket}→{hit_domains[0]}')

    # 2) 领域词命中（权重 0.5）：场景的领域标签 → 对应词单 → 企业文本查词
    scen_text = _text(scenario.get('name'), scenario.get('intro'),
                      scenario.get('domain'), scenario.get('main_tech'))
    ent_text = _text(enterprise.get('intro'), enterprise.get('capability'),
                     enterprise.get('core_products'), enterprise.get('core_tech'),
                     enterprise.get('applicable_scenes'), enterprise.get('main_business'))
    scen_domains = _detect_domains(scen_text)
    lex = get_lexicon()
    if s_domain in DOMAIN_ALIAS:
        scen_domains.add(DOMAIN_ALIAS[s_domain])
    elif s_domain in lex:
        scen_domains.add(s_domain)

    terms = set()
    for d in scen_domains:
        terms.update(lex.get(d, ()))
    hits = sorted(t for t in terms if _kw_in(t, ent_text))
    domain_score = min(1.0, len(hits) / DOMAIN_HIT_SATURATE)
    if hits:
        reasons.append('领域词：' + '、'.join(hits[:5]))

    score = 0.5 * cat_hit + 0.5 * domain_score
    return round(score, 4), reasons
