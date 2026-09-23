"""
Autonomous Routing (免@自主感知唤醒) for GroupConnect.

Architecture: Single-Arbiter + Symmetric Observers.
- Exactly ONE bot process (the arbiter, e.g. primary_bot) performs all
  semantic decisions (alias bypass / Flash-Lite tri-state classification).
- The decision is broadcast ONCE via the existing CrossBotRelay IPC.
- Both processes run the SAME observer code: if target_bot == self -> arm a
  countdown window; any other human message during the window cancels it;
  otherwise dispatch with reply anchoring.

Jev Classifier: Choice + Noul Two-Stage Pipeline.
- Choice (single-select): determines the primary responder and urgency
  (immediate / wait_silence / none_drop) from structured option criteria.
- Noul (per-bot yes/no): independently evaluates whether each bot should
  participate in parallel collaboration alongside the primary responder.
- Rescue: if Choice drops (probabilities split across bots, e.g. "you two
  both look at this"), but Noul detects explicit parallel intent for any bot
  above parallel_threshold, the drop is rescued — all qualifying bots are
  activated with immediate urgency. Only when BOTH Choice and Noul fail to
  reach threshold does the message fail-closed to drop.

Semantic content (aliases, roles, windows, budget, classifier engine, and
optional rule overrides) is configured in groupconnect.yaml on top of built-in
defaults in groupconnect/routing/defaults.py.
"""

from .router import AutonomousController, AutonomousConfig

__all__ = ["AutonomousController", "AutonomousConfig"]
