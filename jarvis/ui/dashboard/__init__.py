"""Jarvis dashboard. Importing this package does not load Qt; call run()."""


def run(with_core=True):
    from .window import run as go
    return go(with_core)
