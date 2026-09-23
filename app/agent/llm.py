"""Необязательный LLM-слой (OpenAI). Включается, если задан OPENAI_API_KEY.

1. review_gray  — LLM-судья для пограничных случаев потери функций;
2. review_dups  — LLM-судья для кандидатов в дублирование;
3. executive_summary — резюме для эксперта строго по найденным выводам;
4. chat — вопросы эксперта к документам через Function Calling
   (инструменты search_clauses / get_clause / list_findings).

Без ключа все функции возвращают None, и агент работает в детерминированном режиме.
"""
from __future__ import annotations

import json
from typing import Any

from app import config

SYSTEM = (
    "Ты аналитик организационных структур и внутренних нормативных документов. "
    "Используй ТОЛЬКО предоставленный текст пунктов. Не делай утверждений, которых нет в тексте. "
    "Отвечай строго в формате JSON без пояснений вне JSON."
)


def _client():
    if not config.USE_LLM:
        return None
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY)


def _json_call(prompt: str) -> dict | None:
    client = _client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # сеть, лимиты, невалидный JSON — агент продолжает без LLM
        print(f"[llm] fallback: {exc}")
        return None


def review_gray(items: list[dict]) -> dict[str, dict] | None:
    if not items:
        return {}
    prompt = (
        "Для каждой пары определи, что произошло с функцией при переходе от старой редакции к новой.\n"
        "verdict: lost (функции нет) | partially_lost (часть содержания утрачена) | "
        "moved (передана другому подразделению) | reworded (переформулирована без потери смысла).\n"
        "lost_fragment — дословный фрагмент СТАРОГО текста, который утрачен (или пустая строка).\n"
        'Верни JSON {"items":[{"finding_id":"...","verdict":"...","rationale":"одно предложение",'
        '"lost_fragment":"..."}]}\n\n' + json.dumps(items, ensure_ascii=False)
    )
    data = _json_call(prompt)
    if not data:
        return None
    return {x["finding_id"]: x for x in data.get("items", []) if "finding_id" in x}


def review_dups(items: list[dict]) -> dict[str, dict] | None:
    if not items:
        return {}
    prompt = (
        "Для каждой пары функций разных подразделений реши, является ли это реальным дублированием "
        "(одна и та же работа закреплена за двумя подразделениями), а не типовой обязанностью "
        "руководителя или взаимодополняющими ролями.\n"
        'Верни JSON {"items":[{"finding_id":"...","is_duplication":true,"rationale":"одно предложение"}]}\n\n'
        + json.dumps(items, ensure_ascii=False)
    )
    data = _json_call(prompt)
    if not data:
        return None
    return {x["finding_id"]: x for x in data.get("items", []) if "finding_id" in x}


def executive_summary(report_brief: dict) -> str | None:
    prompt = (
        "Составь резюме для эксперта (5–7 предложений, русский язык) ТОЛЬКО по этим выводам. "
        "Упоминай номера пунктов в формате «п. 5.6.2 ред. 8». "
        'Верни JSON {"summary":"..."}\n\n' + json.dumps(report_brief, ensure_ascii=False)
    )
    data = _json_call(prompt)
    return data.get("summary") if data else None


# ---------------------------------------------------------------- Function Calling chat
TOOLS = [
    {"type": "function", "function": {
        "name": "search_clauses",
        "description": "Поиск пунктов документов по смыслу. Возвращает номер, страницу, владельца и текст.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "doc_id": {"type": "string", "description": "D_BEFORE — старая редакция, D_AFTER — новая; можно использовать ID из результатов (например D8, D9). Пусто — оба документа."},
            "top_k": {"type": "integer", "default": 5}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_clause",
        "description": "Получить полный текст пункта по номеру.",
        "parameters": {"type": "object", "properties": {
            "doc_id": {"type": "string", "description": "ID из результатов поиска (например D8, D9), либо D_BEFORE / D_AFTER."}, "number": {"type": "string"}},
            "required": ["doc_id", "number"]}}},
    {"type": "function", "function": {
        "name": "list_findings",
        "description": "Список выводов агента по категории: structure|function|duplication|conflict|defect.",
        "parameters": {"type": "object", "properties": {"category": {"type": "string"}},
                       "required": ["category"]}}},
]


def chat(question: str, tool_impl: dict[str, Any], history: list[dict] | None = None,
         max_steps: int = 5) -> dict | None:
    """Агентный цикл: модель сама решает, какие инструменты вызвать, и отвечает со ссылками."""
    client = _client()
    if client is None:
        return None
    messages = [{"role": "system", "content":
                 "Ты помощник эксперта по реорганизации. Отвечай по-русски, опираясь только на результаты "
                 "инструментов. Каждое утверждение сопровождай ссылкой вида [D8 п. 5.6.2, стр. 10]. "
                 "Если данных нет — так и скажи."}]
    messages += history or []
    messages.append({"role": "user", "content": question})
    calls_log = []
    for _ in range(max_steps):
        resp = client.chat.completions.create(model=config.LLM_MODEL, temperature=0,
                                              messages=messages, tools=TOOLS)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"answer": msg.content, "tool_calls": calls_log}
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = tool_impl[tc.function.name](**args)
            calls_log.append({"tool": tc.function.name, "args": args})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)[:12000]})
    return {"answer": "Превышено число шагов агента.", "tool_calls": calls_log}
