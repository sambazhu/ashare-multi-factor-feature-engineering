#!/usr/bin/env python3
"""把 report_data.json 与本地 vendor 脚本（ECharts / Tailwind）注入 HTML 模板，生成离线自包含报告。"""
import json

BASE = "./analysis"

with open(f"{BASE}/report_data.json") as f:
    data = json.load(f)
with open(f"{BASE}/report_template.html") as f:
    html = f.read()
with open(f"{BASE}/vendor/echarts.min.js") as f:
    echarts_js = f.read()
with open(f"{BASE}/vendor/tailwind.js") as f:
    tailwind_js = f.read()

html = html.replace("/*__REPORT_DATA__*/", json.dumps(data, ensure_ascii=False))
html = html.replace('<script src="https://cdn.tailwindcss.com"></script>',
                    "<script>\n" + tailwind_js + "\n</script>")
html = html.replace('<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>',
                    "<script>\n" + echarts_js + "\n</script>")

out = "./docs/因子数据深度分析与迭代建议报告.html"
with open(out, "w") as f:
    f.write(html)
print("saved", out)

# 自检：不允许残留任何外部资源引用
import re
external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
if external:
    raise SystemExit(f"ERROR: 仍有外部引用: {external}")
print("自检通过：无外部 http(s) 资源引用，完全离线自包含")
