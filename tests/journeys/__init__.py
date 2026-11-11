"""End-to-end journeys and performance budgets (P13 stage B).

Each journey drives the real app through the automation bridge, in a profile
of its own. They read the installed game, so they are marked ``real_game``
(budgets also ``timing``) and run only through ``scripts/codex_check.ps1
-Area journeys``. They skip, naming the reason, when no game profile is set.
"""
