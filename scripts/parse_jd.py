# -*- coding: utf-8 -*-
"""
BOSS直聘 JD 整页文本解析器（半自动采集：用户 Ctrl+A 全选复制）
用法: python parse_jd.py data/raw/batch01.txt
输出: data/out/jd_parsed.csv
"""
import re
import sys
import csv
import os

# ---------- 字段：技能别名归并字典 ----------
# 左：原始写法（小写匹配）；右：归并后的标准技能名
# 调优记录 2026-10-09：新增 数据清洗/学习能力/数据运营 等；
#   移除「建模/模型」→ 机器学习（JD 里「数据分析模型」不等于机器学习，易误判）
SKILL_ALIAS = {
    # SQL 家族
    "sql": "SQL", "mysql": "SQL", "关系型数据库": "SQL", "oracle": "SQL",
    "postgresql": "SQL", "sql server": "SQL", "数据库": "SQL",
    "hive": "Hive", "hivesql": "Hive", "数仓": "Hive", "数据仓库": "Hive",
    "etl": "Hive", "clickhouse": "ClickHouse",
    # Excel 家族
    "excel": "Excel", "表格": "Excel", "vlookup": "Excel", "数据透视": "Excel",
    # Python / 分析工具
    "python": "Python", "pandas": "Python", "numpy": "Python",
    "spss": "SPSS", "sas": "SPSS",
    # 可视化 / BI
    "tableau": "BI可视化", "power bi": "BI可视化", "powerbi": "BI可视化",
    "finebi": "BI可视化", "finereport": "BI可视化", "帆软": "BI可视化",
    "数据可视化": "BI可视化", "可视化": "BI可视化", "bi": "BI可视化",
    # 数据处理过程
    "数据清洗": "数据清洗", "清洗": "数据清洗",
    "数据收集": "数据采集", "数据采集": "数据采集", "数据整理": "数据清洗",
    "数据分析": "数据分析", "数据分析/挖掘": "数据挖掘", "数据挖掘": "数据挖掘",
    # 统计 / 数学
    "统计学": "统计学", "统计": "统计学", "数学/统计": "统计学", "数学": "统计学",
    # 机器学习（严格：必须写明）
    "机器学习": "机器学习", "深度学习": "机器学习", "算法模型": "机器学习",
    # 业务能力（非技术）
    "沟通能力": "业务沟通", "沟通": "业务沟通", "协调能力": "业务沟通",
    "表达能力": "业务沟通", "团队协作": "业务沟通", "协作": "业务沟通",
    "逻辑思维": "逻辑思维", "逻辑能力": "逻辑思维", "分析能力": "逻辑思维",
    "量化分析": "逻辑思维", "拆解": "逻辑思维", "数据敏感": "业务理解",
    "业务理解": "业务理解", "业务分析": "业务理解",
    "学习能力": "学习能力", "快速学习": "学习能力", "探索精神": "学习能力",
    # 行业背景
    "电商": "电商行业", "零售": "电商行业",
    # 运营/指标
    "数据运营": "数据运营", "用户画像": "数据运营",
    "指标体系": "数据运营", "关键业务指标": "数据运营",
    # 输出物
    "报表": "报表", "数据报表": "报表", "报表开发": "报表",
    "分析报告": "报表", "看板": "报表", "数据洞察": "报表",
    # 专业背景
    "经济/工商管理": "经管专业", "工商管理": "经管专业",
    "计算机相关专业": "计算机专业", "计算机": "计算机专业",
    # 工具类
    "办公软件": "办公软件", "office": "办公软件", "电脑操作": "办公软件",
    "大数据": "大数据", "spark": "大数据", "hadoop": "大数据",
    "java": "Java", "javascript": "其他编程", "go语言": "其他编程",
    # 数据建模（单列，不并入机器学习）
    "数据建模": "数据建模", "统计建模": "数据建模",
}

EXPERIENCE = ["在校/应届", "经验不限", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"]
EDUCATION = ["中专/中技", "高中", "大专", "本科", "硕士", "博士", "学历不限"]

SALARY_RE = re.compile(r"(\d{1,3})\s*-\s*(\d{1,3})\s*K")
CITY_RE = re.compile(r"·([\u4e00-\u9fa5]{2,6})·")


def parse_salary(text):
    m = SALARY_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse_experience(line):
    for e in EXPERIENCE:
        if e in line:
            return e
    return ""


def parse_education(line):
    for e in EDUCATION:
        if e in line:
            return e
    return ""


def parse_skills(text):
    """在文本中按别名表匹配技能，返回去重后的标准技能列表。
    注意：别名字典已按「长词优先」原则排列，避免 'bi' 误命中 'business' 等。"""
    low = text.lower()
    hits = []
    for alias, std in SKILL_ALIAS.items():
        if alias in low or alias in text:
            if std not in hits:
                hits.append(std)
    return hits


# ---------- 标题党识别 ----------
# 核心：标题写「数据分析」，但正文没有任何技术技能 → 疑似挂羊头卖狗肉
TECH_SKILLS = {"SQL", "Excel", "Python", "BI可视化", "统计学",
               "数据挖掘", "机器学习", "Hive", "SPSS", "ClickHouse",
               "数据清洗", "数据采集", "大数据", "Java", "其他编程", "数据建模"}
# 销售/客服话术信号词
SALES_SIGNALS = ["无需销售", "无需开发客户", "开发客户", "客户资源", "业绩",
                 "提成", "收入无上限", "月入", "底薪", "无需经验", "无需学历",
                 "上不封顶", "电话销售", "客服", "接听", "推广"]


# 「挂羊头」的强信号：出现这些词，基本可断定不是数据分析岗
FAKE_STRONG = ["标注", "打标", "拉框", "训练数据", "数据生产", "图片标注", "标品",
               "比价", "录入员", "无考核", "明日上岗", "今天面试", "即日上岗",
               "无需销售", "无需开发客户", "上不封顶", "电话销售", "接听",
               "打字快", "会用电脑"]
# 「真岗位」的强信号：有明确的岗位职责/任职要求结构，且正文够长
REAL_STRUCT = ["岗位职责", "工作职责", "任职要求", "任职资格", "岗位要求", "职位描述",
               "职位详情", "职位洋情",      # 「职位详情」被 OCR 系统性错识成「职位洋情」
               "工作内容", "岗位职责："]


def is_title_only(full_text, skills):
    """判断是否为『标题党』。
    判定标准不是「正文有没有写工具名」，而是「是不是挂羊头卖狗肉」。
    返回 (bool, 命中理由)

    为什么不能只看工具名（第二轮踩过的坑，批量处理时又踩了一次）：
    腾讯《王者荣耀》15-30K 游戏数据分析、淘宝闪购 15-25K 数据分析专家、
    MOVA 12-24K 电商数据分析师这类岗位，JD 正文常常只写业务职责、
    不写 SQL/Python 等工具名；若按「无工具名 = 标题党」判，会把最优质的
    岗位整批误杀，并系统性拉低技能占比、抬高标题党率。
    """
    has_tech = any(s in TECH_SKILLS for s in skills)
    if has_tech:
        return False, ""

    txt = full_text or ""
    # ① 有「挂羊头」强信号 → 标题党
    hit_fake = [w for w in FAKE_STRONG if w in txt]
    if hit_fake:
        return True, "非数据岗实质内容：" + "/".join(hit_fake[:3])

    # ② 有完整岗位职责结构 且 正文够长 → 判定为真岗位（只是没写工具名）
    has_struct = any(w in txt for w in REAL_STRUCT)
    if has_struct and len(txt) >= 250:
        return False, ""

    # ③ 其余：正文空洞且无工具名 → 标题党
    hit_sales = [w for w in SALES_SIGNALS if w in txt]
    reason = "正文无任何技术技能"
    if hit_sales:
        reason += "；含销售话术：" + "/".join(hit_sales[:3])
    return True, reason


def block_to_record(block):
    """一个 block = 一条 JD 的整页文本；返回 (record_dict, warnings)"""
    warn = []
    lines = [l.strip() for l in block.split("\n") if l.strip()]

    # --- 岗位名：列表里带「数据分析」的第一行（跳过导航词）---
    NAV = ("首页", "职位", "公司", "校园", "海归", "APP", "有了", "海外",
           "无障碍专区", "消息", "简历", "推荐", "客服", "添加求职期望",
           "地图", "搜索", "全国", "收藏立即沟通", "举报", "职位描述", "去App")
    title = ""
    for l in lines[:80]:
        if "数据分析" in l and not any(n in l for n in NAV) and len(l) < 25:
            title = l
            break
    if not title:
        warn.append("岗位名未识别")

    # --- 公司名：在「招聘者」附近的 xx公司 · 招聘者/经理 ---
    company = ""
    m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,30})\s*·\s*(招聘者|经理|HR|主管|总监|招聘专员)", block)
    if m:
        company = m.group(1).strip()
    if not company:
        warn.append("公司名未识别")

    # --- 城市 / 区 ---
    city = ""
    m = CITY_RE.search(block)
    if m:
        city = m.group(1)

    # --- 薪资 ---
    lo, hi = parse_salary(block)

    # --- 经验 / 学历：在「城市 经验 学历」那一行块里找 ---
    exp = parse_experience(block)
    edu = parse_education(block)
    if not exp:
        warn.append("经验未识别")
    if not edu:
        warn.append("学历未识别")

    # --- 技能：优先只看「职位描述」之后的部分 ---
    idx = block.find("职位描述")
    skill_text = block[idx:] if idx >= 0 else block
    skills = parse_skills(skill_text)

    return {
        "title": title,
        "company": company,
        "city": city,
        "salary_min": lo,
        "salary_max": hi,
        "experience": exp,
        "education": edu,
        "skills": "|".join(skills),
        "skill_count": len(skills),
        "raw_desc": "",
    }, warn


def split_blocks(text):
    """按「收藏立即沟通」到下一个列表区切分——一条 JD 一个 block。
    策略：以「举报微信扫码分享」为分隔锚点（每条 JD 详情都紧跟在它后面）"""
    parts = re.split(r"举报微信扫码分享", text)
    blocks = []
    # 第 0 段是首个 JD 的列表 + 第 1 条详情（含）
    blocks.append(parts[0])
    for p in parts[1:]:
        blocks.append(p)
    return blocks


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data/raw/batch01.txt"
    text = open(src, encoding="utf-8").read()

    # 去掉重复的列表区（同一段列表被 Ctrl+A 复制多次）
    blocks = split_blocks(text)

    # 只保留含「职位描述」且含「数据分析」的段（= 真正的 JD 详情段）
    records = []
    for b in blocks:
        if "职位描述" not in b:
            continue
        rec, warn = block_to_record(b)
        if rec["title"]:
            rec["_warn"] = ";".join(warn)
            records.append(rec)

    out = "data/out/jd_parsed.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cols = ["title", "company", "city", "salary_min", "salary_max",
            "experience", "education", "skills", "skill_count", "_warn"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in cols})

    print(f"解析出 {len(records)} 条 JD -> {out}")
    for r in records:
        print("-" * 60)
        for k in cols:
            print(f"  {k:12}: {r.get(k,'')}")


if __name__ == "__main__":
    main()
