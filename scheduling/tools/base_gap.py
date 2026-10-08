# -*- coding: utf-8 -*-
import json, io, collections

box = json.load(io.open(r'C:\MAA\data\OperBoxData.json', encoding='utf-8'))
ops = box.get('own_opers', [])
owned = {o['name']: o for o in ops if o.get('own')}
print('识别到拥有干员数:', len(owned))
print('done:', box.get('done'))

plan = json.load(io.open(r'C:\MAA\resource\custom_infrast\333_layout_for_Orundum_3_times_a_day.json', encoding='utf-8'))
print('\n=== 模板计划 ===')
print('title    :', plan.get('title'))
print('planTimes:', plan.get('planTimes'))
print('plans    :', [p.get('name') for p in plan['plans']])

# 房间结构
p0 = plan['plans'][0]
print('\n=== 房间结构（第1班）===')
for cat, rooms in p0['rooms'].items():
    prods = []
    for r in rooms:
        if 'product' in r: prods.append(r['product'])
    print(f'  {cat:14s}: {len(rooms)} 间  {("产品:" + ",".join(sorted(set(prods)))) if prods else ""}')

# 引用到的干员
ref = collections.defaultdict(set)
refcount = collections.Counter()
for pl in plan['plans']:
    for cat, rooms in pl['rooms'].items():
        for r in rooms:
            for op in r.get('operators', []):
                ref[op].add(cat)
                refcount[op] += 1

present = sorted(n for n in ref if n in owned)
missing = sorted(n for n in ref if n not in owned)
print('\n=== 干员对账 ===')
print('模板引用干员总数:', len(ref))
print('你拥有           :', len(present))
print('你缺失           :', len(missing))
print('\n缺失名单:')
print('、'.join(missing))
print('\n拥有名单:')
print('、'.join(present))

# 按稀有度列出箱子（方便挑替补）
print('\n=== 你拥有的 6星干员 ===')
six = sorted([o for o in owned.values() if o['rarity']==6], key=lambda x:(-x.get('elite',0),-x.get('level',0)))
print('、'.join(f"{o['name']}(E{o.get('elite',0)}L{o.get('level',0)})" for o in six))
