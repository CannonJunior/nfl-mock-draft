"""
Analytics package for the NFL Mock Draft 2026 prediction engine.

Modules:
    player_pool   — build PlayerCandidate list from DB
    position_value — load config, compute position-adjusted score
    team_context   — load team needs; compute need boost + supply pressure
    draft_engine   — score each player for each team at a given pick
    simulator      — sequential 1-100 simulation + output writing
"""
