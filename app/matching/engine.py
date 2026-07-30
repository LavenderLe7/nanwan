"""匹配引擎：语义分 + 规则分融合，全量预计算写入 matches 表。

总分 = SEMANTIC_WEIGHT × 语义 + RULE_WEIGHT × 规则；语义不可用时总分 = 规则分。
保留每个场景 Top-K 且总分达阈值的结果；已人工标记（已对接/已排除）的行重算时保留标记。
"""
import numpy as np

import config
import db
from matching import embed, rules


def _row_to_dict(r) -> dict:
    return {k: r[k] for k in r.keys()}


def recompute_embeddings(conn):
    """为全部企业/场景重算向量（规模 ~220 条，CPU 秒级）。"""
    if not embed.available():
        return False
    ents = [_row_to_dict(r) for r in db.q(conn, 'SELECT * FROM enterprises')]
    scens = [_row_to_dict(r) for r in db.q(conn, 'SELECT * FROM scenarios')]
    if ents:
        vecs = embed.encode([embed.enterprise_text(e) for e in ents])
        for e, v in zip(ents, vecs):
            embed.save_vector(conn, 'enterprise', e['id'], v)
    if scens:
        vecs = embed.encode([embed.scenario_text(s) for s in scens], is_query=True)
        for s, v in zip(scens, vecs):
            embed.save_vector(conn, 'scenario', s['id'], v)
    return True


def recompute_all(conn=None) -> dict:
    """全量重算匹配结果，返回统计。可在请求内调用（耗时数秒）。"""
    own = conn is None
    if own:
        conn = db.connect()
    try:
        rules.load_lexicon(conn)  # 词库以数据库为准（管理页在线编辑），空表自动回退内置默认
        semantic_ok = recompute_embeddings(conn)
        ents = [_row_to_dict(r) for r in db.q(conn, 'SELECT * FROM enterprises')]
        scens = [_row_to_dict(r) for r in db.q(conn, 'SELECT * FROM scenarios')]

        ent_vecs = embed.load_vectors(conn, 'enterprise') if semantic_ok else {}
        scen_vecs = embed.load_vectors(conn, 'scenario') if semantic_ok else {}

        # 语义相似度矩阵（已归一化 → 点积即余弦）
        sim = None
        ent_pos = scen_pos = None
        if semantic_ok and ents and scens and ent_vecs and scen_vecs:
            e_list = [e for e in ents if e['id'] in ent_vecs]
            s_list = [s for s in scens if s['id'] in scen_vecs]
            em = np.stack([ent_vecs[e['id']] for e in e_list])
            sm = np.stack([scen_vecs[s['id']] for s in s_list])
            sim = sm @ em.T  # [n_scen, n_ent]
            ent_pos = {e['id']: i for i, e in enumerate(e_list)}
            scen_pos = {s['id']: i for i, s in enumerate(s_list)}

        # 保留人工标记，清掉未标记的旧结果
        conn.execute("DELETE FROM matches WHERE status='候选'")

        n_written = 0
        w_sem = config.SEMANTIC_WEIGHT if semantic_ok else 0.0
        w_rule = 1.0 - w_sem
        for si, s in enumerate(scens):
            scored = []
            for ei, e in enumerate(ents):
                r_score, reasons = rules.rule_score(e, s)
                sem = None
                if sim is not None and s['id'] in scen_pos and e['id'] in ent_pos:
                    sem = float(sim[scen_pos[s['id']], ent_pos[e['id']]])
                total = w_sem * (sem or 0.0) + w_rule * r_score
                if total >= config.MATCH_MIN_SCORE:
                    scored.append((total, sem, r_score, reasons, e))
            scored.sort(key=lambda x: x[0], reverse=True)
            for total, sem, r_score, reasons, e in scored[:config.MATCH_TOP_K]:
                parts = list(reasons)
                if sem is not None:
                    parts.append(f'语义相似度 {sem:.2f}')
                # 已人工标记（已对接/已排除）的行保留标记，仅更新分数与理由
                conn.execute(
                    '''INSERT INTO matches(scenario_id, enterprise_id, semantic_score,
                       rule_score, total_score, reason) VALUES(?,?,?,?,?,?)
                       ON CONFLICT(scenario_id, enterprise_id) DO UPDATE SET
                       semantic_score=excluded.semantic_score,
                       rule_score=excluded.rule_score,
                       total_score=excluded.total_score,
                       reason=excluded.reason''',
                    (s['id'], e['id'], sem, r_score, round(total, 4), '；'.join(parts)),
                )
                n_written += 1
        if own:
            conn.commit()
        n_linked = link_projects_semantic(conn)
        if own:
            conn.commit()
        return {'semantic': semantic_ok, 'matches': n_written,
                'scenarios': len(scens), 'enterprises': len(ents),
                'projects_linked': n_linked}
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        if own:
            conn.close()


def link_projects_semantic(conn, threshold: float = 0.60) -> int:
    """用语义向量把项目的「计划落地场景」自由文本关联到场景库。

    文件1 的落地场景是“沙湾河”这类自由文本，字符串匹配几乎关联不上；
    改用语义相似度（planned_scene 作查询），达到阈值才挂接。返回新关联数量。
    """
    if not embed.available():
        return 0
    rows = db.q(conn, '''SELECT id, planned_scene FROM projects
                         WHERE scenario_id IS NULL AND planned_scene IS NOT NULL
                         AND planned_scene != '' ''')
    scen_vecs = embed.load_vectors(conn, 'scenario')
    if not rows or not scen_vecs:
        return 0
    scen_ids = list(scen_vecs.keys())
    sm = np.stack([scen_vecs[i] for i in scen_ids])
    qv = embed.encode([r['planned_scene'] for r in rows], is_query=True)
    sims = qv @ sm.T
    n = 0
    for i, r in enumerate(rows):
        j = int(np.argmax(sims[i]))
        if float(sims[i, j]) >= threshold:
            conn.execute('UPDATE projects SET scenario_id=? WHERE id=? AND scenario_id IS NULL',
                         (scen_ids[j], r['id']))
            n += 1
    return n


def refresh_entity(conn, owner_type: str, owner_id: int):
    """单条档案编辑后的增量刷新：重算该实体相关匹配。"""
    semantic_ok = embed.available()
    if semantic_ok:
        row = db.q1(conn, f"SELECT * FROM {'enterprises' if owner_type=='enterprise' else 'scenarios'} WHERE id=?", (owner_id,))
        if row:
            d = _row_to_dict(row)
            text = embed.enterprise_text(d) if owner_type == 'enterprise' else embed.scenario_text(d)
            vec = embed.encode([text], is_query=(owner_type == 'scenario'))[0]
            embed.save_vector(conn, owner_type, owner_id, vec)
    # 简化处理：单点变更直接触发全量重算（~220条规模下秒级完成，保证一致性）
    return recompute_all(conn)
