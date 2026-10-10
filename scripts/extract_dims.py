# -*- coding: utf-8 -*-
"""
JD 多维提取器 v3 —— 把一条 JD 的正文文本，抽成 11 个分析维度
用法: python scripts/extract_dims.py
输入: data/jd_dataset.json （须含 desc 字段）
输出: data/jd_dataset_v3.json / .csv  + data/dim_coverage.txt（各维度命中率）

设计原则：
1) OCR 文本噪声大，每个维度都要标注「提取置信度」，不做假装精确的判断
2) 关键词命中即记，宁可漏不可错判（尤其 AI 维度分两级）
3) 所有维度可复算：只看 desc + 结构化字段，不依赖任何人工标注的中间态
"""
import os
import re
import json
import csv
import collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- 地区三级分类 ----------
TIER1 = {"北京", "上海", "广州", "深圳"}
NEW_TIER1 = {"成都", "杭州", "重庆", "西安", "苏州", "武汉", "南京", "天津", "郑州",
             "长沙", "东莞", "佛山", "宁波", "青岛", "沈阳", "合肥", "大连", "无锡",
             "厦门", "福州", "济南", "哈尔滨", "长春", "昆明", "南宁", "石家庄"}


# ---------- 已知重复：(保留 id, 剔除 id, 依据) ----------
# 第二轮查重发现（4-gram Jaccard + 人工核验：公司/薪资/城市/经验/学历五字段全同）
DUPS = [
    ("OCR019", "OCR032", "同岗：太原 7-8K 硕士 特玛茹·数据分析师"),
    ("OCR076", "OCR099", "同岗：杭州 12-18K 高帆破浪科技·数据分析实习"),
    ("OCR002", "OCR045", "同岗：太原 2-3K 筑龙·数据分析实习生"),
    ("OCR078", "OCR100", "同岗：杭州 13-16K 银科思成·数据分析师"),
    ("OCR014", "OCR046", "同岗：太原 2-4K 太原公能科技·数据处理实习生"),
    ("OLD30", "OCR025", "同岗：太原 6-8K 山西启恩玄科技，手打版与 OCR 版重复"),
]
DUP_DROP = {d[1] for d in DUPS}


# OCR 城市名错字修正表
# BOSS 页面城市字段经 OCR 后系统性错识，用「XX·YY区」地址线索反查确认：
#   荔州 → 苏州（地址命中 姑荔区=姑苏区 / 虎丘区 / 吴中区 / 相城区 / 荔州工业园区）
#   充锡 → 无锡（地址命中 锡山区 / 梁溪区 / 惠山区）
#   深训 / 浑圳 → 深圳
# 前缀粘连（"新荔州""程师充锡""析师荔州"）是岗位名被并进了城市字段
CITY_FIX = {
    "荔州": "苏州", "新荔州": "苏州", "析师荔州": "苏州", "大数据荔州": "苏州",
    "充锡": "无锡", "新充锡": "无锡", "程师充锡": "无锡", "析师充锡": "无锡",
    "专员充锡": "无锡", "数据分充锡": "无锡",
    "深训": "深圳", "浑圳": "深圳", "新浑圳": "深圳",
}
CITY_FIX_SUFFIX = (("荔州", "苏州"), ("充锡", "无锡"), ("浑圳", "深圳"), ("深训", "深圳"))


def fix_city(c):
    """修正 OCR 错识的城市名；返回 None/空 则原样返回"""
    if not c:
        return c
    c = c.strip()
    if c in CITY_FIX:
        return CITY_FIX[c]
    for suf, real in CITY_FIX_SUFFIX:
        if c.endswith(suf):
            return real
    return c


def city_tier(city):
    city = fix_city(city)
    if not city:
        return "未知"
    if city == "太原":
        return "太原"
    if city in TIER1:
        return "一线"
    if city in NEW_TIER1:
        return "新一线"
    return "其他二线"


def city_group(city):
    """三级分组：太原 / 一线新一线 / 其他二线"""
    t = city_tier(fix_city(city))
    if t == "太原":
        return "太原"
    if t in ("一线", "新一线"):
        return "一线新一线"
    if t == "其他二线":
        return "其他二线"
    return "未知"


# ---------- ① 岗位方向细分 ----------
# 顺序即优先级，先命中者为准
DIRECTION_RULES = [
    ("算法/机器学习", ["算法工程师", "机器学习", "深度学习", "算法", "数据挖掘工程师"]),
    ("BI/数仓/数据治理", ["bi工程师", "bi开发", "数据仓库", "数仓", "数据治理", "数据开发", "etl工程师"]),
    ("商业/经营分析", ["商业分析", "经营分析", "战略分析", "战略", "咨询顾问", "行业分析"]),
    ("数据运营", ["数据运营", "用户运营", "产品运营", "运营专员", "活动运营", "用户画像"]),
    ("风控/财务分析", ["风控", "风险", "财务分析", "信贷", "反欺诈"]),
    ("实习生", ["实习"]),
    ("专员/助理", ["专员", "助理"]),
    ("分析师(通用)", ["分析师", "数据分析"]),
]


def extract_direction(title, desc):
    hay = (title + " " + desc[:400]).lower()
    for name, kws in DIRECTION_RULES:
        for k in kws:
            if k.lower() in hay:
                return name
    return "未分类"


# ---------- ② 可否应届/在校 ----------
FRESH_YES = ["应届毕业生", "应届生", "在校/应届", "在校生", "26届", "27届", "2026届", "2027届",
             "实习生", "校招", "校园招聘", "无经验要求", "经验不限"]
FRESH_NO = ["3-5年", "5-10年", "10年以上"]


def extract_fresh(exp, edu, desc):
    """返回 2=明确可应届 / 1=经验不限(可能可) / 0=明确需经验 / -1=未知"""
    hay = f"{exp} {edu} {desc[:600]}"
    if any(k in hay for k in FRESH_YES):
        return 2
    if any(k in hay for k in FRESH_NO):
        return 0
    if "经验不限" in hay or "1年以内" in hay or "1-3年" in hay:
        return 1
    return -1


# ---------- ④ AI 相关要求（三级，必须分层，否则结论会错） ----------
# L3 AI研发层：懂原理/能搭 —— 这是真正的门槛，也是薪资分水岭
AI_BUILD = ["rag", "微调", "llm/agent", "llm、agent", "agent开发", "ai agent", "智能体开发",
            "搭建知识库", "知识库、智能体", "大模型训练", "模型微调", "pytorch", "tensorflow",
            "transformer", "深度学习", "大模型训练数据", "fine-tuning", "prompt工程"]
# L2 AI应用层：会用AI工具提效 —— 门槛低，正在快速变成默认要求
AI_APPLY = ["大模型工具", "ai工具", "使用大模型", "ai辅助", "ai分析", "ai分析能力",
            "ai skill", "gpt、copilot", "copilot", "自动问数", "ai翻译", "ai视频",
            "大模型辅助", "主流ai", "ai及大模型"]
# L1 传统机器学习/统计建模 —— 2020 年前就有，不算「AI 要求」
AI_CLASSIC = ["机器学习", "聚类", "决策树", "xgboost", "lightgbm", "特征工程", "预测模型",
              "推荐算法", "scikit", "sklearn", "回归模型", "分类算法"]
AI_SOFT = ["人工智能", " ai ", "chatgpt", "文心", "通义", "智谱", "豆包", "kimi"]
# OCR 噪声排除：这些上下文里的「大模型」不是真的大模型
AI_NOISE = ["大气污染模式", "数值大模型", "解大模型应", "大模型应、", "模式、解大模型"]


def extract_ai(desc, skills):
    """返回 (等级, 命中词列表)
    等级: 3=AI研发层 / 2=AI应用层 / 1=传统机器学习 / 0=无
    先剔除 OCR 噪声上下文，再分级；同级取最高。"""
    low = " " + desc.lower() + " "
    # 噪声屏蔽：把误命中的上下文整句遮掉
    for junk in AI_NOISE:
        low = low.replace(junk, "〔噪〕")

    build = [k for k in AI_BUILD if k in low]
    apply_ = [k for k in AI_APPLY if k in low]
    classic = [k for k in AI_CLASSIC if k in low]
    soft = [k for k in AI_SOFT if k in low]

    if build:
        return 3, build
    if apply_:
        return 2, apply_
    if classic:
        return 1, classic
    if soft:
        return 1, soft
    return 0, []


# ---------- ⑤ 公司类型（规模 + 行业） ----------
SIZE_RE = re.compile(r"(\d{1,3}\s*-\s*\d{1,5}\s*人|\d{1,5}\s*人以上|0\s*-\s*\d{1,3}\s*人)")
FIN_RE = re.compile(r"(不需要融资|不需要融资|已上市|D轮及以上|C轮|B轮|A轮|天使轮|未融资)")

SIZE_ORDER = ["0-20人", "20-99人", "100-499人", "500-999人", "1000-9999人", "10000人以上"]


def extract_company(desc):
    m = SIZE_RE.search(desc)
    size = m.group(1).replace(" ", "") if m else ""
    f = FIN_RE.search(desc)
    return size, (f.group(1) if f else "")


# ---------- ⑦ 作息 / ⑧ 福利 ----------
REST_YES = ["双休", "周末双休", "上五休二", "做五休二", "大小周", "单双休"]
REST_NO = ["单休", "上六休一", "六天工作制", "月休", "排班"]
OT_YES = ["不加班", "无需加班", "弹性工作", "朝九晚五", "弹性工时"]
OT_NO = ["能适应加班", "接受加班", "加班", "出差", "抗压"]
INSURE = ["五险一金", "六险一金", "六险二金", "五险", "社保", "公积金"]
WELFARE = ["包住", "包吃", "餐补", "饭补", "交通补助", "通讯补贴", "年终奖", "13薪", "14薪",
           "15薪", "16薪", "定期体检", "员工旅游", "团建", "带薪年假", "节日福利", "免费班车"]
OUTSOURCE = ["外包", "派遣", "劳务派遣", "驻场", "人力外包", "项目外包"]


def hit(text, keys):
    low = " " + text.lower() + " "
    return [k for k in keys if k in low or k in text]


def main():
    src = os.path.join(BASE, "data", "jd_dataset.json")
    rows = json.load(open(src, encoding="utf-8"))
    print(f"读入 {len(rows)} 条")

    out = []
    for r in rows:
        desc = r.get("desc", "") or ""
        title = r.get("title", "") or ""
        city = r.get("city", "") or ""
        exp = r.get("experience", "") or ""
        edu = r.get("education", "") or ""

        grp = city_group(city)
        direction = extract_direction(title, desc)
        fresh = extract_fresh(exp, edu, desc)
        ai_lv, ai_kw = extract_ai(desc, r.get("skills", ""))
        size, financing = extract_company(desc)

        rest = hit(desc, REST_YES)
        rest_no = hit(desc, REST_NO)
        ot_ok = hit(desc, OT_YES)
        ot_bad = hit(desc, OT_NO)
        ins = hit(desc, INSURE)
        wel = hit(desc, WELFARE)
        outsrc = hit(desc, OUTSOURCE)

        # 采集日期：从截图文件名推断（Screenshot_20261010_xxx → 2026-10-10），
        # 推断不出才回落到 2026-10-09。跨批次采集后不能再写死单日。
        cdate = r.get("collect_date") or ""
        if not cdate:
            _m = re.search(r"(20\d{6})", "|".join(r.get("files", []) or []))
            if _m:
                s8 = _m.group(1)
                cdate = "%s-%s-%s" % (s8[:4], s8[4:6], s8[6:])
            else:
                cdate = "2026-10-09"

        stub = {
            **r,
            "dup_of": "" if r["id"] not in DUP_DROP else next(k for k, v, _ in DUPS if v == r["id"]),
            "is_valid": 0 if r["id"] in DUP_DROP else 1,
            "city": fix_city(r.get("city", "")),
            "city_group": grp,
            "city_tier": city_tier(city),
            "direction": direction,
            "fresh_ok": fresh,
            "ai_level": ai_lv,
            "ai_keywords": "|".join(ai_kw[:6]),
            "company_size": size,
            "company_financing": financing,
            "rest_double_off": 1 if (rest and not rest_no) else (0 if rest_no and not rest else -1),
            "rest_keywords": "|".join((rest + rest_no)[:4]),
            "ot_keywords": "|".join((ot_ok + ot_bad)[:4]),
            "insurance": "|".join(ins[:3]),
            "welfare": "|".join(wel[:5]),
            "outsourced": 1 if outsrc else 0,
            "outsourced_kw": "|".join(outsrc[:2]),
            "collect_date": cdate,
            "applied": r.get("applied", ""),      # ③ 投递：留给后续填写
            "got_reply": r.get("got_reply", ""),  # ③ 结果：留给后续填写
        }
        out.append(stub)

    # 覆盖率自检
    cov = collections.OrderedDict()
    keys = ["city_group", "direction", "fresh_ok", "ai_level", "company_size",
            "company_financing", "rest_double_off", "insurance", "welfare", "outsourced"]
    for k in keys:
        valid = 0
        for r in out:
            v = r.get(k)
            if isinstance(v, str):
                if v.strip():
                    valid += 1
            elif isinstance(v, int):
                if v != -1 and v != 0 or k in ("outsourced", "ai_level"):
                    if v != -1:
                        valid += 1
            elif v:
                valid += 1
        cov[k] = valid

    dst_json = os.path.join(BASE, "data", "jd_dataset_v3.json")
    json.dump(out, open(dst_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    cols = []
    for r in out:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    dst_csv = os.path.join(BASE, "data", "jd_dataset_v3.csv")
    with open(dst_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, "") for k in cols})

    cov_txt = os.path.join(BASE, "data", "dim_coverage.txt")
    with open(cov_txt, "w", encoding="utf-8") as f:
        f.write("维度\t有效条数\t覆盖率\t说明\n")
        notes = {
            "city_group": "地区三级分组",
            "direction": "①岗位方向细分",
            "fresh_ok": "②可否应届 2明确可/1可能/0需经验(-1未知)",
            "ai_level": "④AI要求 3研发/2应用/1传统ML/0无",
            "company_size": "⑤公司规模",
            "company_financing": "⑤融资阶段",
            "rest_double_off": "⑦双休 1是/0否(-1未提及)",
            "insurance": "⑧社保",
            "welfare": "⑧福利",
            "outsourced": "⑧是否外包",
        }
        for k, v in cov.items():
            f.write(f"{k}\t{v}\t{v/len(out)*100:.1f}%\t{notes.get(k,'')}\n")

    print(f"已输出 {len(out)} 条 -> {dst_json}")
    print(f"                    -> {dst_csv}")
    print("\n=== 各维度提取覆盖率 ===")
    for k, v in cov.items():
        print(f"  {k:20} {v:>4}/{len(out)}  ({v/len(out)*100:5.1f}%)  {notes.get(k,'')}")


if __name__ == "__main__":
    main()
