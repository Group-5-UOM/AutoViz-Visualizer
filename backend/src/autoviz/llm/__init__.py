"""LLM planner layer (Week 2) — NL request -> analysis_plan + one repair attempt.

Planned modules:
- prompts.py    system prompt with dataset schema/profile context
- planner.py    NL -> structured AnalysisPlan (JSON output)
- repair.py     one automatic retry driven by validation errors / failed_step
"""
