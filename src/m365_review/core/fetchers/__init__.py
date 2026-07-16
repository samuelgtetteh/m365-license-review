"""Graph fetchers. Each module fetches one area and returns normalized models.

Fetchers never touch pagination/retry — that lives in graph_client. They only
know their endpoint(s) and how to map raw JSON into models.
"""
