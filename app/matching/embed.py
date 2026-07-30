"""语义向量：BGE-small-zh-v1.5 加载、编码、库存取。

模型未安装/未下载时自动降级：available() 返回 False，engine 退化为纯规则匹配，
系统其余功能不受影响。模型权重经 ModelScope 下载（scripts/download_model.py）。
"""
import numpy as np

import config

_model = None
_unavailable_reason = None


def available() -> bool:
    """模型目录存在且依赖可导入。"""
    global _unavailable_reason
    if not config.MODEL_DIR.exists():
        _unavailable_reason = '模型未下载（运行 scripts/download_model.py）'
        return False
    try:
        import torch  # noqa: F401
        import sentence_transformers  # noqa: F401
    except Exception as e:
        _unavailable_reason = f'依赖未安装：{e}'
        return False
    return True


def unavailable_reason() -> str:
    available()
    return _unavailable_reason or ''


def load_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(str(config.MODEL_DIR), device='cpu')
    return _model


def encode(texts: list[str], is_query: bool = False) -> np.ndarray:
    """编码为 float32 向量矩阵。查询侧（场景）按 BGE 官方建议加指令前缀。"""
    model = load_model()
    if is_query:
        texts = [config.QUERY_INSTRUCTION + t for t in texts]
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def save_vector(conn, owner_type: str, owner_id: int, vec: np.ndarray):
    conn.execute(
        'REPLACE INTO embeddings(owner_type, owner_id, vector, model_ver) VALUES(?,?,?,?)',
        (owner_type, owner_id, vec.astype(np.float32).tobytes(), config.MODEL_VERSION),
    )


def load_vectors(conn, owner_type: str) -> dict[int, np.ndarray]:
    rows = conn.execute(
        'SELECT owner_id, vector FROM embeddings WHERE owner_type=? AND model_ver=?',
        (owner_type, config.MODEL_VERSION),
    ).fetchall()
    return {r['owner_id']: np.frombuffer(r['vector'], dtype=np.float32) for r in rows}


def enterprise_text(e: dict) -> str:
    """企业匹配文本：只喂与匹配相关的 curated 字段。"""
    parts = [e.get('positioning'), e.get('intro'), e.get('capability'),
             e.get('core_products'), e.get('core_tech'), e.get('applicable_scenes')]
    return '。'.join(p.replace('\n', ' ') for p in parts if p)[:1024]


def scenario_text(s: dict) -> str:
    parts = [s.get('name'), s.get('intro'), s.get('domain'), s.get('main_tech')]
    return '。'.join(p.replace('\n', ' ') for p in parts if p)[:512]
