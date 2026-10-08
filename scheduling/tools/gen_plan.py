# -*- coding: utf-8 -*-
import json, io, collections, copy, os

BOX   = r'C:\MAA\data\OperBoxData.json'
INFRA = r'C:\MAA\resource\infrast.json'
TPL   = r'C:\MAA\resource\custom_infrast\333_layout_for_Orundum_3_times_a_day.json'
OUTDIR= r'C:\Users\<user>\Desktop\MAA基建排班'

box = json.load(io.open(BOX, encoding='utf-8'))
opers = [o for o in box['own_opers'] if o.get('own')]
owned = set(o['name'] for o in opers)
id2name = {o['id']: o['name'] for o in opers}
meta = {o['name']: (o.get('rarity',1), o.get('elite',0), o.get('level',1)) for o in opers}
infra = json.load(io.open(INFRA, encoding='utf-8'))

# name -> {productKey: efficiency}
eff = collections.defaultdict(dict)
for room, rd in infra.items():
    if not isinstance(rd, dict): continue
    for sid, s in (rd.get('skills') or {}).items():
        e = s.get('efficient') or {}
        for opid in s.get('operatorIds', []):
            nm = id2name.get(opid)
            if not nm: continue
            for prod, val in e.items():
                if not isinstance(val, (int, float)): continue
                eff[nm][prod] = max(eff[nm].get(prod, -9e9), float(val))

PROD = {'LMD':'Money','Orundum':'SyntheticJade','Pure Gold':'PureGold',
        'Battle Record':'CombatRecord','Originium Shard':'OriginStone','Chip':'Chip'}

def rank(pool, prods):
    """按对给定产品集的最大效率排序（降序）"""
    def sc(nm):
        d = eff.get(nm, {})
        return max([d.get(PROD[p], 0) for p in prods] + [0])
    return sorted(pool, key=lambda n: (sc(n), meta[n][0], meta[n][1]), reverse=True)

def rank_generic(pool, roomkey):
    def sc(nm):
        d = eff.get(nm, {})
        return (d.get('all', 0), max(d.values()) if d else 0, meta[nm][0])
    return sorted(pool, key=lambda n: sc(n), reverse=True)

def split3(lst):
    return [lst[i::3] for i in range(3)]

def build(plan_mode):
    tpl = json.load(io.open(TPL, encoding='utf-8'))
    out = copy.deepcopy(tpl)
    out['author'] = '按你的干员箱自动生成'
    suffix = '搓玉' if plan_mode == 'orundum' else '搓龙门币'
    out['title'] = f"333-{suffix}-3班（依你箱子定制）"
    out['description'] = ("由 MAA 基建技能库 + 你的干员识别结果自动生成，非全局最优；"
                          "缺人处已在你拥有的干员里按效率替补。可自行微调或与自带预设对比。")
    # 产品方案
    if plan_mode == 'orundum':
        trade_prods   = ['LMD', 'LMD', 'Orundum']
        mfg_prods     = ['Pure Gold', 'Pure Gold', 'Originium Shard']
    else:
        trade_prods   = ['LMD', 'LMD', 'LMD']
        mfg_prods     = ['Pure Gold', 'Pure Gold', 'Pure Gold']
    trade_plist = list(dict.fromkeys(trade_prods))
    mfg_plist   = list(dict.fromkeys(mfg_prods))

    # 每类房间的候选池（该房间类型常用的干员 = 有对应技能的）
    def has_trade(n): return any(k in eff.get(n, {}) for k in ('Money','SyntheticJade'))
    def has_mfg(n):   return any(k in eff.get(n, {}) for k in ('CombatRecord','PureGold','OriginStone','Chip'))
    trade_pool = [n for n in owned if has_trade(n)]
    mfg_pool   = [n for n in owned if has_mfg(n)]
    ctrl_pool  = [n for n in owned if 'all' in eff.get(n, {})]
    # 兜底：若某池太小，用全箱子补
    trade_pool = rank(trade_pool, trade_plist)
    mfg_pool   = rank(mfg_pool, mfg_plist)

    trade_g = split3(trade_pool)
    mfg_g   = split3(mfg_pool)

    for si, pl in enumerate(out['plans']):
        used = set()
        # 无人机/菲亚梅塔沿用模板
        # trading
        tgrp = [n for n in trade_g[si] if n not in used]
        rooms = pl['rooms'].get('trading', [])
        for ri, r in enumerate(rooms):
            prod = trade_prods[ri] if ri < len(trade_prods) else 'LMD'
            cap = max(1, len(r.get('operators', [])) or 3)
            pick = sorted(tgrp, key=lambda n: (eff.get(n,{}).get(PROD[prod],0)), reverse=True)[:cap]
            for n in pick:
                tgrp.remove(n); used.add(n)
            r['product'] = prod
            r['operators'] = pick
            r['sort'] = True; r['autofill'] = len(pick) < cap
        # manufacture
        mgrp = [n for n in mfg_g[si] if n not in used]
        rooms = pl['rooms'].get('manufacture', [])
        for ri, r in enumerate(rooms):
            prod = mfg_prods[ri] if ri < len(mfg_prods) else 'Pure Gold'
            cap = max(1, len(r.get('operators', [])) or 3)
            pick = sorted(mgrp, key=lambda n: (eff.get(n,{}).get(PROD[prod],0)), reverse=True)[:cap]
            for n in pick:
                mgrp.remove(n); used.add(n)
            r['product'] = prod
            r['operators'] = pick
            r['sort'] = True; r['autofill'] = len(pick) < cap
        # 其余房间：沿用模板里你拥有的，缺的置空交给 autofill
        for cat in ['power','control','meeting','hire','processing','dormitory']:
            for r in pl['rooms'].get(cat, []):
                kept = [n for n in r.get('operators', []) if n in owned and n not in used]
                for n in kept: used.add(n)
                r['operators'] = kept
                r['autofill'] = True
    return out

os.makedirs(OUTDIR, exist_ok=True)
for mode, fn in [('orundum', '333_搓玉_定制.json'), ('lmd', '333_搓龙门币_定制.json')]:
    data = build(mode)
    p = os.path.join(OUTDIR, fn)
    io.open(p, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))
    print('已生成:', p)
    for pl in data['plans']:
        print(' 班:', pl['name'])
        for cat in ['trading','manufacture','control','power','hire']:
            for ri,r in enumerate(pl['rooms'].get(cat,[])):
                print(f"   {cat:11s}#{ri+1} {r.get('product',''):16s} : {' | '.join(r['operators']) if r['operators'] else '(空)'}")
