# -*- coding: utf-8 -*-
"""生成独立HTML文件"""
import json
import os

# 读取精简数据
print("读取数据...")
with open('data/slim_2026-03-06.json', 'r', encoding='utf-8') as f:
    data1 = json.load(f)

with open('data/slim_2025-01-02.json', 'r', encoding='utf-8') as f:
    data2 = json.load(f)

print(f"2026-03-06: 普通债{len(data1.get('normal', []))}个, 永续债{len(data1.get('perpetual', []))}个")
print(f"2025-01-02: 普通债{len(data2.get('normal', []))}个, 永续债{len(data2.get('perpetual', []))}个")

# 读取HTML模板
with open('yield_curve_template.html', 'r', encoding='utf-8') as f:
    html_template = f.read()

# 数据转为JSON（格式化输出，便于浏览器解析）
data_json = json.dumps({
    "2026-03-06": data1,
    "2025-01-02": data2
}, ensure_ascii=False, indent=None, separators=(',', ':'))

# 替换占位符
html_content = html_template.replace('__DATA__', data_json)

# 保存
output_path = 'data/期限结构曲线查询.html'
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(html_content)

file_size = os.path.getsize(output_path) / 1024 / 1024
print(f"\n文件已生成: {output_path}")
print(f"文件大小: {file_size:.1f} MB")
print("\n直接用浏览器打开即可使用！")