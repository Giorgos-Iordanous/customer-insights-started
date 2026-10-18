import pytest

from customer_insights import analysis


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [([0, 1, 0, 1, 0], 0.4), ([0, 0], 0.0), ([1, 1], 1.0), ([], None)],
)
def test_cancellation_rate(statuses, expected):
    customers = ({"cancelled": status} for status in statuses)

    actual = analysis.cancellation_rate(customers)

    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    "customer",
    [
        {},
        {"cancelled": None},
        {"cancelled": "1"},
        {"cancelled": "active"},
        {"cancelled": -1},
        {"cancelled": 2},
        {"cancelled": 0.0},
        {"cancelled": 1.0},
        {"cancelled": False},
        {"cancelled": True},
    ],
)
def test_cancellation_rate_rejects_missing_or_unexpected_status(customer):
    with pytest.raises(ValueError):
        analysis.cancellation_rate([{"cancelled": 0}, customer])
