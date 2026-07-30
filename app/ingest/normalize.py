"""导入清洗：企业名归一化、类别拆分、文本规整。

规则来源（CLAUDE.md 数据陷阱）：
- 企业名常带 （专精特新企业、国高企业）等括号后缀与换行，join 前必须归一化；
- 类别是复合串（如 ②人工智能、智能终端 / ③节能环保），圈码可复用（③既是无人机又是节能环保），
  因此标准桶取「去圈码后的首段」，原始串保留展示。
"""
import re

PAREN_RE = re.compile(r'（[^（）]*）|\([^()]*\)')
WS_RE = re.compile(r'\s+')
CIRCLED_RE = re.compile(r'[①②③④⑤⑥⑦⑧⑨⑩⑪⑫]+')


def norm_name(name) -> str:
    """跨表 join key：去括号后缀 + 去全部空白。"""
    if name is None:
        return ''
    s = str(name)
    s = PAREN_RE.sub('', s)
    s = WS_RE.sub('', s)
    return s.strip('、，,。；; ')


def clean_text(v) -> str:
    """单元格文本规整：None→''，换行压成空格，去首尾空白。"""
    if v is None:
        return ''
    s = str(v).replace('\r', '')
    # 保留中文顿号分隔的可读性，仅把换行变为空格
    s = s.replace('\n', ' ')
    return WS_RE.sub(' ', s).strip()


def clean_display_name(v) -> str:
    """企业展示名：规整空白，并去掉括号前的空格（文件1 换行会引入' （'）。"""
    s = clean_text(v)
    return re.sub(r'\s+（', '（', s).strip()


def merge_segments(*texts, seps=r'[、,，;；]') -> str:
    """能力/场景类文本合并：按分隔符切段后保序去重再拼回（用于同企业多行合并）。"""
    seen, out = set(), []
    for t in texts:
        for item in re.split(seps, clean_text(t)):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return '、'.join(out)


def clean_multiline(v) -> str:
    """保留换行的长文本（简介/项目介绍），仅去掉行首尾空白与多余空行。"""
    if v is None:
        return ''
    lines = [ln.strip() for ln in str(v).replace('\r', '').split('\n')]
    lines = [ln for ln in lines if ln]
    return '\n'.join(lines)


def split_category(raw) -> tuple[str, str]:
    """类别串 → (标准桶, 规整后的原始串)。

    例：'②人工智能、智能终端' → ('人工智能', '②人工智能、智能终端')
        '⑤制造业成品、仪器设备等' → ('制造业成品', ...)
    """
    s = clean_text(raw)
    if not s:
        return '', ''
    bucket = CIRCLED_RE.sub('', s)
    bucket = re.split(r'[、,，/]', bucket)[0].strip()
    return bucket, s


def merge_quals(*texts) -> str:
    """资质合并去重：按 、/，/,/； 切分后保序去重再拼回。"""
    seen, out = set(), []
    for t in texts:
        for item in re.split(r'[、,，;；]', clean_text(t)):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return '、'.join(out)
