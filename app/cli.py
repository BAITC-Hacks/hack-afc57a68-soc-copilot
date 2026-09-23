"""CLI: python -m app.cli BEFORE AFTER [--out path_without_ext]"""
import argparse
import json

from app.pipeline import analyze
from app.report import to_markdown


def main():
    p = argparse.ArgumentParser(description="OrgTrace: сравнение документов до/после реорганизации")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--out", default="orgtrace_report")
    a = p.parse_args()
    report = analyze(a.before, a.after, on_step=lambda r: print(f"[{r['tool']}] {r['summary']}"))
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write(to_markdown(report))
    print(json.dumps(report.summary, ensure_ascii=False, indent=2))
    print(f"Сохранено: {a.out}.json, {a.out}.md")


if __name__ == "__main__":
    main()
