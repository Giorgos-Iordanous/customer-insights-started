"""Aggregate cancellation associations; comments are strings, never instructions."""
from datetime import date
import re


_INSTRUCTION = re.compile(
    r"ignore.{0,60}(?:instruction|previous)|export.{0,80}(?:customer|table)|"
    r"\.env\b|admin.{0,20}password|https?://|records-backup|"
    r"keep.{0,30}secret|do not.{0,20}(?:tell|disclose)", re.I | re.S
)
_LOGIN = re.compile(
    r"\b(?:can't|cannot|unable to|couldn't)\b.{0,30}\blog in\b|"
    r"\blog in\b.{0,30}\b(?:can't|cannot|unable to|couldn't)\b", re.I
)
_BUFFERING = re.compile(r"\bbuffering\b", re.I)
_NO_BUFFERING = re.compile(
    r"\b(?:no|not|never|without)\b.{0,25}\bbuffering\b|"
    r"\bbuffering\b.{0,20}\b(?:fixed|resolved|gone)\b", re.I
)
_SUBTITLES = re.compile(r"\bsubtitles?\b.{0,80}\bout of sync\b", re.I)
_NO_SUBTITLE_PROBLEM = re.compile(r"\b(?:not|never|no longer)\b.{0,20}\bout of sync\b", re.I)
_NOT_MISSING = re.compile(r"\b(?:not|nothing|no longer)\b.{0,20}\bmissing\b", re.I)
_ARABIC_AUDIO = re.compile(
    r"\bmissing\s+(?:the\s+)?Arabic\s+audio\b|"
    r"\bArabic\s+audio(?:\s+tracks?)?(?:\s+(?:is|are))?\s+missing\b", re.I
)
_PAYMENT_FAILURE = re.compile(
    r"\bpayment\b.{0,40}\bfail(?:ed|ure|s)?\b|"
    r"\bfail(?:ed|ure|s)?\b.{0,40}\bpayment\b", re.I
)
_VALUE = re.compile(r"\bnot\b.{0,30}\bworth\b|\bworth\b.{0,30}\bnot\b", re.I)
_PRICE = re.compile(r"\b(?:price|cost|money|subscription|fee|value)\b", re.I)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _themes(text):
    """Conservative, potentially incomplete phrase tags; no causal inference."""
    technical = bool(
        _LOGIN.search(text)
        or (_BUFFERING.search(text) and not _NO_BUFFERING.search(text))
        or (_SUBTITLES.search(text) and not _NO_SUBTITLE_PROBLEM.search(text))
    )
    arabic_audio = bool(_ARABIC_AUDIO.search(text) and not _NOT_MISSING.search(text))
    return {
        "technical": technical,
        "arabic_audio": arabic_audio,
        "payment_failure": bool(_PAYMENT_FAILURE.search(text)),
        "value": bool(_VALUE.search(text) and _PRICE.search(text)),
    }


def analyse(customers, comments, as_of=None):
    """Return numeric aggregates only; never return customer values or comments."""
    as_of = date.today() if as_of is None else as_of
    if type(as_of) is not date:
        raise ValueError("Analysis date must be a date")
    by_id = {}
    payment = {status: {"total": 0, "cancelled": 0} for status in ("paid", "late", "failed")}
    tickets = {band: {"total": 0, "cancelled": 0} for band in ("high", "low")}
    cancelled = 0
    required = (
        "customer_id", "signup_date", "cancelled", "cancelled_date",
        "last_payment_status", "support_tickets",
    )
    for source in customers:
        try:
            row = {key: source[key] for key in required}
        except (KeyError, IndexError, TypeError):
            raise ValueError("Required analytics fields are unavailable") from None
        identifier, status = row["customer_id"], row["cancelled"]
        signup, ended = _day(row["signup_date"]), _day(row["cancelled_date"])
        if (
            type(identifier) is not int or identifier in by_id
            or type(status) is not int or status not in (0, 1)
            or signup is None or signup > as_of
            or (status == 1 and (ended is None or ended < signup or ended > as_of))
            or (status == 0 and row["cancelled_date"] is not None)
            or not isinstance(row["last_payment_status"], str) or row["last_payment_status"] not in payment
            or type(row["support_tickets"]) is not int or row["support_tickets"] < 0
        ):
            raise ValueError("Invalid or inconsistent customer analytics data")
        by_id[identifier] = (status, signup, ended)
        cancelled += status
        for group in (payment[row["last_payment_status"]], tickets["high" if row["support_tickets"] >= 3 else "low"]):
            group["total"] += 1
            group["cancelled"] += status

    commenters = {"cancelled": set(), "active": set()}
    theme_sets = {
        name: {status: set() for status in commenters}
        for name in ("technical", "arabic_audio", "payment_failure", "value")
    }
    temporal = {name: set() for name in ("earlier", "retrospective")}
    counts = {key: 0 for key in (
        "total", "before_signup", "invalid_dates", "future_dates", "instruction_excluded", "retained"
    )}
    temporal_counts = {name: 0 for name in temporal}
    for source in comments:
        counts["total"] += 1
        try:
            identifier, text = (source[key] for key in ("customer_id", "comment_text"))
        except (KeyError, IndexError, TypeError):
            raise ValueError("Required comment fields are unavailable") from None
        try:
            created = source["created_at"]
        except (KeyError, IndexError):
            created = None
        if type(identifier) is not int or identifier not in by_id:
            raise ValueError("Comment customer is absent from the analytics view")
        status, signup, ended = by_id[identifier]
        created = _day(created)
        if created is None:
            counts["invalid_dates"] += 1
            continue
        if created < signup:
            counts["before_signup"] += 1
            continue
        if created > as_of:
            counts["future_dates"] += 1
            continue
        if not isinstance(text, str):
            raise ValueError("Comment text must be text")
        # Exclude the entire matching comment, not just its embedded instruction.
        # This heuristic is not a guarantee that every malicious string is detected.
        # Every other string is still used only as data in fixed regular expressions.
        if _INSTRUCTION.search(text):
            counts["instruction_excluded"] += 1
            continue
        counts["retained"] += 1
        label = "cancelled" if status else "active"
        if status:
            period = "earlier" if created < ended else "retrospective"
            temporal[period].add(identifier)
            temporal_counts[period] += 1
            # Date-only records cannot establish ordering on cancellation day.
            # Use only strictly earlier feedback for both themes and coverage.
            if period == "retrospective":
                continue
        commenters[label].add(identifier)
        for theme, matches in _themes(text).items():
            if matches:
                theme_sets[theme][label].add(identifier)

    counts.update({name: {"comments": temporal_counts[name], "customers": len(ids)} for name, ids in temporal.items()})
    return {
        "total": len(by_id), "cancelled": cancelled, "payment": payment, "tickets": tickets,
        "themes": {name: {status: len(ids) for status, ids in groups.items()} for name, groups in theme_sets.items()},
        "commenters": {status: len(ids) for status, ids in commenters.items()}, "comments": counts,
    }


def _percentage(numerator, denominator, places=2):
    return f"{numerator / denominator:.{places}%}" if denominator else "N/A"


def _group(group):
    return f"{_percentage(group['cancelled'], group['total'])} ({group['cancelled']:,}/{group['total']:,})"


def report_content(stats):
    """Render static labels and computed numbers; never interpolate source text."""
    payment, tickets = stats["payment"], stats["tickets"]
    rows = [
        {"factor": "Payment difficulties", "evidence": (
            f"Failed-payment customers cancelled at {_group(payment['failed'])}, versus {_group(payment['paid'])} "
            f"for paid customers. Late-payment customers cancelled at {_group(payment['late'])}."
        )},
        {"factor": "Higher support-ticket counts", "evidence": (
            f"Customers with 3+ tickets cancelled at {_group(tickets['high'])}, versus {_group(tickets['low'])} "
            "for fewer tickets. This may indicate service friction; ticket counts alone cannot explain the underlying problem."
        )},
    ]
    for key, label, description in (
        ("technical", "Technical problems", "Login/access, buffering, or subtitle-sync issues appeared for"),
        ("arabic_audio", "Missing Arabic audio tracks", "Mentioned by"),
        ("payment_failure", "Payment failure in comments", "Mentioned by"),
        ("value", "Poor perceived value", "Mentioned by"),
    ):
        n, d = stats["themes"][key], stats["commenters"]
        evidence = (
            f"{description} {n['cancelled']:,}/{d['cancelled']:,} cancelled commenters "
            f"({_percentage(n['cancelled'], d['cancelled'], 1)})."
        )
        rows.append({"factor": label, "evidence": evidence})
    c, d = stats["comments"], stats["commenters"]
    notes = [
        f"Entire comments matching instruction/URL filters were excluded from thematic analysis ({c['instruction_excluded']:,} excluded). "
        f"Comments dated before signup were also excluded ({c['before_signup']:,} excluded).",
        f"Comment themes cover {d['cancelled']:,}/{stats['cancelled']:,} cancelled customers with retained comments "
        "dated on or after signup and strictly before cancellation. "
        "Each customer is counted once per theme. Themes overlap and cannot be added together.",
        f"Earlier feedback used for themes: {c['earlier']['comments']:,} comments from {c['earlier']['customers']:,} cancelled customers. "
        f"Retrospective feedback (on or after cancellation) was excluded from theme counts and their denominator: "
        f"{c['retrospective']['comments']:,} comments from {c['retrospective']['customers']:,} cancelled customers. "
        "Customers may appear in both timing groups. Active-customer theme comparisons are omitted because observation windows differ.",
        "These are associations and reported issues, not proven causes of cancellation.",
        "The cancellation rate covers the full snapshot, not only this week. Comment themes use conservative phrase rules; "
        "payment status and ticket counts may postdate cancellation.",
    ]
    if c["invalid_dates"] or c["future_dates"]:
        notes.insert(1, f"Additional date exclusions: {c['invalid_dates']:,} missing/invalid dates and {c['future_dates']:,} future dates.")
    return rows, notes
