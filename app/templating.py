"""共享 Jinja2 模板实例（run.py 与各 router 共同引用，避免循环导入）。"""
from fastapi.templating import Jinja2Templates

import config

templates = Jinja2Templates(directory=config.BASE_DIR / 'templates')
templates.env.filters['nl2br'] = lambda s: (s or '').replace('\n', '<br>')

# 字段中文标签（表单/详情页共用）
templates.env.globals['EL'] = {
    'name': '企业名称', 'category_bucket': '类别', 'category_raw': '原始类别',
    'intro': '企业与产品简介', 'capability': '场景能力', 'applicable_scenes': '可应用落地场景',
    'qualifications': '资质与荣誉', 'positioning': '核心定位', 'main_business': '主营业务',
    'core_products': '核心产品', 'core_tech': '核心技术', 'clients_cases': '典型客户/案例',
}
templates.env.globals['SL'] = {
    'name': '场景名称', 'domain': '应用领域', 'intro': '场景简介',
    'landing_area': '拟落地应用区域', 'lead_dept': '牵头部门', 'main_tech': '主要技术',
    'ref_case': '参考案例', 'potential_enterprises': '潜在企业及产品',
    'source': '来源', 'status': '状态',
}
# 长文本字段用 textarea，其余用单行输入
templates.env.globals['LONG_E'] = {'intro', 'capability', 'applicable_scenes', 'main_business',
                                   'core_products', 'core_tech', 'clients_cases', 'qualifications'}
templates.env.globals['LONG_S'] = {'intro', 'ref_case', 'potential_enterprises', 'main_tech'}
