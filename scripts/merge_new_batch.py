# -*- coding: utf-8 -*-
"""
增量合并：把新一批 OCR 归并出的 JD 并入主数据集。

流程：
  data/out/ocr_jd.json  （merge_ocr.py 对【全部】ocr_text 的归并结果）
    → 剔除明显非 JD 的噪声记录
    → 与 data/jd_dataset.json 现有记录做查重（公司+薪资 强匹配 / 正文 4-gram Jaccard）
    → 新增的记录分配新 id，追加进主数据集

用法：
  python scripts/merge_new_batch.py            # 试运行，只打印统计
  python scripts/merge_new_batch.py --write    # 真正写入 data/jd_dataset.json
"""
import os, re, sys, json, glob, shutil, collections
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEW_JSON = os.path.join(BASE, "data", "out", "ocr_jd.json")
MAIN_JSON = os.path.join(BASE, "data", "jd_dataset.json")
OCR_DIR = os.path.join(BASE, "data", "ocr_text")

# ---------------------------------------------------------------- 噪声过滤
# 教训：不能用「页面上有『发现』『微信』『BOSS直聘』」判噪声 —— BOSS 的 JD 页
# 底部本来就有这些导航/来源文字，第一轮误杀了 22 条真 JD（含拼多多 30-60K）。
# 改用更强判据：【有薪资 = 一定是 JD】。薪资格式只可能出现在招聘页。
SALARY_PAT = re.compile(r"\d+\s*[-~]\s*\d+\s*[Kk千万]|\d+\s*[Kk](?![A-Za-z])|\d+\s*-\s*\d+\s*元|元/天|元/月")

# 仅在【无薪资】时才启用的噪声特征（英语口语 App、手机桌面等真非 JD 页面）
NOISE_HINT = ["流利度", "发音", "视频讲解", "弱读", "洋分洋情", "AI语音"]

MIN_DESC = 60           # desc 太短说明没截到正文


def is_noise(rec):
    d = rec.get("desc", "") or ""
    # ① 有薪资 → 铁定是 JD，直接放行（这是最关键的一条修正）
    if SALARY_PAT.search(d):
        return None
    # ② 无薪资：才走噪声/残缺判断
    if len(d) < MIN_DESC:
        return "正文过短(%d字)" % len(d)
    for n in NOISE_HINT:
        if n in d[:300]:
            return "疑似非JD页面(命中「%s」)" % n
    hit = sum(1 for k in ("city", "salary", "title", "company") if (rec.get(k) or "").strip())
    if hit < 2:
        return "字段不足(仅%d项)" % hit
    return None


# ---------------------------------------------------------------- 查重
def norm_txt(t):
    t = re.sub(r"[^一-鿿A-Za-z0-9]", "", t or "")
    return set(t[i:i + 4] for i in range(0, max(1, len(t) - 3)))


def jaccard(a, b):
    A, B = norm_txt(a), norm_txt(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def core_name(c):
    """公司名核心：去掉省市前缀与常见后缀，便于跨批次比对"""
    c = re.sub(r"[（(].*?[)）]", "", c or "")
    c = re.sub(r"(有限公司|股份有限公司|有限责任公司|分公司|科技|技术|集团|公司)$", "", c.strip())
    return re.sub(r"[^一-鿿A-Za-z0-9]", "", c)


def find_dup(rec, main_rows):
    """返回 (命中记录id, 原因) 或 (None, None)"""
    rc, rs = core_name(rec.get("company", "")), (rec.get("salary") or "").strip()
    for m in main_rows:
        # 强匹配：公司核心名相同 且 薪资相同
        if rc and rs and core_name(m.get("company", "")) == rc and (m.get("salary") or "").strip() == rs:
            return m["id"], "公司+薪资相同"
        # 弱匹配：正文高度相似
        s = jaccard(rec.get("desc", ""), m.get("desc", ""))
        if s >= 0.70:
            return m["id"], "正文相似 %.2f" % s
    return None, None


def main():
    write = "--write" in sys.argv

    new = json.load(open(NEW_JSON, encoding="utf-8"))
    main_rows = json.load(open(MAIN_JSON, encoding="utf-8"))
    known_files = set()
    for r in main_rows:
        known_files.update(r.get("files", []) or [])

    print("归并结果 %d 条；主数据集现有 %d 条" % (len(new), len(main_rows)))

    # ---- 1) 拆分：已入库 / 噪声 / 候选新增 ----
    already, noise, cand = [], [], []
    for r in new:
        fs = set(r.get("files", []) or [])
        if fs and fs <= known_files:
            already.append(r)
            continue
        why = is_noise(r)
        if why:
            noise.append((r, why))
            continue
        cand.append(r)

    print("  已入库（旧批次）: %d" % len(already))
    print("  噪声剔除        : %d" % len(noise))
    print("  候选新增        : %d" % len(cand))

    # ---- 2) 候选内部先自去重（同一次采集可能重复截了同一岗位）----
    uniq, inner_dup = [], []
    for r in cand:
        d, why = find_dup(r, uniq)
        if d:
            inner_dup.append((r, d, why))
        else:
            uniq.append(r)
    print("  候选内部去重剔除: %d" % len(inner_dup))

    # ---- 3) 与主数据集查重 ----
    add, cross_dup = [], []
    for r in uniq:
        d, why = find_dup(r, main_rows)
        if d:
            cross_dup.append((r, d, why))
        else:
            add.append(r)
    print("  与主库重复剔除  : %d" % len(cross_dup))
    print("  ★ 实际新增      : %d" % len(add))

    # ---- 4) 展示明细（便于人工核验）----
    if inner_dup or cross_dup:
        print("\n=== 去重明细（前 20 条）===")
        for r, d, why in (inner_dup + cross_dup)[:20]:
            print("  剔除 %s → %s  [%s]  %s | %s"
                  % (r.get("id"), d, why, (r.get("company") or "")[:16], (r.get("salary") or "")))
    if noise:
        print("\n=== 噪声明细（前 10 条）===")
        for r, why in noise[:10]:
            print("  剔除 %s  [%s]  desc: %s"
                  % (r.get("id"), why, (r.get("desc") or "").replace("\n", " ")[:50]))

    print("\n=== 新增记录预览（前 8 条）===")
    for r in add[:8]:
        print("  %s | %-8s | %-12s | %-16s | %s"
              % ((r.get("city") or "?")[:6], (r.get("salary") or "?")[:8],
                 (r.get("title") or "?")[:12], (r.get("company") or "?")[:16],
                 len(r.get("desc") or "")))

    # 城市分布
    print("\n=== 新增记录城市分布 ===")
    for k, v in collections.Counter((r.get("city") or "未识别") for r in add).most_common(12):
        print("  %-10s %d" % (k, v))

    if not write:
        print("\n[试运行] 未写入。确认无误后加 --write 执行。")
        return

    # ---- 5) 写回 ----
    if os.path.exists(MAIN_JSON):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = os.path.join(BASE, "data", "intermediate", "jd_dataset_backup_%s.json" % ts)
        shutil.copy2(MAIN_JSON, bak)
        print("\n已备份原数据集 → %s" % os.path.relpath(bak, BASE))

    # 分配新 id：延续 OCR### 编号。
    # 教训：必须在【每次分配后】重新检查 used —— 只查一次起点会从 OCR001 重编，
    # 与旧批次 103 条全部撞号（第一轮就踩了这个坑，导致 334 条里 103 个重复 id）。
    used = {r["id"] for r in main_rows}
    nxt = 1

    def next_id():
        nonlocal nxt
        while ("OCR%03d" % nxt) in used:
            nxt += 1
        got = "OCR%03d" % nxt
        used.add(got)
        nxt += 1
        return got

    # 补字段：skills / flag / flag_type —— merge_ocr.py 不产出这些，
    # 必须在这里用 parse_jd.py 的统一规则补齐，否则新增记录混进主库后会
    # 稀释技能占比与标题党比例（第一轮就因此把标题党率从 13% 冲淡到 5.3%）。
    import importlib.util
    _sp = importlib.util.spec_from_file_location(
        "pj", os.path.join(BASE, "scripts", "parse_jd.py"))
    pj = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(pj)

    for r in add:
        r["id"] = next_id()
        r["source"] = "ocr"
        if not (r.get("skills") or "").strip():
            r["skills"] = "|".join(pj.parse_skills(r.get("desc", "") or ""))
        if r.get("flag") is None:
            fl, why = pj.is_title_only(r.get("desc", "") or "",
                                       (r.get("skills") or "").split("|"))
            r["flag"] = bool(fl)
            r["reason"] = why or r.get("reason", "")

    merged = main_rows + add
    json.dump(merged, open(MAIN_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写入 %s：%d → %d 条（新增 %d）"
          % (os.path.relpath(MAIN_JSON, BASE), len(main_rows), len(merged), len(add)))
    print("下一步：python scripts/extract_dims.py && python scripts/build_report.py")


if __name__ == "__main__":
    main()
