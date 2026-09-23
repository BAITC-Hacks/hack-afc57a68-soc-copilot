"""Извлечение оргструктуры (раздел 3), привязка функций к подразделениям (раздел 5)
и сравнение структур «до» / «после»."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.models import Clause, Document, Evidence

UNIT_RE = re.compile(r"(.+?)\s*\(([А-ЯЁA-Z]{2,})\)")
SPECIAL = {"ГА": "Главный аудитор", "БВА": "Все работники БВА", "Общество": "Общество"}


@dataclass
class Unit:
    abbr: str
    name: str
    kind: str                       # department | functional | role
    clause: str                     # пункт, где подразделение определено
    page: int
    quote: str
    positions: list[tuple[str, str]] = field(default_factory=list)  # (номер, должность)


def _abbr(name: str) -> str:
    return "".join(w[0].upper() for w in re.findall(r"[А-ЯЁа-яё]{3,}", name))


def _strip_unit_word(name: str) -> str:
    return re.sub(r"^(департамент|управление|отдел|служба|центр|направлени[ея])\s+", "",
                  name.lower()).strip()


def has_abbr(text: str, abbr: str) -> bool:
    return re.search(rf"(?<![А-ЯЁA-Z]){re.escape(abbr)}(?![А-ЯЁA-Z])", text) is not None


def extract_units(doc: Document) -> dict[str, Unit]:
    units: dict[str, Unit] = {}
    # 1) перечень подразделений: пункт «... состоит из следующих структурных подразделений»
    for c in doc.clauses:
        if re.search(r"состоит из следующих структурных подразделений", c.text, re.I):
            for ch in [x for x in doc.clauses if x.parent == c.number]:
                m = UNIT_RE.search(ch.text)
                if m:
                    units[m.group(2)] = Unit(m.group(2), m.group(1).strip(), "department",
                                             ch.number, ch.page, ch.text.rstrip("."))
            break
    # 2) должности, подчинённые Главному аудитору: «Директор X» без аббревиатуры -> функциональная единица
    for c in doc.clauses:
        if re.search(r"Главному аудитору подчиняются", c.text):
            for ch in [x for x in doc.clauses if x.parent == c.number]:
                m = re.match(r"Директор\s+(.+?)\.?$", ch.text)
                if not m or any(has_abbr(ch.text, a) for a in units):
                    continue
                name = m.group(1).strip()
                name = name[0].upper() + name[1:]
                name = re.sub(r"^Направления", "Направление", name)
                ab = _abbr(name)
                units[ab] = Unit(ab, name, "functional", ch.number, ch.page, ch.text.rstrip("."))
            break
    # 3) штатный состав: «Директору X подчиняются работники ... в составе следующих должностей»
    for c in doc.clauses:
        m = re.match(r"Директору\s+(.+?)\s+подчиняются", c.text)
        if not m:
            continue
        owner = resolve_owner("Директор " + m.group(1), units)
        for ab in owner:
            if ab in units:
                units[ab].positions = [(ch.number, ch.text.rstrip("."))
                                       for ch in doc.clauses if ch.parent == c.number]
    return units


def resolve_owner(header: str, units: dict[str, Unit]) -> list[str]:
    h = header.strip()
    low = h.lower()
    if re.search(r"главный аудитор и работники бва|^работники бва", low):
        return ["БВА"]
    if re.search(r"общество обеспечивает", low):
        return ["Общество"]
    found = [ab for ab in units if has_abbr(h, ab)]
    if found:
        return found
    for ab, u in units.items():
        key = _strip_unit_word(u.name)
        if len(key) > 8 and fuzz.partial_ratio(key, low) >= 90:
            return [ab]
    if re.search(r"директор[ыа]? департаментов", low):
        return [ab for ab, u in units.items() if u.kind == "department"]
    if "главный аудитор" in low:
        return ["ГА"]
    return []


def assign_owners(doc: Document, units: dict[str, Unit], section: str = "5") -> None:
    """Каждому пункту раздела 5 (права и обязанности) назначает подразделение-владельца
    по заголовку вида «5.4. Директор департамента ...:»."""
    sec = doc.get(section)
    default = resolve_owner(sec.text, units) if sec else []
    headers = [c for c in doc.clauses if c.depth == 2 and c.number.startswith(section + ".")]
    for h in headers:
        owner = resolve_owner(h.text[:200], units) or default
        for c in doc.subtree(h.number):
            c.owner_units = owner


def unit_label(abbrs: list[str]) -> str:
    return "/".join(abbrs) if abbrs else "—"


def owner_group(abbrs: list[str]) -> str:
    return "+".join(sorted(abbrs))


def function_clauses(doc: Document, section: str = "5") -> list[Clause]:
    """Листовые пункты раздела 5 с назначенным владельцем (без заголовков)."""
    return [c for c in doc.clauses
            if c.number.startswith(section + ".") and c.depth >= 3 and c.is_leaf
            and c.owner_units and len(c.text) > 15]


def ev(c: Clause, quote: str | None = None, role: str = "source") -> Evidence:
    q = quote if quote is not None else c.text
    return Evidence(doc_id=c.doc_id, clause=c.number, page=c.page, quote=q[:220], role=role)
