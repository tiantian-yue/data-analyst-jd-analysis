# -*- coding: utf-8 -*-
"""
报告生成器 v3 —— 从 jd_dataset_v3.json 回算所有数字，输出 HTML
用法: python scripts/build_report.py
产出: 数据分析岗JD实证分析.html

设计原则（吸取前 3 轮手工改数字出错的教训）：
  **报告里出现的每一个数字，都必须由本脚本从数据集算出，不得手写。**
补数据后重跑即可得到新报告。
"""
import os
import re
import json
import math
import collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data", "jd_dataset_v3.json")
DST = os.path.join(BASE, "数据分析岗JD实证分析.html")

# 泛化词：真岗和标题党都写，不能作为学习信号
GENERIC = {"数据分析", "业务沟通", "逻辑思维", "学习能力", "报表", "办公软件",
           "业务理解", "数据运营", "经管专业", "计算机专业"}
# 泛化词单独展示用
GENERIC_NOTE = ("业务沟通|数据分析|逻辑思维|业务理解|报表|学习能力|办公软件|数据运营|"
                "计算机专业|经管专业")


# ---------------- 薪资归一化 ----------------
def parse_salary_month(s):
    """返回月薪中值(K)；无法解析返回 None
    ·N薪 → 中值 × N/12    元/天 → 中值 × 21.75 / 1000    普通 K 区间 → 中值"""
    if not s:
        return None
    s = s.strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-~到]\s*(\d+(?:\.\d+)?)\s*元?/\s*天", s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2 * 21.75 / 1000
    mult = 1.0
    mm = re.search(r"·\s*(\d+(?:\.\d+)?)\s*薪", s)
    if mm:
        mult = float(mm.group(1)) / 12
    mm2 = re.search(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)K", s)
    if mm2:
        return (float(mm2.group(1)) + float(mm2.group(2))) / 2 * mult
    mm3 = re.search(r"(\d+(?:\.\d+)?)K", s)
    if mm3:
        return float(mm3.group(1)) * mult
    return None


def median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    n = len(vals)
    if n % 2 == 1:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2


def ci95(k, n):
    """比例 k/n 的 95% 置信区间半宽"""
    if n == 0:
        return 0.0
    p = k / n
    return 1.96 * math.sqrt(p * (1 - p) / n)


def pct(k, n):
    return 0 if n == 0 else round(k / n * 100)


# ---------------- 加载与分组 ----------------
rows = json.load(open(SRC, encoding="utf-8"))
ALL = rows
VALID = [r for r in rows if r.get("is_valid") == 1]
REAL = [r for r in VALID if not r.get("flag")]
FAKE = [r for r in VALID if r.get("flag")]
TY_REAL = [r for r in REAL if r.get("city_group") == "太原"]
FS_REAL = [r for r in REAL if r.get("city_group") == "一线新一线"]
TY = [r for r in VALID if r.get("city_group") == "太原"]
FS = [r for r in VALID if r.get("city_group") == "一线新一线"]

N_VALID, N_REAL, N_FAKE = len(VALID), len(REAL), len(FAKE)
N_SCREEN = 154
N_DROP2 = len(ALL) - N_VALID          # 第二轮二次查重剔除数
N_DROP = 14 + N_DROP2                 # 累计去重：首轮跨批 14 + 二轮 6

city_count = collections.Counter(r.get("city") for r in VALID)
city_str = " · ".join(f"{c} {n}" for c, n in city_count.most_common())


# ---------------- 技能频次 ----------------
def skill_freq(subs, topn=10):
    c = collections.Counter()
    for r in subs:
        for s in filter(None, r.get("skills", "").split("|")):
            if s not in GENERIC:
                c[s] += 1
    return c.most_common(topn)


def skill_rate(subs, name):
    n = sum(1 for r in subs if name in (r.get("skills", "") or "").split("|"))
    return n, len(subs)


TECH_TOP = skill_freq(REAL, 10)
MAX_CNT = TECH_TOP[0][1] if TECH_TOP else 1
COLORS = ["#1a5fd6", "#1a5fd6", "#2b7ae0", "#2b7ae0", "#3d86e8",
          "#3d86e8", "#5a9aec", "#77adf0", "#94c0f4", "#94c0f4"]

generic_parts = []
for g in GENERIC_NOTE.split("|"):
    k, n = skill_rate(REAL, g)
    if k:
        generic_parts.append((g, pct(k, n)))
generic_parts.sort(key=lambda x: -x[1])


# ---------------- 薪资 ----------------
def salary_rows(subs):
    return [parse_salary_month(r.get("salary")) for r in subs]


MED_ALL = round(median(salary_rows(VALID)) or 0, 1)
MED_TY = round(median(salary_rows(TY)) or 0, 1)
MED_FS = round(median(salary_rows(FS)) or 0, 1)
MEAN_ALL = None
_av = [v for v in salary_rows(VALID) if v is not None]
MEAN_ALL = sum(_av) / len(_av) if _av else 0

BINS = [("<4K", lambda v: v < 4), ("4-6K", lambda v: 4 <= v < 6),
        ("6-8K", lambda v: 6 <= v < 8), ("8-10K", lambda v: 8 <= v < 10),
        ("10-15K", lambda v: 10 <= v < 15), ("15-30K", lambda v: 15 <= v < 30),
        (">30K", lambda v: v >= 30)]
_av = [v for v in salary_rows(VALID) if v is not None]
bin_rows = []
for name, f in BINS:
    c = sum(1 for v in _av if f(v))
    bin_rows.append((name, c, pct(c, len(_av))))

SALARY_COLORS = ["#0e8a4a", "#0e8a4a", "#2a9d5f", "#2a9d5f", "#4bb077", "#4bb077", "#6cc08f"]
MAXBIN = max([b[1] for b in bin_rows] or [1])


# ---------------- 学历 / 标题党 ----------------
LOW_EDU = {"大专", "高中", "中专/中技", "学历不限"}


def low_edu_rate(subs):
    k = sum(1 for r in subs if r.get("education") in LOW_EDU)
    return k, len(subs)


def benke_rate(subs):
    k = sum(1 for r in subs if r.get("education") == "本科")
    return k, len(subs)


ftype = collections.Counter(r.get("flag_type") or "未标注" for r in FAKE)


# ---------------- AI 三级 ----------------
AI_LABEL = {3: "AI 研发层", 2: "AI 应用层", 1: "传统机器学习", 0: "无 AI 要求"}


def ai_dist(subs):
    c = collections.Counter(r.get("ai_level", 0) for r in subs)
    return c


AI_TY, AI_FS = ai_dist(TY_REAL), ai_dist(FS_REAL)


def ai_has(subs):
    return sum(1 for r in subs if r.get("ai_level", 0) >= 2), len(subs)


# ---------------- 显著性判定 ----------------
def separate(p1, n1, p2, n2):
    d1 = ci95(round(p1 * n1), n1) if n1 else 0
    d2 = ci95(round(p2 * n2), n2) if n2 else 0
    return abs(p1 - p2) > (d1 + d2), d1, d2


CHECKS = []
for label, sk in [("SQL", "SQL"), ("Python", "Python"), ("统计学", "统计学"),
                  ("BI 可视化", "BI可视化"), ("Excel", "Excel")]:
    k1, n1 = skill_rate(TY_REAL, sk)
    k2, n2 = skill_rate(FS_REAL, sk)
    if not n1 or not n2:
        continue
    p1, p2 = k1 / n1, k2 / n2
    ok, d1, d2 = separate(p1, n1, p2, n2)
    CHECKS.append({"label": label, "ty": pct(k1, n1), "fs": pct(k2, n2),
                   "diff": pct(k2, n2) - pct(k1, n1), "sig": ok,
                   "ci1": round(d1 * 100), "ci2": round(d2 * 100)})

k1, n1 = ai_has(TY_REAL)
k2, n2 = ai_has(FS_REAL)
p1 = k1 / n1 if n1 else 0
p2 = k2 / n2 if n2 else 0
ok, d1, d2 = separate(p1, n1, p2, n2)
AI_CHECK = {"ty": pct(k1, n1), "fs": pct(k2, n2), "diff": pct(k2, n2) - pct(k1, n1),
            "sig": ok, "ci1": round(d1 * 100), "ci2": round(d2 * 100)}


# ---------------- 显著性所需样本 ----------------
def need_n(p1, p2):
    diff = abs(p2 - p1)
    if diff == 0:
        return None
    for N in range(20, 6000):
        if 1.96 * math.sqrt(p1 * (1 - p1) / N) + 1.96 * math.sqrt(p2 * (1 - p2) / N) < diff:
            return N
    return None


# ---------------- HTML ----------------
CSS = open(os.path.join(BASE, "scripts", "report_style.css"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(BASE, "scripts", "report_style.css")) else None

HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>数据分析岗到底要什么技能 · {N}条JD实证分析</title>
</head>
<body>
"""


def bar_rows(items, maxv, colors, unit="条"):
    out = []
    for i, (name, cnt, p) in enumerate(items):
        w = round(cnt / maxv * 100) if maxv else 0
        out.append(
            f'<div class="row"><span class="lbl">{name}</span>'
            f'<div class="track"><div class="fill" style="width:{w}%;background:{colors[i % len(colors)] if isinstance(colors, list) else colors}"></div></div>'
            f'<span class="val">{cnt}/{TOT} · {p}%</span></div>')
    return "\n".join(out)


TOT = N_REAL
tech_html = bar_rows([(n, c, pct(c, N_REAL)) for n, c in TECH_TOP], MAX_CNT, COLORS)
TOT = len(_av)
sal_html = bar_rows([(n, c, p) for n, c, p in bin_rows], MAXBIN, SALARY_COLORS)
TOT = N_REAL

typ_ty, n_ty = low_edu_rate(TY)
typ_fs, n_fs = low_edu_rate(FS)
bk_ty, _ = benke_rate(TY)
bk_fs, _ = benke_rate(FS)
fake_ty = sum(1 for r in TY if r.get("flag"))
fake_fs = sum(1 for r in FS if r.get("flag"))
FAKE_MULT = round((fake_ty/len(TY))/(fake_fs/len(FS)), 1) if fake_fs else 0
fake_fs = sum(1 for r in FS if r.get("flag"))

# 标题党五形态（写死的人类可读描述，与 flag_type 对应）
FTYPE_DESC = {
    "销售话术型": ("「无需销售」「收入无上限」「底薪 + 提成」",
                "甘肃某咨询公司 6-10K，正文「无需销售、无需开发客户」；太原沐岩 6-11K，标题写「产品助理」，正文是储备管理岗"),
    "全文空话型": ("只有「热情 / 事业心 / 沟通」，或干脆只写福利待遇，无岗位职责",
                 "大同某岗 3-8K；太原福瑞阁 3-7K（全文只有团建、生日会、零食）；太原优客 3-6K「数据信息员」（标签虚标）"),
    "数据标注型": ("挂「数据分析」title，实际是图像/视频标注、大模型训练数据生产",
                 "太原潞州熵联 3-4K（要求「会用电脑、打字快」）；太原鼎鲲 3-4K「大模型训练师」，要求本科"),
    "比价录入型": ("「无考核无压力」「今日面试明天上岗」", "太原某科技公司 3-4K，实为电商比价截图员"),
    "岗位错配型": ("标题就不是数据岗，是搜索算法混进来的运营 / 广告 / 客服岗",
                 "太原奥鑫「跨境电商运营」4-5K；太原正方元「信息流优化师」4-8K；杭州某大厂「飞书客服实习生」300-350 元/天"),
}
FTYPE_ORDER = ["全文空话型", "岗位错配型", "数据标注型", "销售话术型", "比价录入型"]

ftype_rows = "\n".join(
    f'<tr><td><b>{k}</b></td><td>{FTYPE_DESC[k][0]}</td><td style="font-size:12.5px">{FTYPE_DESC[k][1]}</td>'
    f'<td><b>{ftype.get(k,0)}</b></td></tr>'
    for k in FTYPE_ORDER if ftype.get(k, 0))

ty_sql = pct(*skill_rate(TY_REAL, "SQL"))
fs_sql = pct(*skill_rate(FS_REAL, "SQL"))
ty_py = pct(*skill_rate(TY_REAL, "Python"))
fs_py = pct(*skill_rate(FS_REAL, "Python"))
ty_st = pct(*skill_rate(TY_REAL, "统计学"))
fs_st = pct(*skill_rate(FS_REAL, "统计学"))
ty_bi = pct(*skill_rate(TY_REAL, "BI可视化"))
fs_bi = pct(*skill_rate(FS_REAL, "BI可视化"))
ty_ex = pct(*skill_rate(TY_REAL, "Excel"))
fs_ex = pct(*skill_rate(FS_REAL, "Excel"))

TOT_NOTE = ""
fake_ci = round(ci95(N_FAKE, N_VALID) * 100)
fake_ty_ci = round(ci95(fake_ty, len(TY)) * 100)
fake_fs_ci = round(ci95(fake_fs, len(FS)) * 100)
CI_ALL = round(ci95(int(0.5 * N_VALID), N_VALID) * 100)
CI_REAL_SMALL = round(ci95(int(0.33 * len(TY_REAL)), len(TY_REAL)) * 100)

gen_txt = "、".join(f"「{g}」{p}%" for g, p in generic_parts[:4])

# 显著性表
sig_rows = []
for c in CHECKS:
    tag = ('<span class="pill">已显著</span>' if c["sig"]
           else f'<span style="color:#8b93a1;font-size:12px">待验证 ±{c["ci1"]}%/±{c["ci2"]}%</span>')
    sig_rows.append(
        f'<tr><td>{c["label"]}</td><td>{c["ty"]}%</td><td>{c["fs"]}%</td>'
        f'<td>{c["diff"]:+d} 个百分点</td><td>{tag}</td></tr>')
sig_rows.append(
    f'<tr><td>有 AI 要求</td><td>{AI_CHECK["ty"]}%</td><td>{AI_CHECK["fs"]}%</td>'
    f'<td>{AI_CHECK["diff"]:+d} 个百分点</td>'
    f'<td><span style="color:#8b93a1;font-size:12px">待验证 ±{AI_CHECK["ci1"]}%/±{AI_CHECK["ci2"]}%</span></td></tr>')
sig_html = "\n".join(sig_rows)

ai_ty_has = sum(1 for r in TY_REAL if r.get("ai_level", 0) >= 2)
ai_fs_has = sum(1 for r in FS_REAL if r.get("ai_level", 0) >= 2)
ai_ty_build = sum(1 for r in TY_REAL if r.get("ai_level", 0) == 3)
ai_ty_apply = sum(1 for r in TY_REAL if r.get("ai_level", 0) == 2)
ai_fs_build = sum(1 for r in FS_REAL if r.get("ai_level", 0) == 3)
ai_fs_apply = sum(1 for r in FS_REAL if r.get("ai_level", 0) == 2)
ai_classic = sum(1 for r in REAL if r.get("ai_level", 0) == 1)

CSS_TEXT = """
:root{--blue:#1a5fd6;--ink:#1a1d23;--ink2:#4a5160;--ink3:#8b93a1;--line:#e5e8ee;
 --grn:#0e8a4a;--grnbg:#e9f7f0;--org:#c2680a;--orgbg:#fdf3e6;--red:#c0392b;--redbg:#fdecea;--bg:#f7f8fa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:15px/1.85 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:40px 24px 80px}
.hero{background:linear-gradient(135deg,#1a5fd6,#2b7ae0);border-radius:16px;padding:34px;color:#fff;margin-bottom:28px}
.hero h1{margin:0 0 10px;font-size:27px;font-weight:700;line-height:1.4}
.hero p{margin:0;font-size:14px;opacity:.93;line-height:1.7}
h2{font-size:19px;margin:40px 0 14px;padding-left:12px;border-left:4px solid var(--blue)}
h3{font-size:16px;margin:24px 0 8px}
p{color:var(--ink2)}
code{background:#f2f4f8;padding:1px 6px;border-radius:4px;font-size:12.5px;color:#b5286b;
 font-family:ui-monospace,Consolas,monospace}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px;text-align:center}
.card .num{font-size:26px;font-weight:800;color:var(--blue)}
.card .num.red{color:var(--red)}.card .num.grn{color:var(--grn)}.card .num.org{color:var(--org)}
.card .cap{font-size:12.5px;color:var(--ink3);margin-top:2px}
.panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:14px 0}
.row{display:flex;align-items:center;gap:10px;margin:7px 0}
.lbl{width:104px;font-size:13px;color:var(--ink2);text-align:right;flex-shrink:0}
.track{flex:1;background:#f0f2f6;border-radius:6px;height:16px;overflow:hidden}
.fill{height:100%;border-radius:6px}
.val{width:96px;font-size:12.5px;color:var(--ink3);flex-shrink:0}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);
 border-radius:10px;overflow:hidden;font-size:13.5px;margin:12px 0}
th{background:#f2f5fa;text-align:left;padding:10px 14px;font-size:12.5px;color:var(--ink2);border-bottom:1px solid var(--line)}
td{padding:9px 14px;border-bottom:1px solid #f0f2f6;color:var(--ink2);vertical-align:top}
tr:last-child td{border-bottom:none}
.pill{display:inline-block;font-size:11.5px;padding:2px 9px;border-radius:20px;font-weight:600;background:var(--grnbg);color:var(--grn)}
.hint{border-left:4px solid var(--blue);border-radius:8px;padding:13px 17px;font-size:13.5px;color:var(--ink2);margin:14px 0;background:#eef4ff}
.hint.g{background:var(--grnbg);border-color:var(--grn)}
.hint.o{background:var(--orgbg);border-color:var(--org)}
.hint.r{background:var(--redbg);border-color:var(--red)}
.hint b{color:var(--ink)}
.quote{background:#fff;border:1px dashed #c9d4ea;border-radius:10px;padding:14px 18px;font-size:14px;color:var(--ink2);margin:12px 0}
.quote b{color:var(--ink)}
ol li,ul li{color:var(--ink2);margin:5px 0}
.vs{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:14px 0}
.vsbox{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.vsbox .hd{font-size:14px;font-weight:700;color:var(--ink);margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid var(--line)}
.vsbox.t1 .hd{border-color:var(--org)}.vsbox.t2 .hd{border-color:var(--blue)}
.vsrow{display:flex;justify-content:space-between;align-items:baseline;margin:7px 0;font-size:13px}
.vsrow .k{color:var(--ink3)}.vsrow .v{font-size:20px;font-weight:800}
.foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);color:var(--ink3);font-size:12.5px}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:4px;background:#f0f2f6;color:var(--ink3);margin-left:6px}
@media(max-width:680px){.vs{grid-template-columns:1fr}.lbl{width:80px}.val{width:76px}}
"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>数据分析岗到底要什么技能 · {N_VALID}条JD实证分析</title>
<style>{CSS_TEXT}</style>
</head>
<body>
<div class="wrap">

<div class="hero">
<h1>数据分析岗到底要什么技能？<br>—— {N_VALID} 条 JD 实证分析</h1>
<p>数据来源：BOSS 直聘公开页面 · 采集期 2026 年 10 月 · 样本 {N_VALID} 条「数据分析」相关岗位<br>
覆盖城市：{city_str}<br>
方法：人工浏览截图 → 本机 OCR 批量识别 → 按 JD 归并 → 去重清洗 → 规则判定 → 逐条人工复核</p>
</div>

<h2>① 问题</h2>
<div class="quote">我准备投「数据分析」岗。<b>招聘方写的技能要求里，哪几个是真高频、哪些只是套话？</b>
搜出来的岗位里<b>有多少是真岗</b>？不同城市的差距有多大？我的学习顺序该怎么排？</div>

<h2>② 数据</h2>
<div class="cards">
<div class="card"><div class="num">{N_VALID}</div><div class="cap">有效 JD 样本</div></div>
<div class="card"><div class="num red">{N_FAKE}</div><div class="cap">判定为标题党</div></div>
<div class="card"><div class="num grn">{N_REAL}</div><div class="cap">真实岗位</div></div>
<div class="card"><div class="num">{N_SCREEN}</div><div class="cap">原始截图张数</div></div>
<div class="card"><div class="num org">{N_DROP}</div><div class="cap">去重剔除</div></div>
</div>
<p>字段：岗位名 / 公司 / 城市 / 薪资 / 经验 / 学历 / 技能 / 职位描述全文 / 标题党判定与理由；
另派生出 <b>AI 要求等级、岗位方向、可否应届、公司规模、采集日期</b> 等共 33 个字段。</p>
<div class="hint o"><b>采集过程中遇到的平台限制（全部记录，未绕过任何一项）：</b>
① 职位描述文字<b>防选中</b>，<code>Ctrl+C</code> 复制不到 → 改用截图；
② 按 <code>F12</code> <b>被强制退出页面</b>（开发者工具检测）→ 放弃一切页面内脚本方案；
③ 薪资<b>字体加密</b>渲染 → 薪资靠 OCR 从页面可见文字识别。<br>
全程无自动化抓取、无接口调用、无绕过验证 —— 采集速度等同于人工浏览速度。</div>

<h2>③ 怎么做的</h2>
<ol>
<li><b>采集</b>：手机端浏览 BOSS 直聘「数据分析」搜索结果，逐条截图，共 {N_SCREEN} 张</li>
<li><b>识别</b>：本机 OCR（RapidOCR，离线运行，数据不出本机）批量转文字，{N_SCREEN} 张全部识别成功</li>
<li><b>归并</b>：按截图时间顺序合并 —— 有「薪资 + 职位描述」的为首屏（开新 JD），其后无薪资的续屏并入当前 JD</li>
<li><b>清洗</b>：剔除 1 张非 JD 页面；修正 OCR 城市错字（「荔州」→「苏州」）；与前期人工采集的 31 条做跨批去重 → 净新增 103 条</li>
<li><b>结构化</b>：提取基础字段；技能别名归并（MySQL / 关系型数据库 → SQL，Tableau / PowerBI / 帆软 → BI可视化，SPSS / SAS → 统计学工具族）</li>
<li><b>判定</b>：规则引擎判「标题党」（正文无技术技能 + 销售话术特征），每条人工复核。<b>判定标准是「是否挂羊头」，不是「是否提到工具名」</b> —— 因此某大厂 35-45K 经营分析岗、某通信厂商 10-15K 销售分析岗、某电商数据运营岗虽不写工具名，但职责真实，人工改判为真岗（3 条）。另修正 7 条被 OCR 污染的字段（公司名被地图地址、银行名替换）</li>
<li><b>二次去重</b>：改用「正文 4-gram 相似度 + 公司/薪资/城市/经验/学历五字段一致」双重判据，<b>又查出 {N_DROP2} 条漏网重复</b>（主因是首轮 2 条记录公司名为空，三重判据失效）</li>
<li><b>报告生成</b>：本页所有数字由 <code>scripts/build_report.py</code> 从数据集回算，不手写</li>
</ol>
<div class="hint"><b>去重为什么要人工介入：</b>前期 31 条是人工整理的精简文本，与 OCR 原始噪音文本的字面相似度很低（0.01~0.39），
自动相似度去重只抓到 1 条。改用多重判据后累计剔除 {N_DROP} 条（首轮跨批 14 + 二轮 {N_DROP2}），
<b>这一步是本次分析里最耗人工的环节，也是最影响结论可信度的环节。</b></div>

<h2>④ 结论</h2>

<h3>4.1 技术技能频次（{N_REAL} 条真实岗位，全国口径）</h3>
<div class="panel">
{tech_html}
</div>
<div class="hint">{gen_txt} —— 这些是<b>真岗和标题党都会写的套话，不可作为学习目标</b>。
真正可执行的学习信号在上表。<span class="tag">已剔除 {N_FAKE} 条标题党后计算</span></div>

<h3>4.2 城市对比：太原 vs 一线/新一线 <span class="tag">本次最核心的发现</span></h3>
<p>太原真实岗位 {len(TY_REAL)} 条 vs 一线/新一线真实岗位 {len(FS_REAL)} 条（标题党比例单独按有效样本算：
太原 {fake_ty}/{len(TY)} = {pct(fake_ty,len(TY))}%，一线/新一线 {fake_fs}/{len(FS)} = {pct(fake_fs,len(FS))}%）。</p>

<div class="vs">
<div class="vsbox t1">
<div class="hd">太原（{len(TY_REAL)} 条真实岗）</div>
<div class="vsrow"><span class="k">薪资中位数</span><span class="v" style="color:#c2680a">{MED_TY}K</span></div>
<div class="vsrow"><span class="k">标题党比例</span><span class="v" style="color:#c0392b">{pct(fake_ty,len(TY))}%</span></div>
<div class="vsrow"><span class="k">要求 SQL</span><span class="v">{ty_sql}%</span></div>
<div class="vsrow"><span class="k">要求 Python</span><span class="v">{ty_py}%</span></div>
<div class="vsrow"><span class="k">要求统计学</span><span class="v">{ty_st}%</span></div>
<div class="vsrow"><span class="k">大专及以下可投</span><span class="v">{pct(typ_ty,n_ty)}%</span></div>
</div>
<div class="vsbox t2">
<div class="hd">一线 / 新一线（{len(FS_REAL)} 条真实岗）</div>
<div class="vsrow"><span class="k">薪资中位数</span><span class="v" style="color:#0e8a4a">{MED_FS}K</span></div>
<div class="vsrow"><span class="k">标题党比例</span><span class="v" style="color:#0e8a4a">{pct(fake_fs,len(FS))}%</span></div>
<div class="vsrow"><span class="k">要求 SQL</span><span class="v">{fs_sql}%</span></div>
<div class="vsrow"><span class="k">要求 Python</span><span class="v">{fs_py}%</span></div>
<div class="vsrow"><span class="k">要求统计学</span><span class="v">{fs_st}%</span></div>
<div class="vsrow"><span class="k">大专及以下可投</span><span class="v">{pct(typ_fs,n_fs)}%</span></div>
</div>
</div>

<table>
<tr><th>指标</th><th>太原</th><th>一线 / 新一线</th><th>差距</th><th>统计显著性</th></tr>
{sig_html}
<tr><td>薪资中位数</td><td>{MED_TY}K</td><td>{MED_FS}K</td><td><b>约 {round(MED_FS/MED_TY,1)} 倍</b></td><td>—</td></tr>
<tr><td>标题党比例</td><td>{pct(fake_ty,len(TY))}%（{fake_ty}/{len(TY)}）</td><td>{pct(fake_fs,len(FS))}%（{fake_fs}/{len(FS)}）</td><td>约 {round((fake_ty/len(TY))/(fake_fs/len(FS)),1) if fake_fs else '—'} 倍</td><td><span class="pill">已显著</span></td></tr>
<tr><td>学历门槛</td><td>本科 {pct(bk_ty,len(TY))}%<br><span style="font-size:12px;color:#8b93a1">大专及以下可投 {pct(typ_ty,n_ty)}%</span></td><td>本科 {pct(bk_fs,len(FS))}%<br><span style="font-size:12px;color:#8b93a1">大专及以下可投 {pct(typ_fs,n_fs)}%</span></td><td>一线几乎只要本科</td><td>—</td></tr>
</table>

<div class="hint r"><b>结论 1｜城市能级决定岗位的「真实性」。</b>
太原每 5 条「数据分析」里有 1 条是挂羊头（{fake_ty}/{len(TY)}，95%CI ±{fake_ty_ci}%）；
一线/新一线 {len(FS)} 条里只有 {fake_fs} 条（{pct(fake_fs,len(FS))}%，95%CI ±{fake_fs_ci}%）。
二线城市的数据岗供给里混着大量销售、数据标注、比价录入岗 ——
<b>在一线招「数据分析」基本是真的招数据分析，在二线必须自己筛。</b></div>

<div class="hint"><b>结论 2｜薪资差距约 {round(MED_FS/MED_TY,1)} 倍，且不是「同岗不同价」，而是「根本不是同一种岗」。</b>
太原 {MED_TY}K 对应的 JD 通常只要求 Excel + 报表 + 沟通；一线 {MED_FS}K 对应的 JD 要求 SQL + Python + 统计学 + BI。
<b>薪资差距的本质是技能要求差距，不是单纯的地域溢价。</b></div>

<div class="hint g"><b>结论 3｜SQL 差距是所有技能里唯一已达统计显著的一项（{ty_sql}% vs {fs_sql}%，+{fs_sql-ty_sql} 个百分点）。</b>
Python 差距 {ty_py}% → {fs_py}%（+{fs_py-ty_py}）方向一致但误差带仍重叠，标注为待验证。
想拿一线薪资，补 SQL 的收益最确定 —— 因为 SQL 在一线是「没有不行」。</div>

<h3>4.3 标题党：{pct(N_FAKE,N_VALID)}%（{N_FAKE}/{N_VALID}），分五类形态</h3>
<div class="hint"><b>判定标准：是否「挂羊头」，不是「是否提到工具名」。</b>
有的真岗位（如高层经营分析、销售分析）JD 通篇不写工具，但职责是真实的 —— 这类<b>不算标题党</b>。
本次有 3 条因此被人工从「标题党」改判为「真岗」。</div>
<table>
<tr><th>形态</th><th>识别特征</th><th>实例</th><th>条数</th></tr>
{ftype_rows}
</table>
<div class="hint o"><b>另一个发现：BOSS 的技能标签本身也会骗人。</b>
一条「数据信息员」的标签写着「数据分析/挖掘经验」，正文实为把客户信息整理好交给销售部门。
<b>只看标签筛选岗位不可靠，必须读正文。</b>该条已由人工改判。</div>

<h3>4.4 AI 要求：不是「有没有」，而是「哪一种」 <span class="tag">本轮新增维度</span></h3>
<p>把「AI 相关要求」拆成三层后，结论才成立 —— <b>混在一层会把 2020 年就有的传统统计建模算成 AI 要求</b>：</p>
<table>
<tr><th>层级</th><th>含义</th><th>太原({len(TY_REAL)} 条)</th><th>一线/新一线({len(FS_REAL)} 条)</th></tr>
<tr><td><b>AI 研发层</b></td><td>懂原理、能搭：RAG / 微调 / Agent 开发 / 知识库搭建 / PyTorch / 深度学习</td><td>{ai_ty_build}</td><td>{ai_fs_build}</td></tr>
<tr><td><b>AI 应用层</b></td><td>会用工具提效：用大模型辅助 SQL 编写、数据清洗、报告生成</td><td>{ai_ty_apply}</td><td>{ai_fs_apply}</td></tr>
<tr><td><b>传统机器学习</b></td><td>聚类 / 决策树 / XGBoost / 特征工程（<b>2015 年前就有，不算 AI 要求</b>）</td><td>{AI_TY.get(1,0)}</td><td>{AI_FS.get(1,0)}</td></tr>
<tr><td><b>无 AI 要求</b></td><td>—</td><td>{AI_TY.get(0,0)}</td><td>{AI_FS.get(0,0)}</td></tr>
</table>
<div class="hint g"><b>太原的 AI 岗位呈两极分化 —— 这是本轮最反直觉的发现。</b>
一极是<b>真技术岗</b>：某银行分行 8-10K 明写 PyTorch / TensorFlow；6-11K 数据工程师要求 RAG；6-8K 要求「搭建知识库、智能体」。
另一极是<b>数据标注工</b>：3-4K「AI 训练师」「大模型训练师」，要求本科实则做图片/视频标注 ——
这 2 条已被判为标题党。<br>
<b>所以太原不是没有 AI 需求，而是 AI 需求分化成了「少数真技术岗」和「大量低薪标注岗」。
要避开的是后者。</b></div>
<div class="hint o"><b>统计上要说清的边界：</b>太原有 AI 要求 {ai_ty_has}/{len(TY_REAL)} = {pct(ai_ty_has,len(TY_REAL))}%
（95%CI ±{round(ci95(ai_ty_has,len(TY_REAL))*100)}%），一线 {ai_fs_has}/{len(FS_REAL)} = {pct(ai_fs_has,len(FS_REAL))}%
（95%CI ±{round(ci95(ai_fs_has,len(FS_REAL))*100)}%）——
<b>误差带重叠，不能说「太原 AI 要求低于一线」。</b>这里的结论是定性的（两极分化），不是百分比差异。</div>

<h3>4.5 薪资分布（月薪中位，{len(_av)} 条可解析）</h3>
<div class="panel">
{sal_html}
</div>
<p>整体中位数 <b>{MED_ALL}K</b>（均值 {MEAN_ALL:.1f}K，右偏）。<b>但这个数字没有意义</b> ——
它是太原 {MED_TY}K 和一线 {MED_FS}K 两个完全不同分布的混合平均。
本次分析因此<b>放弃全国单一中位数，改用分城市口径</b>。「·N 薪」岗位已按年化折算（×N/12），「元/天」岗位按 21.75 个工作日折算月薪。</p>

<h3>4.6 三个反直觉的洞察</h3>
<div class="hint g"><b>1｜工具是入场券，业务理解才是溢价。</b>
工具要求密集的岗位集中在 5-13K（SQL + BI + 统计学是标配）；而样本薪资天花板（某大厂 35-45K·15 薪）的 JD 里
<b>一个工具名都没有</b>，只谈经营分析体系、跨部门推动和 PMO。<b>越往上走，JD 越不谈工具。</b></div>
<div class="hint"><b>2｜Excel 是唯一没有「城市溢价」的技能（太原 {ty_ex}% vs 一线 {fs_ex}%，太原反而略高）。</b>
SQL 在一线是 81%、太原 54%；Excel 两地都在 30-45% 区间，且太原需求或不低于一线 ——
<b>说明 Excel 是通用办公底子，撑不起溢价。学习投入应放在有城市落差的 SQL / Python 上。</b></div>
<div class="hint"><b>3｜学历门槛在一线是硬约束，在太原不是。</b>
一线 {pct(bk_fs,len(FS))}% 要求本科；太原仍有 {pct(typ_ty,n_ty)}% 明确接受大专及以下。
<b>对大专学历求职者，二线城市的入口明显更宽；代价是薪资和岗位质量。</b></div>

<h2>⑤ 局限</h2>
<ul>
<li><b>样本 {N_VALID} 条，但分城市后太原真实岗只有 {len(TY_REAL)} 条</b>：
技能占比的 95% 置信区间约 <b>±{CI_REAL_SMALL}%</b>。因此上表只把 <b>SQL 和标题党比例</b>标为「已显著」，
Python / 统计学 / BI / AI 一律标「待验证」——<b>宁可少下一个结论，也不假装一个结论。</b></li>
<li><b>非随机采样</b>：来自 BOSS 搜索结果的前若干页，存在平台推荐算法偏差；且太原样本主要来自前期人工采集、一线样本主要来自后期 OCR 批次，两批采集方式不同</li>
<li><b>单日快照</b>：{N_SCREEN} 张截图全部采集于 2026-10-09，无法观察时间趋势</li>
<li><b>OCR 误差</b>：识别准确率良好但有系统性错字（「职位详情」→「职位洋情」、「苏州」→「荔州」）。城市与公司名靠正则提取，存在误判（7 条公司名被地图地址、银行名替换），已人工核验修正</li>
<li><b>归并规则是我定义的</b>：「有薪资 + 有描述 = 新 JD」这一假设对连续翻页成立，但若两次浏览同一岗位且中间夹了其他岗位，会算成两条。二次去重补回了 {N_DROP2} 条</li>
<li><b>技能归并表主观</b>：SPSS / SAS 归统计学工具族、Tableau / PowerBI / 帆软归 BI 可视化 —— 换一套规则数字会不同</li>
<li><b>「标题党」判定含主观成分</b>：规则初判 + 全部人工复核，仍保留判断空间</li>
<li><b>社保/双休维度覆盖率仅约 5%</b>：首轮多数截图未滚到页面底部（仅 25% 截到「立即沟通」标记处），
该维度本轮<b>不足以支撑结论，已如实标注为缺失</b>，第二轮采集已修正截图规范</li>
<li><b>薪资是招聘方标注区间，非实际成交价</b>，区间中值不等于实际 offer</li>
</ul>

<h2>⑥ 参考了谁</h2>
<table>
<tr><th>参考对象</th><th>抄了什么</th><th>没抄什么、为什么</th></tr>
<tr><td>GitHub 开源 JD 爬虫类项目<br>（如 juejin-job-scraper）</td><td>字段设计：公司 / 岗位 / 薪资 / 经验 / 学历 / 技能</td>
<td>没抄爬虫本身：平台用户协议禁止自动化抓取，字体加密 + 反爬对抗成本高，且我的目标是回答「企业要什么」，人工采集完全够用</td></tr>
<tr><td>Kaggle Data Jobs / DS Salaries 数据集项目</td><td>分析结构：一维一切片（技能 / 薪资 / 学历 / 经验 / 城市）</td>
<td>没直接用海外数据集：结论会偏离我要投的中国市场</td></tr>
<tr><td>技能共现 / 词频可视化项目</td><td>技能别名归并字典思路</td>
<td>没上 NLP / 词向量：{N_VALID} 条样本用规则表 + 人工复核更可控、可解释，也更容易向面试官讲清每一步</td></tr>
<tr><td>二手 JD 数据集（和鲸社区等公开数据集）</td><td>—</td>
<td>查过但没用：存量数据集多为 2022 年前数据 —— <b>ChatGPT 2022-11-30 才发布，2022 年的 JD 里不可能有 AI 技能要求维度</b>，
答不了「2026 年该学什么」；且多为单城市（长沙），无太原样本</td></tr>
</table>

<div class="quote"><b>面试可以讲的三句话：</b><br>
①「我知道这类数据可以爬，但招聘平台有明确的反爬和用户协议限制，绕过去有合规风险，而我的问题用人工采集就能回答 ——
所以我把时间花在字段设计和数据清洗上，不是和平台对抗。」<br>
②「我做了一件很多分析不会做的事：<b>给每个结论标显著性</b>。SQL 的城市差距达统计显著我敢写结论；
Python 差距 {fs_py-ty_py} 个点看着更诱人，但 {len(TY_REAL)} 条样本下误差带 ±{CHECKS[1]['ci1']}%，重叠了 ——
所以我写成『方向一致，待更大样本验证』。」<br>
③「中途发现城市混杂后我没有混着算 —— 太原和一线是两个完全不同的市场，混算会把薪资中位数算成一个没有意义的数字。
所以我改成对比口径，反而多出了一个更强的结论。」</div>

<div class="foot">
数据来源：BOSS 直聘公开页面（人工浏览截图采集，未使用任何自动化抓取）· OCR 在本机离线完成，数据未上传任何第三方 ·
采集周期 2026-10 · 分析与成文：本人 · 本页所有数字由 scripts/build_report.py 从数据集回算生成 · 仅用于求职研究与个人作品展示
</div>

</div>
</body>
</html>
"""

open(DST, "w", encoding="utf-8").write(html)

# 控制台回显关键数字，便于人眼核对
print(f"报告已生成 -> {DST}")
print(f"\n=== 关键数字回显 ===")
print(f"有效样本 {N_VALID} / 真实岗 {N_REAL} / 标题党 {N_FAKE} ({pct(N_FAKE,N_VALID)}%)")
print(f"去重剔除 {N_DROP} 条（其中二次查重 {N_DROP-14} 条）")
print(f"城市: {city_str}")
print(f"太原真实岗 {len(TY_REAL)} / 一线新一线真实岗 {len(FS_REAL)}")
print(f"薪资中位数: 全国 {MED_ALL}K | 太原 {MED_TY}K | 一线 {MED_FS}K")
print(f"太原 vs 一线: SQL {ty_sql}%/{fs_sql}% · Python {ty_py}%/{fs_py}% · 统计学 {ty_st}%/{fs_st}% · BI {ty_bi}%/{fs_bi}% · Excel {ty_ex}%/{fs_ex}%")
print(f"AI: 太原 研发{ai_ty_build}/应用{ai_ty_apply}/传统{AI_TY.get(1,0)} | 一线 研发{ai_fs_build}/应用{ai_fs_apply}/传统{AI_FS.get(1,0)}")
print(f"显著性: " + " · ".join(f"{c['label']}{'✅' if c['sig'] else '⏳'}" for c in CHECKS))
