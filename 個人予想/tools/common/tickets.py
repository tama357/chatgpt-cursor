from __future__ import annotations

import re
from dataclasses import dataclass

PICK_RE = re.compile(r"^([1-9])-([1-9])-([1-9]+)$")
TRIFECTA_RE = re.compile(r"^[1-9]-[1-9]-[1-9]$")
OFFICIAL_TRIFECTA_RE = re.compile(r"^(?:[1-9]|1[0-8])-(?:[1-9]|1[0-8])-(?:[1-9]|1[0-8])$")


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExpandedTicket:
    kind: str
    compact: str
    combinations: tuple[str, ...]


def expand_pick(compact: str) -> tuple[str, ...]:
    match = PICK_RE.fullmatch(compact)
    if not match:
        raise ValidationError(f"買い目の形式が不正です: {compact}")
    first, second, candidates = match.groups()
    if first == second:
        raise ValidationError(f"1着と2着が重複しています: {compact}")
    if len(set(candidates)) != len(candidates):
        raise ValidationError(f"3着候補に重複があります: {compact}")
    if first in candidates or second in candidates:
        raise ValidationError(f"同じ番号が複数着に含まれています: {compact}")
    return tuple(f"{first}-{second}-{third}" for third in candidates)


def count_tickets(tickets: list[dict[str, str]]) -> int:
    seen: set[str] = set()
    for ticket in tickets:
        for combo in expand_pick(ticket["pick"]):
            if combo in seen:
                raise ValidationError(f"展開後の買い目が重複しています: {combo}")
            seen.add(combo)
    return len(seen)


def expand_tickets(tickets: list[dict[str, str]]) -> list[ExpandedTicket]:
    seen: set[str] = set()
    expanded: list[ExpandedTicket] = []
    for ticket in tickets:
        combinations = expand_pick(ticket["pick"])
        duplicates = seen.intersection(combinations)
        if duplicates:
            raise ValidationError(
                f"展開後の買い目が重複しています: {', '.join(sorted(duplicates))}"
            )
        seen.update(combinations)
        expanded.append(ExpandedTicket(ticket["type"], ticket["pick"], combinations))
    return expanded


def check_hit(trifecta: str, tickets: list[dict[str, str]]) -> bool:
    if not OFFICIAL_TRIFECTA_RE.fullmatch(trifecta):
        raise ValidationError(f"三連単結果の形式が不正です: {trifecta}")
    if not TRIFECTA_RE.fullmatch(trifecta):
        # 公式が10番以上を含む場合、1〜9の買い目とは一致しない。
        return False
    picks = expand_tickets(tickets)
    all_combos = {combo for ticket in picks for combo in ticket.combinations}
    return trifecta in all_combos
