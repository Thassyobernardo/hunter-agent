import os

def get_payment_link(lead_id: int, project_name: str) -> str:
    """
    Skill: stripe-integration.
    Generates a payment link with metadata to track which lead is paying.
    Currently uses static URL but is structured for Stripe Payment Links with pre-filled fields.
    """
    base_url = os.environ.get("PAYMENT_LINK_URL", "https://buy.stripe.com/example")
    
    # In a real Stripe implementation, we'd use the Stripe API to create a unique checkout session
    # or append client_reference_id as a query param.
    return f"{base_url}?client_reference_id={lead_id}&project={project_name.replace(' ', '_')}"
