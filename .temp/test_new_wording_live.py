"""Live A/B check: new default wording vs this morning's live case.

Cases:
  1. "买的蓝莓没熟咋办？"          — this morning's stranded help request (was drop 0.92)
  2. "这蓝莓也太酸了，白买了"      — pure complaint, must stay drop (firewall check)
  3. "哈哈小马昨晚又熬到三点"       — human-directed banter, must stay drop
"""
import asyncio, sys
sys.path.insert(0, "/home/server/repos/GroupConnect")
from groupconnect.core.config import GatewayConfig
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

gw = GatewayConfig.from_file("/home/server/mama_family_files/.agents/groupconnect.yaml", "guaguahome_bot")
cfg = getattr(gw, "autonomous_config", None) or AutonomousConfig("/home/server/mama_family_files/.agents/groupconnect.yaml")
arb = AutonomousArbiter(cfg)

CASES = [
    ("xiaorou", "买的蓝莓没熟咋办？", "(no prior messages)"),
    ("xiaorou", "这蓝莓也太酸了，白买了", "(no prior messages)"),
    ("xiaorou", "哈哈小马昨晚又熬到三点", "(no prior messages)"),
]

async def main():
    for sender, text, ctx in CASES:
        d = await arb.classify(text, sender, ctx)
        print(f"[{text}] -> target={d.get('target_bot')} urgency={d.get('urgency')} conf={d.get('confidence')} src={d.get('source')}")

asyncio.run(main())
