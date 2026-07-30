"""全局配置：路径、开关、匹配参数。"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DB_PATH = DATA_DIR / 'nanwan.db'
SECRET_PATH = DATA_DIR / 'secret.key'

# 6 张源 Excel 所在目录（app/ 的上级），仅作首次导入源，系统内数据以 SQLite 为准
EXCEL_DIR = BASE_DIR.parent

# 企业端入口开关：本机运行阶段关闭，部署到服务器后改为 True 即开放
ENTERPRISE_PORTAL_ENABLED = True

# 语义匹配
MODEL_DIR = DATA_DIR / 'models' / 'bge-small-zh-v1.5'
MODELSCOPE_MODEL_ID = 'BAAI/bge-small-zh-v1.5'  # 备选: AI-ModelScope/bge-small-zh-v1.5
MODEL_VERSION = 'bge-small-zh-v1.5'
# BGE 检索任务官方建议：查询侧加指令前缀（场景=查询，企业=被检索文档）
QUERY_INSTRUCTION = '为这个句子生成表示以用于检索相关文章：'

SEMANTIC_WEIGHT = 0.7
RULE_WEIGHT = 0.3

# 每个场景保留的候选企业上限（同时总分需 >= MIN_SCORE）
MATCH_TOP_K = 30
MATCH_MIN_SCORE = 0.25

# 初始管理员账号（首次初始化时创建，登录后请尽快在“用户管理”中改密）
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'nanwan2026'

DATA_DIR.mkdir(exist_ok=True)


def load_secret_key() -> str:
    """session 签名密钥：首次运行随机生成并持久化，避免硬编码。"""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text().strip()
    import secrets
    key = secrets.token_hex(32)
    SECRET_PATH.write_text(key)
    return key
