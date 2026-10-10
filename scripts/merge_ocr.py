# -*- coding: utf-8 -*-
"""
把 OCR 出来的 154 个 txt，按 JD 归并 + 提取字段。
归并规则（按截图时间顺序）：
  有「薪资 + 职位描述标记」的图 = 某个 JD 的首屏 → 开一个新 JD
  其后连续的、无薪资的图 = 该 JD 的续屏 → 描述拼接进当前 JD
输出：data/out/ocr_jd.json
"""
import os, re, json, glob

SRC = "data/ocr_text"
OUT = "data/out/ocr_jd.json"

CITIES = ["太原","杭州","上海","北京","苏州","南京","深圳","广州","成都","西安","天津","武汉",
          "郑州","重庆","长沙","青岛","济南","合肥","福州","厦门","宁波","无锡","东莞","佛山",
          "石家庄","沈阳","大连","哈尔滨","长春","南昌","昆明","贵阳","南宁","兰州","呼和浩特",
          "乌鲁木齐","海口","常州","温州","泉州","徐州","嘉兴","金华","绍兴","台州","珠海","中山",
          "惠州","烟台","潍坊","洛阳","唐山","保定","廊坊","邯郸","榆林","大同","临汾","运城","晋中"]

EDU = ["学历不限","博士","硕士","本科","大专","中专/中技","中专","中技","高中"]
EXP_PAT = [r"在校/应届", r"在校", r"应届", r"经验不限", r"1年以内", r"1-3年", r"3-5年",
           r"5-10年", r"10年以上", r"\d+年以内", r"\d+-\d+年", r"\d+年以上"]
DETAIL_MARK = ["职位洋情", "职位详情", "职位描述", "岗位职责", "任职要求", "任职资格"]


def norm(s):
    return re.sub(r"\s+", "", s or "")


def clean_lines(t):
    """去掉手机状态栏、地图噪音等无用行"""
    keep = []
    for ln in t.split("\n"):
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^\d{1,2}:\d{2}", s):      # 状态栏时间
            continue
        if re.search(r"\d+G\s*\d+%?$", s) or re.match(r"^\(?\d+\)?$", s):
            continue
        if re.search(r"(小区|花园|大厦|广场|步行街|号楼|酒店|社区|路|街|苑|家园)$", s) and len(s) < 14:
            continue
        keep.append(s)
    return keep


def to_seconds(name):
    m = re.search(r"(\d{4})_?(\d{4})_(\d{6})", name)
    if not m:
        return 0
    a, b, c = m.groups()
    if len(a) == 8:
        y, mo, d = int(a[:4]), int(a[4:6]), int(a[6:])
    else:
        y, mo, d = int(a), int(b[:2]), int(b[2:])
    return ((mo * 31 + d) * 24 + int(c[:2])) * 3600 + int(c[2:4]) * 60 + int(c[4:])


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.txt")))
    files = [f for f in files if os.path.basename(f) != "_all.txt"]
    files.sort(key=lambda f: to_seconds(os.path.basename(f)))

    jds, cur = [], None
    for f in files:
        name = os.path.basename(f)[:-4]
        t = open(f, encoding="utf-8").read()
        n = norm(t)
        has_sal = bool(re.search(r"\d+-\d+K", n) or re.search(r"\d+-\d+元/天", n) or re.search(r"\d+元/天", n))
        has_det = any(k in n for k in DETAIL_MARK)
        if has_sal and has_det:
            cur = {"files": [name], "raw": t}
            jds.append(cur)
        elif cur is not None:
            cur["files"].append(name)
            cur["raw"] += "\n" + t
        else:
            # 开头几张没有首屏（续屏在前），单独成条
            cur = {"files": [name], "raw": t}
            jds.append(cur)

    print(f"归并后 JD 条数: {len(jds)}")

    out = []
    for i, jd in enumerate(jds, 1):
        raw = jd["raw"]
        n = norm(raw)
        # --- 城市 ---
        city = None
        for c in CITIES:
            if re.search(re.escape(c) + r"[·・]", n):
                city = c
                break
        if not city:
            m = re.search(r"([\u4e00-\u9fa5]{2,4})[·・][\u4e00-\u9fa5]{1,8}[市区县]", n)
            city = m.group(1) if m else None
        # --- 薪资 ---
        salary = None
        m = re.search(r"(\d+)-(\d+)K(?:·(\d+)薪)?", n)
        if m:
            salary = f"{m.group(1)}-{m.group(2)}K" + (f"·{m.group(3)}薪" if m.group(3) else "")
        if not salary:
            m = re.search(r"(\d+)-(\d+)元/天", n)
            if m:
                salary = f"{m.group(1)}-{m.group(2)}元/天"
        if not salary:
            m = re.search(r"(\d+)元/天", n)
            if m:
                salary = f"{m.group(1)}元/天"
        if not salary and "面议" in n:
            salary = "面议"
        # --- 学历 ---
        edu = None
        best = 10 ** 9
        for e in EDU:
            p = n.find(e)
            if p >= 0 and p < best:
                best, edu = p, e
        # --- 经验 ---
        exp = None
        best = 10 ** 9
        for pat in EXP_PAT:
            m = re.search(pat, n)
            if m and m.start() < best:
                best, exp = m.start(), m.group(0)
        # --- 公司（全称优先）---
        company = None
        m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{3,25}(?:有限公司|股份有限公司|集团有限公司|银行|研究院|事务所))", n)
        if m:
            company = m.group(1)
        if not company:
            m = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,20})[·・](?:HR|HRBP|人事|招聘者|经理|主管|总监)", raw)
            if m:
                company = m.group(1).strip()
        # --- 岗位名：含「数据/分析/运营/BI」的短行 ---
        title = None
        for ln in clean_lines(raw)[:14]:
            s = ln.strip()
            if 3 <= len(s) <= 14 and re.search(r"(数据分析|数据|分析师|运营|BI|商业分析|经营分析|数据开发|挖掘)", s):
                if "职位描述" in s or "职位详情" in s:
                    continue
                title = s
                break
        # --- 正文（去掉噪音行）---
        body = "\n".join(clean_lines(raw))
        out.append({
            "id": f"OCR{i:03d}",
            "files": jd["files"],
            "title": title or "",
            "company": company or "",
            "city": city or "",
            "salary": salary or "",
            "experience": exp or "",
            "education": edu or "",
            "desc": body,
        })

    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    import collections
    print("城市:", dict(collections.Counter(r["city"] for r in out).most_common()))
    print("有薪资:", sum(1 for r in out if r["salary"]), "| 有学历:", sum(1 for r in out if r["education"]),
          "| 有经验:", sum(1 for r in out if r["experience"]), "| 有公司:", sum(1 for r in out if r["company"]),
          "| 有岗位名:", sum(1 for r in out if r["title"]))
    print("已保存:", OUT)


if __name__ == "__main__":
    main()
