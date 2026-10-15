"""Filling a ``{token}`` template and marking the names in the result (shared by events, reasons and hooks)."""

from __future__ import annotations

import string
from collections.abc import Mapping, Sequence

Ref = tuple[int, int, str, int]  # (start, end, what it names, its id) for one name in a text
Where = dict[str, tuple[str, int]]  # token -> (what it names, its id); what is one of ``entities.REF_KINDS``


def render_template(
    template: str,
    tokens: Mapping[str, object],
    where: Where,
    inner: Mapping[str, Sequence[Ref]] | None = None,
) -> tuple[str, list[Ref]]:
    """Fill ``template`` and return the text with the ``(start, end, what, id)`` span of every name in it.

    A token in ``where`` is one name. A token in ``inner`` is itself a text that holds names (a relation's reason, with
    the places it names): its spans are moved to where it lands in the result.
    """
    out: list[str] = []
    refs: list[Ref] = []
    length = 0
    for literal, field, _, _ in string.Formatter().parse(template):
        out.append(literal)
        length += len(literal)
        if field is None:
            continue
        value = str(tokens[field])
        if value and field in where:
            refs.append((length, length + len(value), *where[field]))
        if inner and field in inner:
            refs.extend((length + start, length + end, what, ident) for start, end, what, ident in inner[field])
        out.append(value)
        length += len(value)
    return "".join(out), refs
