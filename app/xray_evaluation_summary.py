"""Biologist-facing interpretation of stored exact scientific Structure AI scores.

These are descriptive comparisons with human VERIFIED labels, not a claim of
independent model validation or estimates of human correction time.
"""
from __future__ import annotations


def format_fraction(correct, total):
    total=int(total or 0)
    if total<=0:
        return "not evaluated"
    n=int(correct or 0)
    return f"{n} of {total} ({100*n/total:.1f}%)"


def scientific_comparison_summary(summary):
    """Return honest outcome lines, prioritizing complete specimens and exact values."""
    complete=format_fraction(summary.get("all_traits_correct_specimens"),
                             summary.get("all_traits_evaluable_specimens"))
    measurements=format_fraction(summary.get("exact_traits"),
                                 summary.get("exact_traits_total"))
    lines=[
        f"All measured traits correct on the same specimen: {complete}",
        f"Individual scientific measurements exactly correct: {measurements}",
    ]
    delta=summary.get("repeated_count_mae")
    if delta is not None:
        lines.append(f"Average absolute error in counted elements: {float(delta):.2f}")
    return "\n".join(lines)
