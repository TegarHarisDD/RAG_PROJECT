"""The Eval Set and its harness script (``python -m evals.run_eval``).

A script, not part of the test suite (spec's Testing Decisions): it runs the
live pipeline against Atlas and OpenRouter and records real results. Only the
scorer it uses (``app.eval_scorer``) is unit-tested.
"""
