"""Pure recipe logic: rendering and diffing.

Nothing in this package touches the database, the network, or the web
framework. That is what makes the review gate testable — the diff you approve
is computed by functions that can be exercised in isolation.
"""
