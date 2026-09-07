import json
import os

data_dir = '/data1/wkzq/ashare/data'
basic_path = os.path.join(data_dir, 'stock_basic_index.json')
with open(basic_path, 'r', encoding='utf-8') as f:
    basic = json.load(f)

latest_path = os.path.join(data_dir, 'data_2026-09-01.json')
with open(latest_path, 'r', encoding='utf-8') as f:
    daily = json.load(f)

updated_count = 0
for s in daily:
    code = s.get('code')
    if code in basic and basic[code].get('n'):
        s['name'] = basic[code]['n']
        updated_count += 1

with open(latest_path, 'w', encoding='utf-8') as f:
    json.dump(daily, f, ensure_ascii=False)

print(f"Updated {updated_count} stock names in data_2026-09-01.json!")
