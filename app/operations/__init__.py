"""Background-operation execution + persistence (Milestone 8).

Scope is deliberately narrow: this runs a small, fixed set of
already-existing, already-tested Milestone 1-7 entry points (currently
just the knowledge-base rebuild) on a background thread instead of
blocking the HTTP request for their duration. It is not a general task
queue, does not accept arbitrary code from a caller, and does not add
any new reasoning/planning capability -- every operation type it can
run is a single, hardcoded, pre-existing function.
"""
