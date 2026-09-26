"""b61df1c 全量实案回归：呼唤语双案 + dispatch/parallel + 顺序调换后防火墙回归。
用法: python3 .temp/probe_full.py
"""
import asyncio, sys
sys.path.insert(0, '/home/server/repos/GroupConnect')
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

CASES = [
    # -- 今日呼唤语双实案（此前误派管家） --
    ("小迷妹，管家最近智力有点低下，他改完你去看看改对了吗。", "Zheng Ma", "呼唤语实案1(应总管)"),
    ("小迷妹 还是你上吧。管家智力有点低。", "Zheng Ma", "呼唤语实案2(应总管)"),
    # -- dispatch / parallel 语义恢复 --
    ("管家，让小迷妹把周末攻略做一下", "Zheng Ma", "dispatch调度方(应管家)"),
    ("小迷妹和管家都来看看这个问题", "Zheng Ma", "parallel并联(应双bot)"),
    ("让他早点睡", "xiaorou", "第三人称委托(应wait)"),
    # -- 顺序调换(wait在上)后的防火墙回归 --
    ("买的蓝莓没熟咋办？", "xiaorou", "求助实案(应wait)"),
    ("这蓝莓也太酸了，白买了", "xiaorou", "纯吐槽(应drop)"),
    ("咱晚上吃火锅吧", "xiaorou", "夫妻提议(应drop)"),
    ("咱晚上吃啥好呢", "xiaorou", "对配偶开放问句(防火墙关键)"),
    ("老婆你真好看", "Zheng Ma", "亲昵(应drop)"),
    ("可以啊", "Zheng Ma", "短续接(应drop)"),
    # -- 明确指令不回归 --
    ("帮我查下明天去杭州的高铁", "Zheng Ma", "查询指令(应管家immediate)"),
    ("把客厅空调调到26度", "Zheng Ma", "设备指令(应管家immediate)"),
    ("提醒我明天早上8点吃药", "Zheng Ma", "提醒指令(应管家immediate)"),
    ("记账 午饭35块", "Zheng Ma", "记账指令(应管家immediate)"),
    ("小迷妹解释一下为什么觉得伴侣很可爱的时候会想咬他", "xiaorou", "点名总管提问"),
]

async def main():
    cfg = AutonomousConfig('/home/server/mama_family_files/.agents/groupconnect.yaml')
    arb = AutonomousArbiter(cfg)
    print(f"drop 生效版: {'自定义' if 'drop' in cfg.custom_rules else '默认'} | "
          f"wait: {'自定义' if 'wait' in cfg.custom_rules else '默认'} | "
          f"assignment: {'自定义' if 'assignment' in cfg.custom_rules else '默认'}")
    for text, sender, note in CASES:
        res = await arb.classify(text, sender, "")
        print(f"[{note}] 「{text}」\n  → target={res.get('target_bot')} bots={res.get('target_bots')} "
              f"urgency={res.get('urgency')} conf={res.get('confidence')} src={res.get('source')}")

if __name__ == "__main__":
    asyncio.run(main())
