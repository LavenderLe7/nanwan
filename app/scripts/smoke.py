"""冒烟测试：进程内 TestClient 走一遍核心链路（不依赖已启动的服务）。

用法：.venv/bin/python scripts/smoke.py
覆盖：导入对账 → 登录/越权 → 匹配结果 → 已知配对回放 → 项目/审核流 → 企业端开关。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import config
import db
from run import app

PASS, FAIL = 0, 0


def check(name, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  ✓ {name}')
    else:
        FAIL += 1
        print(f'  ✗ {name}  {detail}')


def main():
    c = TestClient(app)

    print('== 数据对账 ==')
    with db.get_db() as conn:
        t = {k: db.q1(conn, sql)['c'] for k, sql in {
            'ent': 'SELECT COUNT(*) c FROM enterprises',
            's25': "SELECT COUNT(*) c FROM scenarios WHERE source='南湾25'",
            's80': "SELECT COUNT(*) c FROM scenarios WHERE source='储备库'",
            'proj': 'SELECT COUNT(*) c FROM projects',
            'match': 'SELECT COUNT(*) c FROM matches',
        }.items()}
    check('企业 115 家', t['ent'] == 115, f"实际 {t['ent']}")
    check('南湾25场景 25 个', t['s25'] == 25, f"实际 {t['s25']}")
    check('储备场景 80 个', t['s80'] == 80, f"实际 {t['s80']}")
    check('项目 ≥ 30 个（文件1全量，含延续行；使用中会增长）', t['proj'] >= 30, f"实际 {t['proj']}")
    check('匹配结果已计算', t['match'] > 1000, f"实际 {t['match']}")

    print('== 认证与越权 ==')
    r = c.get('/gov', follow_redirects=False)
    check('未登录访问 /gov 跳转登录', r.status_code == 303)
    r = c.post('/login', data={'username': 'admin', 'password': 'wrong'}, follow_redirects=False)
    check('错误密码回登录页', r.status_code == 303)
    r = c.post('/login', data={'username': 'admin', 'password': config.ADMIN_PASSWORD},
               follow_redirects=False)
    check('管理员登录', r.status_code == 303)
    for p in ['/gov', '/gov/enterprises', '/gov/scenarios', '/gov/match',
              '/gov/projects', '/gov/submissions', '/gov/import', '/gov/users']:
        check(f'{p} 200', c.get(p).status_code == 200)

    print('== 匹配与已知配对回放 ==')
    with db.get_db() as conn:
        s = db.q1(conn, "SELECT id FROM scenarios WHERE name='道路交通隐患整治' AND source='储备库'")
        top10 = [r['name'] for r in db.q(conn, '''SELECT e.name FROM matches m
                 JOIN enterprises e ON e.id=m.enterprise_id
                 WHERE m.scenario_id=? ORDER BY m.total_score DESC LIMIT 10''', (s['id'],))]
        top3 = top10[:3]
        n25 = db.q1(conn, "SELECT COUNT(DISTINCT scenario_id) c FROM matches WHERE scenario_id IN "
                          "(SELECT id FROM scenarios WHERE source='南湾25')")['c']
    # 人工标注了3家企业（耐杰/海威达/杰士安）：要求全部进Top10、至少一家进Top3
    annot = ['耐杰', '海威达', '杰士安']
    check('标注企业全部进 Top10', all(any(a in n for n in top10) for a in annot),
          f'Top10={ [n[:8] for n in top10] }')
    check('标注企业至少一家进 Top3', any(a in n for a in annot for n in top3),
          f'Top3={ [n[:8] for n in top3] }')
    check('南湾25场景全部有候选企业', n25 == 25, f'实际 {n25}/25')
    r = c.get('/gov/api/match/scenario/1')
    check('匹配工作台 API 返回候选列表', r.status_code == 200 and '总分' in r.text)

    print('== 企业端开关 ==')
    with db.get_db() as conn:
        row = db.q1(conn, "SELECT id FROM users WHERE role='enterprise' LIMIT 1")
    if row:
        c2 = TestClient(app)
        c2.post('/login', data={'username': 'oumi', 'password': 'test123456'}, follow_redirects=False)
        r = c2.get('/ent', follow_redirects=False)
        if config.ENTERPRISE_PORTAL_ENABLED:
            check('企业端开放时 /ent 200', r.status_code == 200)
        else:
            check('企业端关闭时 /ent 被拦截', r.status_code == 303)
        r = c2.get('/gov', follow_redirects=False)
        check('企业账号访问 /gov 被拒', r.status_code == 303)
    else:
        print('  - 无企业账号，跳过')

    print(f'\n结果：{PASS} 通过，{FAIL} 失败')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
