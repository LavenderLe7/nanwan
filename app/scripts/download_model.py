"""从 ModelScope 下载 BGE-small-zh-v1.5 到 app/data/models/（HuggingFace 本机不可达）。

用法：.venv/bin/python scripts/download_model.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

MODEL_IDS = [config.MODELSCOPE_MODEL_ID, 'AI-ModelScope/bge-small-zh-v1.5']


def main():
    from modelscope import snapshot_download
    for mid in MODEL_IDS:
        try:
            print(f'尝试下载 {mid} ...')
            path = snapshot_download(mid, local_dir=str(config.MODEL_DIR))
            print(f'完成：{path}')
            return
        except Exception as e:
            print(f'{mid} 失败：{e}')
    sys.exit('所有模型源均下载失败')


if __name__ == '__main__':
    main()
