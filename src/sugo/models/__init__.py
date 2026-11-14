"""Models Sugo downloads on request: the registry, where they are kept, and the download (ADR-070).

``registry`` and ``store`` never touch the network, so any port may use them
to say whether a model is installed; only ``download`` calls the gateway.
"""
