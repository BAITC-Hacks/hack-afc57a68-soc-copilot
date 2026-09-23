"""Shared, bounded and collision-safe upload handling for API and UI."""
from pathlib import Path
from typing import BinaryIO

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {'.pdf', '.docx', '.xlsx', '.xlsm'}


class DocumentInputError(ValueError):
    pass


def save_upload(stream: BinaryIO, filename: str | None, folder: str, role: str) -> str:
    name = (filename or '').replace('\\', '/').rsplit('/', 1)[-1]
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise DocumentInputError('Поддерживаются PDF, DOCX и XLSX. Выберите документ в одном из этих форматов.')
    target = Path(folder) / role / name
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open('wb') as out:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise DocumentInputError('Размер одного документа не должен превышать 25 МБ.')
            out.write(chunk)
    if not size:
        raise DocumentInputError('Файл пуст. Загрузите документ с текстом.')
    return str(target)
