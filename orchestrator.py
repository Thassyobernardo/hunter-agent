import logging
from typing import TypedDict, List, Annotated, Sequence
import operator
from langgraph.graph import StateGraph, END

# Define the shared state for our agency
class AgencyState(TypedDict):
    # The current focus of the system (scan, build, sell, support)
    current_task: str
    # IDs of leads being processed in this cycle
    active_lead_ids: List[int]
    # Any errors encountered
    errors: List[str]
    # Status summary
    summary: dict

log = logging.getLogger(__name__)

def create_agency_graph():
    from scrapers import upwork_scraper
    import manager_agent
    import sales_agent
    import support_agent

    # 1. Define nodes
    def scan_node(state: AgencyState):
        log.info("--- [Node] Scanner Agent ---")
        try:
            # We run the scan and it returns number of saved leads
            # The leads themselves are in the DB
            count = upwork_scraper.scrape()
            return {"summary": {"new_leads": count}}
        except Exception as e:
            return {"errors": [f"Scan error: {str(e)}"]}

    def manager_node(state: AgencyState):
        log.info("--- [Node] Manager Agent ---")
        try:
            result = manager_agent.run_manager_cycle()
            return {"summary": result}
        except Exception as e:
            return {"errors": [f"Manager error: {str(e)}"]}

    def sales_node(state: AgencyState):
        log.info("--- [Node] Sales Agent ---")
        try:
            count = sales_agent.run_sales_cycle()
            return {"summary": {"sent_emails": count}}
        except Exception as e:
            return {"errors": [f"Sales error: {str(e)}"]}

    def support_node(state: AgencyState):
        log.info("--- [Node] Support Agent ---")
        try:
            count = support_agent.run_support_cycle()
            return {"summary": {"delivered_zips": count}}
        except Exception as e:
            return {"errors": [f"Support error: {str(e)}"]}

    # 2. Build the graph
    workflow = StateGraph(AgencyState)

    workflow.add_node("scanner", scan_node)
    workflow.add_node("manager", manager_node)
    workflow.add_node("sales", sales_node)
    workflow.add_node("support", support_node)

    # 3. Define edges
    # Standard flow: Scan -> Manage -> Sell -> Support
    workflow.set_entry_point("scanner")
    workflow.add_edge("scanner", "manager")
    workflow.add_edge("manager", "sales")
    workflow.add_edge("sales", "support")
    workflow.add_edge("support", END)

    return workflow.compile()

# Singleton for the agency app
_agency_app = None

def get_agency_app():
    global _agency_app
    if _agency_app is None:
        _agency_app = create_agency_graph()
    return _agency_app

def run_full_agency_cycle():
    """Trigger one full multi-agent cycle."""
    app = get_agency_app()
    initial_state = {
        "current_task": "start",
        "active_lead_ids": [],
        "errors": [],
        "summary": {}
    }
    return app.invoke(initial_state)
