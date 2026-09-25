"""
Autonomous Routing (免@自主感知唤醒) for GroupConnect.

Architecture: Single-Arbiter + Symmetric Observers.
- Exactly ONE bot process (the arbiter, e.g. primary_bot) performs all
  semantic decisions (alias bypass / Flash-Lite tri-state classification).
- The decision is broadcast ONCE via the existing CrossBotRelay IPC.
- Both processes run the SAME observer code: if target_bot == self -> arm a
  countdown window; any other human message during the window cancels it;
  otherwise dispatch with reply anchoring.

Jev Classifier: Orthogonal Choice (timing) + Noul (assignment).
- Choice (single-select, fixed 3 options): judges ONLY the interaction
  timing / social context (immediate / wait / drop) — independent of bot
  identity, so probabilities never split across bots.
- Noul (per-bot yes/no): each bot independently evaluates "does this
  message need me to handle it?" — the assignment dimension.
- Dynamic dual threshold (one knob): when Choice says respond, the Noul
  gate relaxes to confidence_threshold × 2/3 (e.g. 0.40) to prevent
  false silences; when Choice says drop, the strict confidence_threshold
  (e.g. 0.60) guards against chitchat false rescues.
- Layered arbitration: no candidate bots -> true drop; Choice=drop with
  high-confidence Noul claims -> rescue with wait_silence (4s grace for
  humans to speak first); Choice!=drop -> adopt Choice's urgency directly.
- Threshold note: the Jev path uses the dynamic dual threshold above; the
  LLM path (single JSON output) applies a flat confidence_threshold with
  no relaxation, since it judges bot assignment and timing in one pass.

Semantic content (aliases, roles, windows, budget, classifier engine, and
optional rule overrides) is configured in groupconnect.yaml on top of built-in
defaults in groupconnect/routing/defaults.py.
"""

from .router import AutonomousController, AutonomousConfig

__all__ = ["AutonomousController", "AutonomousConfig"]
