"""Every HTTP route the app serves, for tests that check routes as a whole.

`app.routes` lists an included router as one entry, so iterating it directly
sees only the routes declared on the app itself. Each included router expands
to the routes it registered, with their effective paths and dependencies.
"""


def app_routes(app) -> list:
    """Route objects with `path`, `methods`, `endpoint` and `dependant`."""
    routes = []
    for route in app.routes:
        expand = getattr(route, "effective_route_contexts", None)
        for candidate in (expand() if expand else [route]):
            if getattr(candidate, "methods", None) and hasattr(candidate, "path"):
                routes.append(candidate)
    return routes
