"""Загрузка PDF / DOCX / XLSX в модель Document с пунктами."""
from __future__ import annotations

import re
from pathlib import Path

from app.models import Clause, Document
from app.parser.clauses import split_into_clauses
from app.uploads import DocumentInputError, MAX_UPLOAD_BYTES


def _meta_from_text(first_page: str) -> dict:
    t = re.sub(r"\s+", " ", first_page)
    ed = re.search(r"редакция\s*(?:No|№|N)?\s*(\d+)", t, re.I)
    prot = re.search(r"Протокол\s*(?:No|№|N)?\s*(\d+)\s*от\s*«?(\d{1,2})»?\s*(\w+)\s*(\d{4})", t, re.I)
    title = re.search(r"(ПОЛОЖЕНИЕ\s+О\s+[А-ЯЁ\s«»\"]+?)(?:\(|АО|$)", t)
    return {
        "edition": ed.group(1) if ed else "",
        "approved": (f"Протокол № {prot.group(1)} от {prot.group(2)} {prot.group(3)} {prot.group(4)}"
                     if prot else ""),
        "title": title.group(1).strip().capitalize() if title else "",
    }


def load_pdf(path: str, doc_id: str) -> tuple[Document, list[dict]]:
    import pymupdf  # PyMuPDF

    # Deduplicate only overlapping PDF text blocks, never repeated obligations.
    # Opening bytes also avoids a leaked native file handle on malformed PDFs on Windows.
    with pymupdf.open(stream=Path(path).read_bytes(), filetype='pdf') as pdf:
        if pdf.needs_pass:
            raise DocumentInputError('PDF защищён паролем. Загрузите доступную для чтения копию.')
        pages = []
        for i, page in enumerate(pdf):
            seen, blocks = set(), []
            for block in page.get_text('blocks'):
                if block[6] != 0:
                    continue
                if block[4].strip().isdigit() and block[1] > page.rect.height * 0.9:
                    continue  # A footer may occur first in PDF content-stream order.
                key = (tuple(round(v, 1) for v in block[:4]), block[4])
                if key not in seen:
                    seen.add(key)
                    blocks.append(block[4])
            pages.append((i + 1, '\n'.join(blocks)))
    meta = _meta_from_text(pages[0][1] if pages else "")
    clauses, anomalies = split_into_clauses(pages, doc_id, meta["edition"])
    doc = Document(doc_id=doc_id, file=Path(path).name, kind="pdf", clauses=clauses, **meta)
    return doc, anomalies


def _docx_paragraph_texts(path: str) -> list[str]:
    """Возвращает абзацы DOCX, восстанавливая автонумерацию списков (w:numPr)."""
    import docx
    from docx.table import Table

    d = docx.Document(path)
    counters: dict[tuple[str, int], int] = {}
    out: list[str] = []
    for p in d.iter_inner_content():
        if isinstance(p, Table):
            for row in p.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    out.append(' | '.join(dict.fromkeys(cells)))
            continue
        text = p.text.strip()
        if not text:
            continue
        numpr = p._p.pPr.numPr if p._p.pPr is not None else None
        if numpr is not None and numpr.numId is not None:
            num_id = str(numpr.numId.val)
            lvl = int(numpr.ilvl.val) if numpr.ilvl is not None else 0
            counters[(num_id, lvl)] = counters.get((num_id, lvl), 0) + 1
            for k in [k for k in counters if k[0] == num_id and k[1] > lvl]:
                del counters[k]
            prefix = ".".join(str(counters.get((num_id, l), 1)) for l in range(lvl + 1))
            if not re.match(r"^\d", text):
                text = f"{prefix}. {text}"
        out.append(text)
    return out


def load_docx(path: str, doc_id: str) -> tuple[Document, list[dict]]:
    paras = _docx_paragraph_texts(path)
    text = "\n".join(paras)
    meta = _meta_from_text(text[:3000])
    # У DOCX нет страниц: условная «страница» = блок из 40 абзацев
    pages = [(i // 40 + 1, "\n".join(paras[i:i + 40])) for i in range(0, len(paras), 40)]
    clauses, anomalies = split_into_clauses(pages, doc_id, meta["edition"])
    doc = Document(doc_id=doc_id, file=Path(path).name, kind="docx", clauses=clauses, **meta)
    return doc, anomalies


def load_xlsx(path: str, doc_id: str, edition: str = "") -> tuple[Document, list[dict]]:
    """Каждая непустая строка листа — отдельный «пункт» с адресом Лист!A{row}."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    clauses: list[Clause] = []
    for sheet_no, ws in enumerate(wb.worksheets, 1):
        for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            vals = [str(v).strip() for v in row if v is not None and str(v).strip()]
            if not vals:
                continue
            number = f"{ws.title}!A{r_idx}"
            clauses.append(Clause(
                clause_id=f"{doc_id}:{number}", doc_id=doc_id, edition=edition,
                number=number, text=" | ".join(vals), page=sheet_no, section=ws.title,
            ))
    wb.close()
    doc = Document(doc_id=doc_id, file=Path(path).name, kind="xlsx", edition=edition, clauses=clauses)
    return doc, []


def load_any(path: str, doc_id: str) -> tuple[Document, list[dict]]:
    ext = Path(path).suffix.lower()
    loaders = {'.pdf': load_pdf, '.docx': load_docx, '.xlsx': load_xlsx, '.xlsm': load_xlsx}
    if ext not in loaders:
        raise DocumentInputError(f'Неподдерживаемый формат: {ext}')
    if Path(path).stat().st_size > MAX_UPLOAD_BYTES:
        raise DocumentInputError('Размер одного документа не должен превышать 25 МБ.')
    try:
        doc, anomalies = loaders[ext](path, doc_id)
    except DocumentInputError:
        raise
    except Exception as exc:
        raise DocumentInputError(f'Не удалось прочитать {Path(path).name}. Проверьте формат и целостность файла.') from exc
    if not any(len(c.text.strip()) > 2 for c in doc.clauses):
        raise DocumentInputError(f'{doc.file}: не найдены текстовые пункты. Для скана нужен OCR; для положения — нумерованные разделы.')
    if doc.kind == 'docx':
        doc.warnings.append('DOCX: номера страниц условные (блоки по 40 абзацев). Для точных страниц используйте PDF.')
    if doc.kind == 'xlsx':
        doc.warnings.append('XLSX: источники указаны по листам и строкам. Анализ функций требует нумерованного положения в PDF/DOCX.')
    return doc, anomalies
