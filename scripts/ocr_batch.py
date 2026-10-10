# -*- coding: utf-8 -*-
"""
批量 OCR：把 JD 截图文件夹里的图片全部转成文本。
用法：
  python scripts/ocr_batch.py [图片目录] [输出目录]
默认：
  图片目录 = data/screenshots
  输出目录 = data/ocr_text
输出：
  data/ocr_text/<文件名>.txt   单张文本
  data/ocr_text/_all.txt        全部合并（带分隔标记，供逐条解析）
"""
import os
import sys
import glob
from rapidocr_onnxruntime import RapidOCR

EXTS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp")


def ocr_one(engine, path):
    result, _ = engine(path)
    if not result:
        return ""
    # result: [[box, text, score], ...]，box 为四角坐标
    items = []
    for box, text, score in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), min(xs), text, score))
    # 按行（y）再按列（x）排序，还原阅读顺序
    items.sort(key=lambda t: (round(t[0] / 12), t[1]))
    lines, cur_y, buf = [], None, []
    for y, x, text, score in items:
        if cur_y is None or abs(y - cur_y) <= 12:
            buf.append((x, text))
            cur_y = y if cur_y is None else (cur_y + y) / 2
        else:
            lines.append(" ".join(t for _, t in sorted(buf)))
            buf, cur_y = [(x, text)], y
    if buf:
        lines.append(" ".join(t for _, t in sorted(buf)))
    return "\n".join(lines)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data/screenshots"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/ocr_text"
    os.makedirs(out, exist_ok=True)

    files = []
    for e in EXTS:
        files.extend(glob.glob(os.path.join(src, e)))
        files.extend(glob.glob(os.path.join(src, e.upper())))
    files = sorted(set(files))
    if "--new-only" in sys.argv:
        before = len(files)
        files = [f for f in files
                 if not os.path.exists(os.path.join(out, os.path.splitext(os.path.basename(f))[0] + ".txt"))]
        print(f"[增量模式] 总 {before} 张，已处理 {before - len(files)} 张，待处理 {len(files)} 张")
    if not files:
        print(f"[!] 目录里没有图片: {os.path.abspath(src)}")
        return

    print(f"共 {len(files)} 张，开始识别（CPU 模式，约 2-5 秒/张）...\n")
    engine = RapidOCR()
    all_txt, ok, low = [], 0, []
    for i, f in enumerate(files, 1):
        name = os.path.splitext(os.path.basename(f))[0]
        txt = ocr_one(engine, f)
        with open(os.path.join(out, name + ".txt"), "w", encoding="utf-8") as fp:
            fp.write(txt)
        n = len(txt.strip())
        flag = "OK " if n > 120 else "LOW"
        if n <= 120:
            low.append(name)
        else:
            ok += 1
        print(f"[{i}/{len(files)}] {flag} {name}  ({n} 字符)")
        all_txt.append(f"\n===== [{name}] =====\n{txt}")

    with open(os.path.join(out, "_all.txt"), "w", encoding="utf-8") as fp:
        fp.write("\n".join(all_txt))
    print(f"\n完成：{ok} 张识别正常，{len(low)} 张内容偏少（可能糊/非JD页）")
    if low:
        print("内容偏少的文件：", ", ".join(low[:20]))
    print("合并文本：", os.path.abspath(os.path.join(out, "_all.txt")))


if __name__ == "__main__":
    main()
