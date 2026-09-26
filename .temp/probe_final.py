"""yaml wait 自定义生效后的最终复验。用法: python3 .temp/probe_final.py
"""
import asyncio, sys
sys.path.insert(0, '/home/server/repos/GroupConnect')
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

CASES = [
    ("咱晚上吃啥好呢", "xiaorou", "配偶商议(应drop)"),
    ("让他早点睡", "xiaorou", "第三人称转述(应wait)"),
    ("买的蓝莓没熟咋办？", "xiaorou", "求助实案(应wait)"),
    ("这蓝莓也太酸了，白买了", "xiaorou", "吐槽(应drop)"),
    ("咱晚上吃火锅吧", "xiaorou", "夫妻提议(应drop)"),
    ("老婆你真好看", "Zheng Ma", "亲昵(应drop)"),
    ("可以啊", "Zheng Ma", "短续接(应drop)"),
    ("小迷妹，管家最近智力有点低下，他改完你去看看改对了吗。", "Zheng Ma", "呼唤语实案1(应总管)"),
    ("小迷妹 还是你上吧。管家智力有点低。", "Zheng Ma", "呼唤语实案2(应总管)"),
    ("小迷妹和管家都来看看这个问题", "Zheng Ma", "并联(应双bot)"),
    ("帮我查下明天去杭州的高铁", "Zheng Ma", "明确指令(应管家immediate)"),
    ("把客厅空调调到26度", "Zheng Ma", "设备指令(应管家immediate)"),
    ("记账 午饭35块", "Zheng Ma", "记账指令(应管家immediate)"),
]

async def main():
    cfg = AutonomousConfig('/home/server/mama_family_files/.agents/groupconnect.yaml')
    arb = AutonomousArbiter(cfg)
    print(f"wait 生效版: {'自定义' if 'wait' in cfg.custom_rules else '默认'} | "
          f"drop: {'自定义' if 'drop' in cfg.custom_rules else '默认'}")
    for rnd in range(3):
        print(f"===== 第 {rnd+1} 轮 =====")
        for text, sender, note in CASES:
            res = await arb.classify(text, sender, "")
            print(f"[{note}] 「{text}」 → target={res.get('target_bot')} "
                  f"bots={res.get('target_bots')} urgency={res.get('urgency')} conf={res.get('confidence')}")

if __name__ == "__main__":
    asyncio.run(main())
