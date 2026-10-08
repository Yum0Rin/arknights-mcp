# -*- coding: utf-8 -*-
import json, io

box = json.load(io.open(r'C:\MAA\data\OperBoxData.json', encoding='utf-8'))
owned = {o['name'] for o in box['own_opers'] if o.get('own')}
plan = json.load(io.open(r'C:\MAA\resource\custom_infrast\333_layout_for_Orundum_3_times_a_day.json', encoding='utf-8'))

for pi, pl in enumerate(plan['plans']):
    print(f"\n########## 第{pi+1}班 : {pl.get('name')} ##########")
    d = pl.get('drones', {})
    print(f"  无人机: room={d.get('room')} index={d.get('index')} enable={d.get('enable')}")
    fm = pl.get('Fiammetta', {})
    print(f"  菲亚梅塔: enable={fm.get('enable')} target={fm.get('target')}")
    for cat, rooms in pl['rooms'].items():
        for ri, r in enumerate(rooms):
            ops = r.get('operators', [])
            prod = r.get('product', '')
            marks = [('❌缺' if o not in owned else '  ') + o for o in ops]
            tag = f"[{prod}]" if prod else ""
            if not ops:
                marks = ['(空/自动填)']
            print(f"  {cat:11s} #{ri+1} {tag:16s} autofill={str(r.get('autofill')):5s} : " + ' | '.join(marks))
