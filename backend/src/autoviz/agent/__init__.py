"""Internal LangGraph agentic workflow: NL request -> validated charts.

LangGraph decides when/why steps run; the deterministic services
(services/orchestrator.run_pipeline and friends) remain the single source of
truth for validation, execution, and chart generation.
"""
