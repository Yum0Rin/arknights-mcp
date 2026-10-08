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
meta = {o['name']: (o.get('rarity',1), o.get('elite',0)) for o in opers}
infra = json.load(io.open(INFRA, encoding='utf-8'))

# eff[room][name][product] = 效率值（含 skills 与 skillsGroup）
eff = collections.defaultdict(lambda: collections.defaultdict(dict))
for room, rd in infra.items():
    if not isinstance(rd, dict): continue
    R = eff[room]
    skills = rd.get('skills') or {}
    def add(nm, e):
        if not nm: return
        d = R[nm]
        for p, v in e.items():
            if isinstance(v, (int, float)): d[p] = max(d.get(p, -9e9), float(v))
    for sid, s in skills.items():
        ops_here = [id2name.get(x) for x in s.get('operatorIds', [])]
        for nm in ops_here: add(nm, s.get('efficient') or {})
    for g in rd.get('skillsGroup') or []:
        for item in g.get('necessary', []):
            e = item.get('efficient') or {}
            seen = set()
            for sid in item.get('skills', []):
                for opid in (skills.get(sid, {}) or {}).get('operatorIds', []):
                    seen.add(id2name.get(opid))
            for nm in seen: add(nm, e)
        for item in g.get('optional', []):
            e = item.get('efficient') or {}
            for nm in item.get('filter', []):
                if nm in owned: add(nm, e)

PROD = {'LMD':'Money','Orundum':'SyntheticJade','Pure Gold':'PureGold',
        'Battle Record':'CombatRecord','Originium Shard':'OriginStone','Chip':'Chip'}
ROOMK = {'trading':'Trade','manufacture':'Mfg','power':'Power','control':'Control',
         'meeting':'Reception','hire':'Office','processing':'Processing','dormitory':'Dorm'}

def pools(roomk):
    return [n for n in owned if n in eff.get(roomk, {})]

def score(roomk, nm, prod):
    d = eff.get(roomk, {}).get(nm, {})
    pk = PROD.get(prod, prod) if prod else None
    vals = [d.get('all', 0)]
    if pk: vals.append(d.get(pk, 0))
    return max(vals)

def build(mode):
    tpl = json.load(io.open(TPL, encoding='utf-8'))
    out = copy.deepcopy(tpl)
    suffix = '搓玉' if mode == 'orundum' else '搓龙门币'
    out['author'] = '按你的干员箱自动生成'
    out['title'] = f"333-{suffix}-3班（依你箱子定制）"
    out['description'] = ('基于 MAA 基建技能库 + 你的干员识别结果生成：保留原排班中你已有的人，'
                          '空缺按同类效率在你箱子里轮换替补。非全局最优，可自行微调。')
    if mode == 'orundum':
        trade_prods = ['LMD', 'LMD', 'Orundum']
        mfg_prods   = ['Pure Gold', 'Pure Gold', 'Originium Shard']
    else:
        trade_prods = ['LMD', 'LMD', 'LMD']
        mfg_prods   = ['Pure Gold', 'Pure Gold', 'Pure Gold']

    gpools = {k: pools(k) for k in ['Trade','Mfg','Power','Control','Reception','Office','Processing','Dorm']}
    gcount = collections.Counter()       # 跨班使用次数（用于轮换）

    def fill_room(roomk, prod, tmpl_ops, cap, used_this):
        keep = [n for n in tmpl_ops if n in owned and n not in used_this]
        need = cap - len(keep)
        if need > 0:
            cand = [n for n in gpools[roomk] if n not in used_this and n not in keep]
            r = score
            cand.sort(key=lambda n: (gcount[n], -r(roomk, n, prod), -meta[n][0]))
            fill = cand[:need]
        else:
            fill = []
        ops = keep + fill
        for n in ops:
            used_this.add(n); gcount[n] += 1
        return ops

    for pl in out['plans']:
        used_this = set()
        for ri, r in enumerate(pl['rooms'].get('trading', [])):
            prod = trade_prods[ri] if ri < len(trade_prods) else 'LMD'
            cap = max(1, len(r.get('operators', [])) or 3)
            ops = fill_room('Trade', prod, r.get('operators', []), cap, used_this)
            r['product'] = prod; r['operators'] = ops; r['sort'] = True; r['autofill'] = len(ops) < cap
        for ri, r in enumerate(pl['rooms'].get('manufacture', [])):
            prod = mfg_prods[ri] if ri < len(mfg_prods) else 'Pure Gold'
            cap = max(1, len(r.get('operators', [])) or 3)
            ops = fill_room('Mfg', prod, r.get('operators', []), cap, used_this)
            r['product'] = prod; r['operators'] = ops; r['sort'] = True; r['autofill'] = len(ops) < cap
        # 其它房间：各自容量
        caps = {'power':1, 'control':5, 'meeting':2, 'hire':1, 'processing':1}
        for cat, cap in caps.items():
            for r in pl['rooms'].get(cat, []):
                rk = ROOMK[cat]
                ops = fill_room(rk, None, r.get('operators', []), cap, used_this)
                r['operators'] = ops; r['autofill'] = len(ops) < cap
        for r in pl['rooms'].get('dormitory', []):
            keep = [n for n in r.get('operators', []) if n in owned and n not in used_this]
            for n in keep: used_this.add(n)
            r['operators'] = keep; r['autofill'] = True
    return out

os.makedirs(OUTDIR, exist_ok=True)
for mode, fn in [('orundum', '333_搓玉_定制.json'), ('lmd', '333_搓龙门币_定制.json')]:
    data = build(mode)
    p = os.path.join(OUTDIR, fn)
    io.open(p, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=2))
    print('=== 已生成:', p)
    for pl in data['plans']:
        print('  班:', pl['name'])
        for cat in ['trading','manufacture','control','power','hire']:
            for ri, r in enumerate(pl['rooms'].get(cat, [])):
                s = ' | '.join(r['operators']) if r['operators'] else '(空)'
                print(f"    {cat:11s}#{ri+1} {r.get('product',''):16s}: {s}")
