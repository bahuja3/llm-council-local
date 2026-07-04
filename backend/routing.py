"""Per-query council routing.

Generalizes the fast 5th-seat swap into full per-seat routing: each signal
detected in the user's question (a web search fired, it's a coding question, it's
quantitative) lets a *specialist* model claim a seat; *generalist* models fill the
remaining seats up to COUNCIL_SIZE. Detection is cheap regex on the ORIGINAL
question (not the search-augmented one).
"""

import re
from typing import List, Tuple

from .config import (
    SPECIALISTS_FULL,
    SPECIALISTS_FAST,
    ROUTE_GENERALISTS_FULL,
    ROUTE_GENERALISTS_FAST,
    COUNCIL_SIZE,
    CHAIRMAN_MODEL,
    FAST_CHAIRMAN_MODEL,
)

# Coding-question signal (targeted to avoid false positives on generic words).
_CODE_RE = re.compile(
    r"\b(code|coding|program|programming|script|function|debug|traceback|"
    r"stack ?trace|compile|syntax|regex|refactor|algorithm|leetcode|"
    r"python|javascript|typescript|rust|golang|c\+\+|sql)\b|```",
    re.IGNORECASE,
)

# Quantitative / math-reasoning signal.
_MATH_RE = re.compile(
    r"\b(math|maths|calculate|calculation|compute|equation|solve for|"
    r"integral|derivative|calculus|algebra|geometry|probability|factorial|"
    r"theorem|prove that|logarithm|quadratic|percentage|percent)\b|"
    r"\d+\s*[+\-*/^%]\s*\d+",
    re.IGNORECASE,
)


def detect_signals(query: str, searched: bool) -> List[str]:
    """Ordered list of active specialist signals for this query.

    Order matters: earlier signals claim seats first when the council is small.
    """
    signals: List[str] = []
    if searched:
        signals.append("websearch")
    if _CODE_RE.search(query):
        signals.append("code")
    if _MATH_RE.search(query):
        signals.append("math")
    return signals


def route_council(query: str, searched: bool, fast: bool) -> Tuple[List[str], str, List[str]]:
    """
    Assemble the council for this query.

    Returns (council_models, chairman, signals). Specialists for each active
    signal claim seats first; generalists (fast or full pool) fill the rest up to
    COUNCIL_SIZE, de-duplicated. With no signals this is just the generalist
    roster — identical to the pre-routing behavior.
    """
    generalists = ROUTE_GENERALISTS_FAST if fast else ROUTE_GENERALISTS_FULL
    specialists = SPECIALISTS_FAST if fast else SPECIALISTS_FULL
    chairman = FAST_CHAIRMAN_MODEL if fast else CHAIRMAN_MODEL
    signals = detect_signals(query, searched)

    seats: List[str] = []
    # Specialists claim seats first (in signal order), de-duplicated.
    for sig in signals:
        model = specialists.get(sig)
        if model and model not in seats:
            seats.append(model)
    # Generalists fill the remaining seats.
    for g in generalists:
        if len(seats) >= COUNCIL_SIZE:
            break
        if g not in seats:
            seats.append(g)

    return seats[:COUNCIL_SIZE], chairman, signals
