"""Customer cancellation analysis."""


def cancellation_rate(customers):
    """Return cancelled / total, or None for an empty dataset.

    Missing or unexpected statuses fail rather than silently biasing the rate.
    """
    total = cancelled = 0
    for customer in customers:
        try:
            status = customer["cancelled"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("Each customer must have a cancelled status of 0 or 1") from None
        if type(status) is not int or status not in (0, 1):
            raise ValueError("Each customer must have a cancelled status of 0 or 1")
        total += 1
        cancelled += status
    return cancelled / total if total else None


def cancellation_reasons(customers, comments, as_of=None):
    """Return aggregate associations and issue tags, not proven causes."""
    from .factors import analyse

    return analyse(customers, comments, as_of=as_of)


def at_risk_customers(customers, comments):
    """Return active customers most likely to cancel."""
    raise NotImplementedError
