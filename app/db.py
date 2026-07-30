"""SQLite 数据访问层：连接管理、初始化、通用查询助手。"""
import sqlite3
from contextlib import contextmanager

import config

SCHEMA_PATH = config.BASE_DIR / 'schema.sql'


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """建表 + 播种初始管理员（幂等）。"""
    with get_db() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
        # 政策轨：enterprises 表追加字段（安全迁移，SQLite ALTER TABLE 不支持 IF NOT EXISTS）
        for col, typ in [('registered_capital', 'REAL'), ('employee_count', 'INTEGER'),
                         ('biz_anomaly', "TEXT DEFAULT '未见异常'")]:
            try:
                conn.execute(f'ALTER TABLE enterprises ADD COLUMN {col} {typ}')
            except Exception:
                pass
        cur = conn.execute('SELECT COUNT(*) AS c FROM users')
        if cur.fetchone()['c'] == 0:
            import auth
            conn.execute(
                'INSERT INTO users(username, password_hash, display_name, role) VALUES(?,?,?,?)',
                (config.ADMIN_USERNAME, auth.hash_password(config.ADMIN_PASSWORD), '系统管理员', 'admin'),
            )
            print(f'[init] 已创建初始管理员 {config.ADMIN_USERNAME} / {config.ADMIN_PASSWORD}（请登录后尽快修改）')


def q(conn, sql, args=()):
    """查询全部行（list[sqlite3.Row]）。"""
    return conn.execute(sql, args).fetchall()


def q1(conn, sql, args=()):
    """查询单行或 None。"""
    return conn.execute(sql, args).fetchone()
