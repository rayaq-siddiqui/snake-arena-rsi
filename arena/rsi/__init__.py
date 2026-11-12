"""Generic recursive self-improvement framework (phase 3).

Improves anything described by ``ParamSpec`` and an ``Evaluator``. It must not import
the engine, agents or simulator: a test walks the imports to enforce that.
"""
