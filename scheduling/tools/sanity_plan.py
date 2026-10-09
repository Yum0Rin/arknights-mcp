# -*- coding: utf-8 -*-
"""周度理智规划（运筹模型）→ sanity_plan.json

参数来源：PRTS wiki（理智/任务/剿灭/关卡）+ 企鹅物流掉落（1-7 固源岩）。
- 自然回复 240/日；周常应急理智浓缩液×2=240；每日任务不给理智。
- 理智上限(99级)=205；每12h回复120<205 → 每次上线花到≤85 即不溢出。
- 剿灭当期：25理智/次≈370合成玉/次，周上限1800。
- CE-6: 36理智=10000龙门币；LS-6: 36理智=10000经验；1-7: 6理智≈1.245固源岩(4.82理智/个)。
- 搓玉链：2固源岩→1源石碎片→10合成玉。
- 养成配比(LMD:EXP)：6★=1.63、5★=1.55、4★=1.37（取6★为主）。
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sanity_plan.json")

# ---- 参数 ----
REGEN_DAY = 240            # 自然回复/日
CAP = 205                  # 理智上限(99级)
WEEK_TASK_SANITY = 240     # 周常 应急理智浓缩液×2
DAILY = {"lmd": 9500, "orundum": 100, "exp": 9600}      # 每日任务(作战记录折算经验)
WEEKLY = {"lmd": 23000, "orundum": 500, "exp": 24400}   # 每周任务
ANNI = {"san_per_run": 25, "orundum_per_run": 370, "week_cap": 1800}
CE = {"san": 36, "lmd": 10000}     # 277.78 龙门币/理智
LS = {"san": 36, "exp": 10000}     # 277.78 经验/理智
R17 = {"san": 6, "rock": 1.245}    # 固源岩
ROCK_PER_SHARD = 2
ORUNDUM_PER_SHARD = 10
RATIO = {"6★": 1.63, "5★": 1.55, "4★": 1.37}
# 基地每日产出（来自一图流）
BASE_QS = {"lmd": 55855, "exp": 30303}                        # 钱书均衡
BASE_OR = {"lmd": 34642, "exp": 15703, "orundum": 486}        # 搓玉
ROCK_NEED_OR = 92.4    # 搓玉基地每日耗固源岩


def grow_plan(budget, ratio, base, label):
    """养成向：剿灭打满后，剩余理智按 LMD:EXP 配比投 CE/LS（含基地+任务产出）。"""
    anni_runs = math.ceil(ANNI["week_cap"] / ANNI["orundum_per_run"])
    anni_san = anni_runs * ANNI["san_per_run"]
    rem = budget - anni_san
    # 非刷取来源
    lmd0 = base["lmd"] * 7 + DAILY["lmd"] * 7 + WEEKLY["lmd"]
    exp0 = base["exp"] * 7 + DAILY["exp"] * 7 + WEEKLY["exp"]
    k = CE["lmd"] / CE["san"]           # = LS 经验/理智（相等）
    # 解 lmd0 + k*s_ce = ratio*(exp0 + k*(rem-s_ce))
    s_ce = (ratio * (exp0 + k * rem) - lmd0) / (k * (1 + ratio))
    s_ls = rem - s_ce
    lmd = lmd0 + k * s_ce
    exp = exp0 + k * s_ls
    six = min(lmd / 589841, exp / 361400)
    return {
        "label": label, "ratio": ratio,
        "allocation": {"anni": anni_san, "anniRuns": anni_runs, "ce": round(s_ce, 1), "ls": round(s_ls, 1)},
        "fromBaseAndTasks": {"lmd": round(lmd0), "exp": round(exp0)},
        "total": {"lmd": round(lmd), "exp": round(exp)},
        "sixStarEquivPerWeek": round(six, 2),
        "orundumPerWeek": ANNI["week_cap"] + DAILY["orundum"] * 7 + WEEKLY["orundum"],
    }


def orundum_plan(budget, base):
    """搓玉向：剿灭打满后，剩余理智全刷 1-7 固源岩养搓玉。"""
    anni_runs = math.ceil(ANNI["week_cap"] / ANNI["orundum_per_run"])
    anni_san = anni_runs * ANNI["san_per_run"]
    rem = budget - anni_san
    rock = rem / (R17["san"] / R17["rock"])      # 固源岩/周
    shards = rock / ROCK_PER_SHARD
    orundum_craft = shards * ORUNDUM_PER_SHARD
    # 受基地搓玉产能约束（制造/贸易吞吐）
    base_cap = base["orundum"] * 7
    craft = min(orundum_craft, base_cap)
    total = craft + ANNI["week_cap"] + DAILY["orundum"] * 7 + WEEKLY["orundum"]
    return {
        "label": "搓玉向",
        "allocation": {"anni": anni_san, "anniRuns": anni_runs, "stage17": round(rem, 1)},
        "rockPerWeek": round(rock, 1),
        "shardsPerWeek": round(shards, 1),
        "craftOrundum": round(craft),
        "baseCraftCap": base_cap,
        "orundumTotalPerWeek": round(total),
    }


def main():
    budget = REGEN_DAY * 7 + WEEK_TASK_SANITY
    data = {
        "params": {
            "regenPerDay": REGEN_DAY, "sanityCap": CAP, "loginIntervalH": 12,
            "regenPerInterval": CAP * 0 + 120, "safeLeaveBelow": CAP - 120,
            "weeklyTaskSanity": WEEK_TASK_SANITY, "weeklyBudget": budget,
            "capNote": "12h回复120<上限205：每次上线把理智花到≤85即不溢出；道具可临时突破上限(≤999)。",
        },
        "anni": ANNI,
        "plans": {
            "grow6": grow_plan(budget, RATIO["6★"], BASE_QS, "养成向（6★配比 1.63）"),
            "grow5": grow_plan(budget, RATIO["5★"], BASE_QS, "养成向（5★配比 1.55）"),
            "orundum": orundum_plan(budget, BASE_OR),
        },
    }
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote", OUT)
    g = data["plans"]["grow6"]; o = data["plans"]["orundum"]
    print("养成(6★):", g["allocation"], "→ LMD", g["total"]["lmd"], "EXP", g["total"]["exp"],
          "≈", g["sixStarEquivPerWeek"], "个6★/周；合成玉", g["orundumPerWeek"])
    print("搓玉:", o["allocation"], "→ 固源岩", o["rockPerWeek"], "源石碎片", o["shardsPerWeek"],
          "合成玉合计", o["orundumTotalPerWeek"])


if __name__ == "__main__":
    main()
