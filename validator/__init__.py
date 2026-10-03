"""Validator package: runtime checks, one-call review against the paper, and the calculator.

Names are loaded lazily so `python -m validator.runtime` does not import its own module twice.
"""
__all__ = ['Validator', 'load_paper', 'MAX_REVIEWS', 'REVIEW_TOKENS']


def __getattr__(name):
    if name in __all__:
        from . import core
        return getattr(core, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
