"""Seeded, synthetic regulation pairs with a human-readable ground-truth manifest.

python -m app.generate_cases --out runs/generated --seed 42 --clauses-per-section 24
No source documents or external models are used.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import zipfile
from pathlib import Path


def case_texts(seed: int = 42, clauses_per_section: int = 24) -> tuple[list[str], list[str], dict]:
    rng = random.Random(seed)
    before = ['ПОЛОЖЕНИЕ О ВНУТРЕННЕМ АУДИТЕ', 'Редакция № 1', 'Синтетический тестовый документ',
        '1. Общие положения', '1.1. Положение определяет функции и ответственность подразделений Общества.',
        '2. Термины и определения', '2.1. Контроль качества означает проверку полноты и обоснованности аудиторских выводов.',
        '3. Организационная структура', '3.4. Блок состоит из следующих структурных подразделений:',
        'а. Департамент контроля качества (ДКК).', 'б. Департамент мониторинга (ДМ).',
        '3.5. Главному аудитору подчиняются:', 'а. Директор ДКК.', 'б. Директор ДМ.',
        '3.6. Директору ДКК подчиняются работники в составе следующих должностей:',
        'а. Директор проектов ДМ.', 'б. Старший аудитор ДКК.',
        '4. Полномочия', '4.1. Главный аудитор обеспечивает независимость проверок.',
        '5. Права и обязанности', '5.1. Директор ДКК обязан:',
        '5.1.1. Проводить независимую оценку качества аудиторских процедур и оформлять заключение о выявленных недостатках.',
        '5.1.2. Согласовывать методологию проведения аудиторских проверок и контролировать применение стандартов качества.',
        '5.1.3. Осуществлять мониторинг исполнения корректирующих мероприятий и проверять устранение выявленных нарушений.',
        '5.1.4. Формировать отчёт о результатах оценки качества на ежеквартальной основе и по итогам года с приложением подтверждающих материалов.',
        '5.1.5. Вести специальный реестр резервных экспертов по информационной безопасности и ежегодно подтверждать их квалификационные сертификаты.',
        '5.2. Директор ДМ обязан:',
        '5.2.1. Проводить анализ устойчивости операционных процессов и представлять рекомендации руководству Общества.',
        '5.2.2. Обеспечивать хранение материалов завершённых мониторинговых мероприятий в электронном архиве.',
        '5.3. Работники БВА обязаны:', '5.3.1. Не внедрять операционные и контрольные процедуры в проверяемых подразделениях.']
    after = ['ПОЛОЖЕНИЕ О ВНУТРЕННЕМ АУДИТЕ', 'Редакция № 2', 'Синтетический тестовый документ',
        '1. Общие положения', before[4], '2. Термины и определения', before[6],
        '3. Организационная структура', before[8],
        'а. Департамент качества аудита (ДКА).', 'б. Департамент методологии качества (ДМК).', 'в. Департамент мониторинга (ДМ).',
        '3.5. Главному аудитору подчиняются:', 'а. Директор ДКА.', 'б. Директор ДМК.', 'в. Директор ДМ.',
        '3.6. Директору ДКА подчиняются работники в составе следующих должностей:', 'а. Директор проектов ДМ.',
        '3.7. Директору ДМ подчиняются работники в составе следующих должностей:', 'а. Директор проектов ДМ.',
        '4. Полномочия', '4.1. Главный аудитор вправе участвовать в органах управления подконтрольных обществ.',
        '5. Права и обязанности', '5.1. Директор ДКА обязан:',
        before[21], before[23].replace('5.1.3.', '5.1.2.'),
        '5.2. Директор ДМК обязан:', before[22].replace('5.1.2.', '5.2.1.'),
        before[24].replace('5.1.4.', '5.2.2.').replace('на ежеквартальной основе и по итогам года ', ''),
        '5.3. Директор ДМ обязан:', before[21].replace('5.1.1.', '5.3.1.'),
        before[27].replace('5.2.1.', '5.3.2.'), before[28].replace('5.2.2.', '5.3.3.'),
        '5.3.4. Обеспечивать оказание консультационных услуг по внедрению контрольных процедур и осуществлять мониторинг тех же процедур.',
        '5.4. Работники БВА обязаны:', '5.4.1. Не внедрять операционные и контрольные процедуры в проверяемых подразделениях.',
        '5.4.2. ;']
    topics = ['планирования проверок', 'подготовки отчётности', 'ведения реестров', 'обмена информацией',
              'документирования решений', 'согласования рекомендаций', 'обработки замечаний', 'управления архивом']
    for section in range(6, 19):
        title = f'{section}. Порядок {topics[(section - 6) % len(topics)]}'
        before.append(title)
        after.append(title)
        for n in range(1, clauses_per_section + 1):
            days = rng.choice([3, 5, 10, 15, 20])
            line = (f'{section}.{n}. Ответственное подразделение обеспечивает регистрацию материалов '
                    f'по направлению {topics[rng.randrange(len(topics))]} в течение {days} рабочих дней. '
                    'Результаты согласуются с руководителем и сохраняются вместе с подтверждающими документами.')
            before.append(line)
            after.append(line)
    before.extend(['19. Заключительные положения', '19.1. Доступ к материалам предоставляется согласно п. 5.2.2.',
                   '20. Приложения', '20.1. Форма реестра экспертов прилагается к настоящему Положению.'])
    after.extend(['19. Заключительные положения', '19.1. Доступ к материалам предоставляется согласно п. 5.9.9.',
                  '20. Дополнительный раздел', '20.1. Контроль исполнения возложен на Главного аудитора.',
                  '21. Приложения', '21.1. Форма отчётности заменяет форму реестра экспертов.'])
    manifest = {'seed': seed, 'clauses_per_section': clauses_per_section, 'synthetic': True,
        'scenarios': [
            {'kind': 'split', 'before': ['3.4.а'], 'after': ['3.4.а', '3.4.б'], 'description': 'ДКК разделён на ДКА и ДМК; функции распределены между ними.'},
            {'kind': 'lost', 'before': ['5.1.5'], 'after': [], 'description': 'Удалён реестр резервных экспертов и подтверждение сертификатов.'},
            {'kind': 'partial', 'before': ['5.1.4'], 'after': ['5.2.2'], 'description': 'Удалены ежеквартальная периодичность и годовой цикл отчётности.'},
            {'kind': 'duplication', 'before': [], 'after': ['5.1.1', '5.3.1'], 'description': 'Независимая оценка качества закреплена одновременно за ДКА и ДМ.'},
            {'kind': 'conflicting_subordination', 'before': ['3.6.а'], 'after': ['3.6.а', '3.7.а'], 'description': 'Директор проектов ДМ подчинён двум руководителям.'},
            {'kind': 'self_review', 'before': [], 'after': ['5.3.4', '5.4.1'], 'description': 'Консультирование по внедрению и мониторинг тех же процедур.'},
            {'kind': 'dangling_reference', 'before': ['19.1'], 'after': ['19.1'], 'description': 'Ссылка на отсутствующий пункт 5.9.9.'},
            {'kind': 'empty_clause', 'before': [], 'after': ['5.4.2'], 'description': 'Пустой пункт.'},
            {'kind': 'renumbering', 'before': ['20.1'], 'after': ['21.1'], 'description': 'Добавлен раздел 20, приложение перенумеровано и изменено.'},
        ]}
    return before, after, manifest


def _pdf(lines: list[str], path: Path):
    import pymupdf
    font = pymupdf.Font('cjk')  # Bundled Droid Sans Fallback includes Cyrillic on all platforms.
    doc = pymupdf.open()
    page, y = None, 70
    for text in lines:
        # Fixed metrics and seeded content make pagination reproducible.
        words, wrapped, current = text.split(), [], ''
        for word in words:
            proposed = (current + ' ' + word).strip()
            if font.text_length(proposed, fontsize=10) > 475 and current:
                wrapped.append(current)
                current = word
            else:
                current = proposed
        wrapped.append(current)
        if page is None or y + len(wrapped) * 15 > 780:
            page = doc.new_page(width=595, height=842)
            page.insert_font(fontname='Body', fontbuffer=font.buffer)
            page.insert_text((290, 817), str(len(doc)), fontsize=9)
            y = 60
        for line in wrapped:
            page.insert_text((60, y), line, fontname='Body', fontsize=10)
            y += 15
        y += 5
    doc.set_metadata({'title': 'OrgTrace synthetic regulation', 'creationDate': 'D:20260101000000Z', 'modDate': 'D:20260101000000Z'})
    doc.subset_fonts()
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()


def _docx(lines: list[str], path: Path):
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)
    for i, line in enumerate(lines):
        doc.add_paragraph(line, style='Title' if i == 0 else 'Normal')
    doc.core_properties.created = doc.core_properties.modified = dt.datetime(2026, 1, 1)
    doc.save(path)
    # ZIP timestamps must not make identical fixture content produce new hashes.
    with zipfile.ZipFile(path) as src:
        entries = [(info.filename, src.read(info.filename)) for info in src.infolist()]
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as out:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(info, data)


def generate(out: Path, seed: int = 42, clauses_per_section: int = 24) -> dict:
    if not 1 <= clauses_per_section <= 50:
        raise ValueError('clauses_per_section must be between 1 and 50')
    out.mkdir(parents=True, exist_ok=True)
    before, after, manifest = case_texts(seed, clauses_per_section)
    manifest['files'] = {}
    for name, lines in [('version_a', before), ('version_b', after)]:
        for ext, writer in [('pdf', _pdf), ('docx', _docx)]:
            path = out / f'{name}.{ext}'
            writer(lines, path)
            manifest['files'][path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('runs/generated'))
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--clauses-per-section', type=int, default=24)
    args = parser.parse_args()
    result = generate(args.out, args.seed, args.clauses_per_section)
    print(f'Generated {len(result["files"])} files and manifest in {args.out}')


if __name__ == '__main__':
    main()
