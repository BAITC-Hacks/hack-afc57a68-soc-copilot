"""Инструменты агента: StructComparator, LossDetector, DuplicationDetector,
ConflictDetector, CrossRefChecker, DefectDetector.

Все инструменты детерминированные (правила + сходство). LLM (если включён)
используется поверх них для пограничных случаев — см. app/agent/llm.py.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter

import numpy as np
from rapidfuzz import fuzz

from app import config
from app.agent.similarity import Similarity, normalize
from app.agent.structure import (Unit, ev, function_clauses, has_abbr, owner_group,
                                 unit_label)
from app.models import Clause, Document, Finding

SPECIAL_OWNERS = {"ГА", "БВА", "Общество"}

# Типовые обязанности, которые есть у каждого руководителя: не считаем их дублированием
GENERIC_PATTERNS = [
    r"^осуществля\w* выполнение прочих поручений",
    r"^запрашива\w* у руководителей общества",
    r"^взаимодейству\w* [cс] руководителями общества",
    r"^выно\w* предложения по повышению профессионального",
    r"^участву\w* в разработке",
    r"^готов\w* материалы",
    r"^готов\w* предложения для включения в план",
    r"^организует работу",
    r"^вести переписку",
    r"^присутствовать на заседаниях",
    r"^выносить (главному аудитору )?предложения по поощрению",
    r"^использовать конфиденциальную",
]


def is_generic(text: str) -> bool:
    t = text.lower().strip()
    return any(re.search(p, t) for p in GENERIC_PATTERNS)


def lex_score(a: str, b: str) -> float:
    """Доля слов более короткого текста, которые в том же порядке есть в более длинном."""
    wa, wb = [w[:6] for w in normalize(a).split()], [w[:6] for w in normalize(b).split()]
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(short) < 5:
        return 0.0
    sm = difflib.SequenceMatcher(a=short, b=long_, autojunk=False)
    matched = sum(bl.size for bl in sm.get_matching_blocks())
    return matched / len(short) * 0.95


def lost_fragments(before: str, after: str, min_words: int = 3) -> list[str]:
    """Фрагменты текста «до», которых нет в тексте «после» (пословный diff)."""
    wa, wb = before.split(), after.split()
    na = [normalize(w)[:6] for w in wa]
    nb = [normalize(w)[:6] for w in wb]
    sm = difflib.SequenceMatcher(a=na, b=nb, autojunk=False)
    out = []
    for tag, i1, i2, _, _ in sm.get_opcodes():
        if tag in ("delete", "replace"):
            words = list(wa[i1:i2])
            while words and len(words[-1].strip(",;.")) <= 2:
                words.pop()
            while words and len(words[0].strip(",;.")) <= 2:
                words.pop(0)
            content = [w for w in na[i1:i2] if len(w) > 3]
            if len(content) >= min_words:
                out.append(" ".join(words).strip(" ,;."))
    return out


class Toolkit:
    """Общий контекст инструментов: документы, подразделения, матрицы сходства."""

    def __init__(self, before: Document, after: Document,
                 units_before: dict[str, Unit], units_after: dict[str, Unit]):
        self.before, self.after = before, after
        self.ub, self.ua = units_before, units_after
        self.sim = Similarity().fit([c.text for c in before.clauses + after.clauses])
        self.fb = function_clauses(before)
        self.fa = function_clauses(after)
        self.M = self._combined(self.fb, self.fa)
        self.reorg_map: dict[str, list[str]] = {}
        self._n = Counter()

    def _combined(self, A: list[Clause], B: list[Clause]) -> np.ndarray:
        if not A or not B:
            return np.zeros((len(A), len(B)))
        M = self.sim.matrix([c.text for c in A], [c.text for c in B])
        for i, a in enumerate(A):                 # лексическая поправка для лучших кандидатов
            for j in np.argsort(-M[i])[:8]:
                lx = lex_score(a.text, B[j].text)
                if lx >= 0.8:                     # засчитываем только явное вхождение
                    M[i, j] = max(M[i, j], lx)
        return M

    def next_id(self, prefix: str) -> str:
        self._n[prefix] += 1
        return f"{prefix}{self._n[prefix]}"

    # ------------------------------------------------------------ StructComparator
    def struct_comparator(self) -> list[Finding]:
        out: list[Finding] = []
        kept = [a for a in self.ub if a in self.ua]
        created = [a for a in self.ua if a not in self.ub]
        gone = [a for a in self.ub if a not in self.ua]

        for ab in gone:                           # куда ушли функции исчезнувшей единицы
            idx = [i for i, c in enumerate(self.fb) if ab in c.owner_units]
            targets = Counter()
            for i in idx:
                j = int(self.M[i].argmax())
                if self.M[i, j] >= config.SIM_LOST:
                    for o in self.fa[j].owner_units:
                        if o not in SPECIAL_OWNERS:
                            targets[o] += 1
            share = {o: n / max(len(idx), 1) for o, n in targets.items()}
            receivers = [o for o, s in share.items() if s >= 0.3 and o in created] or \
                        [o for o, s in share.items() if s >= 0.3]
            u = self.ub[ab]
            fid = self.next_id("S")
            evid = [ev(self._clause(self.before, u.clause), u.quote)]
            if receivers:
                self.reorg_map[ab] = receivers
                for r in receivers:
                    ua = self.ua[r]
                    evid.append(ev(self._clause(self.after, ua.clause), ua.quote, "target"))
                out.append(Finding(
                    id=fid, category="structure", type="reorganized", severity="high",
                    title=f"{u.name} ({ab}) → {', '.join(receivers)}",
                    units_before=[ab], units_after=receivers, evidence=evid,
                    rationale=(f"В ред. {self.after.edition} единица «{u.name}» отсутствует; "
                               f"{round(100 * sum(targets[r] for r in receivers) / max(len(idx), 1))}% "
                               f"её функций (раздел 5) найдены у {', '.join(receivers)}."),
                    recommendation="Проверить, что все функции упразднённой единицы закреплены за новыми подразделениями.",
                    confidence=0.85, method="similarity"))
            else:
                out.append(Finding(
                    id=fid, category="structure", type="removed", severity="high",
                    title=f"Упразднено: {u.name} ({ab})", units_before=[ab], evidence=evid,
                    rationale="Подразделение отсутствует в новой редакции, преемник функций не найден.",
                    recommendation="Определить преемника функций.", confidence=0.7, method="similarity"))

        for ab in created:
            u = self.ua[ab]
            base = [g for g, rs in self.reorg_map.items() if ab in rs]
            pos = "; ".join(p for _, p in u.positions)
            out.append(Finding(
                id=self.next_id("S"), category="structure", type="created", severity="info",
                title=f"Создано: {u.name} ({ab})" + (f" на базе {', '.join(base)}" if base else ""),
                units_after=[ab], evidence=[ev(self._clause(self.after, u.clause), u.quote, "target")],
                rationale=(f"Подразделение впервые указано в ред. {self.after.edition}."
                           + (f" Должности: {pos}." if pos else "")),
                confidence=0.95, method="rule"))

        for ab in kept:
            ub, ua = self.ub[ab], self.ua[ab]
            pb = {re.sub(r"\s+" + ab + r"$", "", p) for _, p in ub.positions}
            pa = {re.sub(r"\s+" + ab + r"$", "", p) for _, p in ua.positions}
            note = ""
            if pb != pa:
                removed_p = sorted(pb - pa)
                added_p = sorted(pa - pb)
                note = (f" Состав должностей изменён: исключены — {', '.join(removed_p) or 'нет'}; "
                        f"добавлены — {', '.join(added_p) or 'нет'}.")
            out.append(Finding(
                id=self.next_id("S"), category="structure", type="kept", severity="info",
                title=f"Сохранено: {ua.name} ({ab})", units_before=[ab], units_after=[ab],
                evidence=[ev(self._clause(self.before, ub.clause), ub.quote),
                          ev(self._clause(self.after, ua.clause), ua.quote, "target")],
                rationale="Подразделение присутствует в обеих редакциях." + note,
                confidence=0.95, method="rule"))
        return out

    # ------------------------------------------------------------ LossDetector
    def _mapped(self, owners: list[str]) -> set[str]:
        s = set(owners)
        for o in owners:
            s |= set(self.reorg_map.get(o, []))
        return s

    def loss_detector(self) -> tuple[list[Finding], list[dict]]:
        findings: list[Finding] = []
        gray: list[dict] = []                     # кандидаты для LLM-классификации
        for i, c in enumerate(self.fb):
            mapped = self._mapped(c.owner_units)
            same_idx = [j for j, a in enumerate(self.fa) if mapped & set(a.owner_units)]
            s_same, j_same = (max(((self.M[i, j], j) for j in same_idx), default=(0.0, -1)))
            j_any = int(self.M[i].argmax()) if self.fa else -1
            s_any = float(self.M[i, j_any]) if j_any >= 0 else 0.0
            before_lbl = unit_label(c.owner_units)

            if s_same >= config.SIM_KEPT:
                t = self.fa[j_same]
                frags = self._really_lost(lost_fragments(c.text, t.text, min_words=4), mapped)
                if frags and s_same < 0.97 and not is_generic(c.text):
                    findings.append(self._fn("partially_lost", "low", c, t, s_same, frags))
                continue
            if s_any >= config.SIM_KEPT and j_any >= 0:
                t = self.fa[j_any]
                existed = self._existed_before(t)
                if is_generic(c.text):
                    continue                      # типовая обязанность руководителя
                if existed:
                    f = self._fn("removed_duplicate", "info", c, t, s_any)
                    f.rationale = (f"Функция исключена у {before_lbl}, но сохраняется у "
                                   f"{unit_label(t.owner_units)}, где она была и раньше "
                                   f"(п. {existed.number} ред. {self.before.edition}). "
                                   f"Вероятно, устранено дублирование.")
                    findings.append(f)
                else:
                    findings.append(self._fn("moved", "medium", c, t, s_any))
                continue
            best_j = j_same if s_same >= s_any else j_any
            best_s = max(s_same, s_any)
            t = self.fa[best_j] if best_j >= 0 else None
            if best_s >= config.SIM_LOST and t is not None:
                frags = self._really_lost(lost_fragments(c.text, t.text), mapped)
                if (not frags and best_j == j_same) or is_generic(c.text):
                    continue                      # переформулировано / типовая обязанность
                f = self._fn("partially_lost", "medium", c, t, best_s, frags)
            else:
                f = self._fn("lost", "high" if not is_generic(c.text) else "medium", c, t, best_s)
            findings.append(f)
            gray.append({"finding_id": f.id, "before": c.text, "after": t.text if t else "",
                         "before_owner": before_lbl,
                         "after_owner": unit_label(t.owner_units) if t else "—"})
        return findings, gray

    def _really_lost(self, frags: list[str], owners: set[str]) -> list[str]:
        """Оставляет только фрагменты, которых нет ни в одном пункте того же владельца."""
        pool = [normalize(a.text) for a in self.after.clauses if owners & set(a.owner_units)]
        return [f for f in frags
                if not any(fuzz.partial_ratio(normalize(f), p) >= 85 for p in pool)]

    def _existed_before(self, target: Clause) -> Clause | None:
        for c in self.fb:
            if set(c.owner_units) & set(target.owner_units):
                if max(self.sim.matrix([c.text], [target.text])[0, 0],
                       lex_score(c.text, target.text)) >= config.SIM_KEPT:
                    return c
        return None

    def _fn(self, typ: str, sev: str, c: Clause, t: Clause | None, s: float,
            frags: list[str] | None = None) -> Finding:
        titles = {"lost": "Потеря функции", "partially_lost": "Частичная потеря функции",
                  "moved": "Перенос функции", "removed_duplicate": "Исключено дублирование"}
        after_lbl = unit_label(t.owner_units) if t else "—"
        evid = [ev(c)]
        if t is not None:
            evid.append(ev(t, role="closest" if typ in ("lost", "partially_lost") else "target"))
        rationale = {
            "lost": f"Для п. {c.number} ред. {c.edition} не найдено аналога в ред. {self.after.edition} "
                    f"(максимальное сходство {s:.2f}).",
            "partially_lost": f"Ближайший аналог — п. {t.number if t else '—'} ({after_lbl}), "
                              f"сходство {s:.2f}." + (f" Утрачено: «{'»; «'.join(frags)}»." if frags else ""),
            "moved": f"Функция перешла от {unit_label(c.owner_units)} к {after_lbl} "
                     f"(п. {t.number if t else '—'}, сходство {s:.2f}).",
            "removed_duplicate": "",
        }[typ]
        rec = {
            "lost": f"Решить, нужна ли функция; при необходимости закрепить её за подразделением в новой редакции.",
            "partially_lost": "Проверить, не утрачено ли существенное содержание формулировки.",
            "moved": f"Убедиться, что у {after_lbl} есть ресурсы и полномочия для выполнения функции.",
            "removed_duplicate": "Действий не требуется; зафиксировать как положительное изменение.",
        }[typ]
        return Finding(
            id=self.next_id({"lost": "L", "partially_lost": "P", "moved": "M",
                             "removed_duplicate": "R"}[typ]),
            category="function", type=typ, severity=sev,
            title=f"{titles[typ]}: {c.text[:90]}{'…' if len(c.text) > 90 else ''}",
            units_before=c.owner_units, units_after=t.owner_units if t and typ != "lost" else [],
            evidence=evid, similarity=round(float(s), 3), rationale=rationale,
            recommendation=rec, confidence=0.75 if typ != "lost" else 0.8, method="similarity")

    # ------------------------------------------------------------ DuplicationDetector
    def duplication_detector(self) -> tuple[list[Finding], list[dict]]:
        B = [c for c in self.fa if not set(c.owner_units) & SPECIAL_OWNERS
             and len(c.owner_units) < len([u for u in self.ua.values() if u.kind == "department"])
             and not is_generic(c.text)]
        M = self._combined(B, B)
        out, cands = [], []
        for i in range(len(B)):
            for j in range(i + 1, len(B)):
                if set(B[i].owner_units) & set(B[j].owner_units):
                    continue
                s = float(max(M[i, j], M[j, i]))
                if s < config.SIM_DUP:
                    continue
                a, b = B[i], B[j]
                f = Finding(
                    id=self.next_id("D"), category="duplication", type="duplication",
                    severity="medium",
                    title=f"Дублирование: {unit_label(a.owner_units)} (п. {a.number}) и "
                          f"{unit_label(b.owner_units)} (п. {b.number})",
                    units_after=sorted(set(a.owner_units + b.owner_units)),
                    evidence=[ev(a), ev(b, role="support")], similarity=round(s, 3),
                    rationale=f"Схожие функции закреплены за разными подразделениями (сходство {s:.2f}).",
                    recommendation="Закрепить функцию за одним подразделением, для второго описать участие (RACI).",
                    confidence=0.7, method="similarity")
                out.append(f)
                cands.append({"finding_id": f.id, "a": a.text, "b": b.text,
                              "a_owner": unit_label(a.owner_units), "b_owner": unit_label(b.owner_units)})
        return out, cands

    # ------------------------------------------------------------ ConflictDetector
    def conflict_detector(self) -> list[Finding]:
        out: list[Finding] = []
        for doc, units, when in ((self.before, self.ub, "before"), (self.after, self.ua, "after")):
            other_units = self.ua if when == "before" else self.ub
            # R1: перекрёстное подчинение — должность подразделения X подчинена руководителю Y
            for ab, u in units.items():
                for num, pos in u.positions:
                    for x in units:
                        if x != ab and has_abbr(pos, x):
                            c = self._clause(doc, num)
                            status = self._persisted_r1(x, pos, when)
                            out.append(Finding(
                                id=self.next_id("K"), category="conflict", type="cross_subordination",
                                severity="high" if when == "after" else "info",
                                title=f"Перекрёстное подчинение: «{pos}» подчинён {u.name} ({ab})"
                                      + (" — устранено в новой редакции" if when == "before" and not status else ""),
                                units_before=[ab, x] if when == "before" else [],
                                units_after=[ab, x] if when == "after" else [],
                                evidence=[ev(c)],
                                rationale=(f"Работник подразделения {x} функционально подчинён руководителю {ab}. "
                                           f"Если {x} контролирует качество работы {ab}, возникает угроза независимости."),
                                recommendation="Исключить подчинение контролирующих работников контролируемому подразделению.",
                                confidence=0.8, method="rule"))
            # R2: консультирование и контроль (мониторинг) в одном подразделении при запрете внедрения процедур
            prohibition = next((c for c in doc.clauses if re.search(
                r"внедрять операционные и контрольные процедуры", c.text)), None)
            if when == "after" and prohibition:
                for ab in units:
                    own = [c for c in doc.clauses if ab in c.owner_units and len(c.owner_units) == 1]
                    consult = next((c for c in own if re.search(r"консультационных услуг", c.text)), None)
                    monitor = consult and re.search(r"мониторинг", consult.text + units[ab].name, re.I)
                    if consult and monitor:
                        existed = any(re.search(r"консультационных услуг", c.text)
                                      for c in self.before.clauses if ab in c.owner_units)
                        out.append(Finding(
                            id=self.next_id("K"), category="conflict", type="self_review",
                            severity="medium", title=f"Риск самопроверки: {units[ab].name} ({ab}) "
                                                     f"консультирует по контролям и осуществляет их мониторинг",
                            units_after=[ab],
                            evidence=[ev(consult, self._window(consult.text, "консультационных услуг")),
                                      ev(prohibition, "внедрять операционные и контрольные процедуры", "support")],
                            rationale=("Подразделение оказывает консультации по совершенствованию СУР/ВК/КУ и "
                                       "одновременно ведёт непрерывный мониторинг СВК; положение запрещает БВА "
                                       "внедрять контрольные процедуры." +
                                       (" Риск существовал и в предыдущей редакции." if existed else "")),
                            recommendation="Развести консультационную и мониторинговую роли или закрепить раскрытие КИ.",
                            confidence=0.65, method="rule"))
            # R3: участие в органах управления подконтрольных обществ
            for c in doc.clauses:
                if when == "after" and re.search(r"участвовать в органах управления подконтрольных", c.text):
                    mit = bool(re.search(r"конфликт|КИ", c.text))
                    in_before = any(re.search(r"участвовать в органах управления подконтрольных", x.text)
                                    for x in self.before.clauses)
                    out.append(Finding(
                        id=self.next_id("K"), category="conflict", type="governance_role",
                        severity="low" if mit else "high",
                        title="Главный аудитор может участвовать в органах управления подконтрольных обществ"
                              + (" (новое положение)" if not in_before else ""),
                        units_after=["ГА"],
                        evidence=[ev(c, self._window(c.text, "участвовать в органах управления"))],
                        rationale=("Совмещение аудиторской и управленческой роли создаёт потенциальный КИ. "
                                   + ("Документ предусматривает меры: раскрытие и заявление о КИ." if mit else "")),
                        recommendation="Контролировать исполнение мер по раскрытию КИ в отчётах БВА.",
                        confidence=0.8, method="rule"))
        return out

    def _persisted_r1(self, x: str, pos: str, when: str) -> bool:
        if when != "before":
            return True
        for u in self.ua.values():
            for _, p in u.positions:
                if has_abbr(p, x) and u.abbr != x:
                    return True
        return False

    # ------------------------------------------------------------ CrossRefChecker
    REF_RE = re.compile(r"(?:п\.|пункт(?:ом|а|у)?)\s*(\d{1,2}(?:\.\d{1,2}){1,3})(?:\s*и\s*(\d{1,2}(?:\.\d{1,2}){1,3}))?")

    def crossref_checker(self) -> list[Finding]:
        """Ссылка «п. X.Y» сохранилась дословно, но после перенумерации пункт X.Y
        означает другое, а прежнее содержание переехало в другой пункт."""
        out: list[Finding] = []
        for c in self.after.clauses:
            for m in self.REF_RE.finditer(c.text):
                broken: list[tuple[str, Clause, Clause, Clause]] = []
                for ref in [g for g in m.groups() if g]:
                    tgt_a, tgt_b = self.after.get(ref), self.before.get(ref)
                    if tgt_a is None:
                        out.append(self._defect("dangling_reference", "medium", c, m.group(0),
                                                f"Пункт {ref} отсутствует в документе."))
                        continue
                    if tgt_b is None:
                        continue
                    ta, tb = self._subtree_text(self.after, ref), self._subtree_text(self.before, ref)
                    if self.sim.matrix([ta], [tb])[0, 0] >= 0.5:
                        continue                  # содержание пункта не изменилось
                    i = c.text.find(m.group(0))
                    ctx = c.text[max(0, i - 250):i]    # смысл ссылки — в тексте перед ней
                    rel_now, rel_old = self.sim.matrix([ctx], [ta, tb])[0]
                    if rel_old <= rel_now + 0.03:
                        continue                  # ссылка стала точнее или не была осмысленной
                    cand = [x for x in self.after.clauses if x.depth == tgt_a.depth]
                    sims = self.sim.matrix([tb], [self._subtree_text(self.after, x.number) for x in cand])[0]
                    moved_to = cand[int(sims.argmax())]
                    if moved_to.number != ref:
                        broken.append((ref, tgt_a, tgt_b, moved_to))
                if not broken:
                    continue
                refs = ", ".join(b[0] for b in broken)
                new = ", ".join(b[3].number for b in broken)
                parts = [f"п. {r} теперь — «{a.text[:70]}…» (в ред. {self.before.edition}: «{b.text[:70]}…»)"
                         for r, a, b, _ in broken]
                fnd = self._defect("broken_cross_reference", "high", c, m.group(0),
                                   "После перенумерации ссылка указывает на другое содержание: "
                                   + "; ".join(parts) + f". Прежнее содержание — в п. {new}.")
                fnd.recommendation = f"Заменить ссылку на п. {refs} ссылкой на п. {new}."
                for _, a, _, mv in broken:
                    fnd.evidence.append(ev(a, role="support"))
                    fnd.evidence.append(ev(mv, role="target"))
                out.append(fnd)
        return out

    # ------------------------------------------------------------ DefectDetector
    def defect_detector(self) -> list[Finding]:
        out: list[Finding] = []
        for doc in (self.before, self.after):
            for c in doc.clauses:
                if c.is_leaf and len(re.sub(r"[\s;.,]", "", c.text)) == 0:
                    out.append(self._defect("empty_clause", "low", c, "",
                                            f"Пункт {c.number} ред. {doc.edition} не содержит текста."))
        # упоминание должности, которой нет в структуре новой редакции
        for c in self.after.clauses:
            for m in re.finditer(r"Директор(?:у|а)?\s+(операционного аудита|направления внутреннего аудита)", c.text):
                phrase = m.group(1)
                if not any(fuzz.partial_ratio(phrase, u.name.lower()) >= 95 and u.kind == "functional"
                           for u in self.ua.values()):
                    out.append(self._defect(
                        "unknown_role", "medium", c, m.group(0),
                        f"Должность «{m.group(0)}» не определена в разделе 3 ред. {self.after.edition} "
                        f"(там указаны: {', '.join('Директор ' + a for a in self.ua)})."))
        return out

    # ------------------------------------------------------------ helpers
    def _defect(self, typ: str, sev: str, c: Clause, quote: str, rationale: str) -> Finding:
        titles = {"broken_cross_reference": "Некорректная перекрёстная ссылка",
                  "dangling_reference": "Ссылка на несуществующий пункт",
                  "empty_clause": "Пустой пункт", "unknown_role": "Неизвестная должность"}
        return Finding(id=self.next_id("X"), category="defect", type=typ, severity=sev,
                       title=f"{titles[typ]}: ред. {c.edition}, п. {c.number}",
                       evidence=[ev(c, quote or c.text)], rationale=rationale,
                       recommendation="Исправить текст документа.", confidence=0.85, method="rule")

    @staticmethod
    def _clause(doc: Document, number: str) -> Clause:
        c = doc.get(number)
        assert c is not None, number
        return c

    @staticmethod
    def _subtree_text(doc: Document, number: str) -> str:
        return " ".join(c.text for c in doc.subtree(number))

    @staticmethod
    def _window(text: str, needle: str, size: int = 160) -> str:
        i = text.find(needle)
        if i < 0:
            return text[:size]
        start = max(0, i - size // 2)
        return text[start:i + len(needle) + size // 2]
