"""Wording of the GeoAgent chat, in English and in Russian.

``--ru`` (parsed in src/config.py into ``CHAT_LANG``) picks ``RU``; without it the
chat is English. "The chat" is everything the user reads in the panel plus the
context block prepended to every message, so the agent answers in the language the
panel speaks.

Both dictionaries are looked up by the same keys: a missing translation raises a
KeyError on the spot instead of silently falling back to the other language.
"""

from .config import CHAT_LANG

EN = {
    # Tool call -> the line shown in the chat while it runs. Anything not listed
    # passes silently; the agent narrates it in its own reply.
    "tool_notices": {
        "run_simulation_in_geoview":
            "🔧 Starting the JutulDarcy run — the first one may take a few minutes…",
        "load_model_in_geoview": "📂 Loading the model in GeoView…",
        "prepare_optimization_in_geoview": "📝 Filling in the optimization form…",
        # GeoAgentPro computes in its own process instead of pressing GeoView's button.
        "simulate_reservoir_for_geoview":
            "🔧 Starting the JutulDarcy run — the first one may take a few minutes…",
    },
    # arg key -> (plain-language headline, field label, render as a code block)
    "approval_args": {
        "Command": ("GeoAgent wants to run a terminal command", "Command", True),
        "Code": ("GeoAgent wants to run Julia code", "Code", True),
        "Filepath": ("GeoAgent wants to overwrite a file", "File", False),
        "Query": ("GeoAgent is refining a search query", "Query", False),
    },

    # ── Panel chrome ──
    "fab_tooltip": "Chat with GeoAgent",
    "empty_state": "Ask the agent, or ask it to simulate the loaded model.",
    "input_placeholder": "Type a message…",
    "input_placeholder_edit": "Correct the value and press Enter…",
    "input_placeholder_respond": "Tell the agent what to do differently…",

    # ── Approval card ──
    "approval_headline": "GeoAgent asks for confirmation",
    "approval_hint": (
        "Rejecting does not end the conversation: the agent is told and offers "
        "something else."
    ),
    "approval_reject": "Reject",
    "approval_accept": "Allow",
    "approval_pending": "⏸ Your confirmation is required.",
    "approval_edited": "✏ Corrected and approved: {value}",
    "approval_answer": "💬 Reply to the agent: {value}",
    "approval_accepted": "✓ Approved.",
    "approval_rejected": "✗ Rejected.",

    # ── Model summary (the context block) ──
    "context_header": "[GeoView context]",
    "no_model": "No model is loaded.",
    "loaded_model": "Loaded model: {path}",
    "grid": "Grid: {nx}x{ny}x{nz}, {total} cells in total, {active} active",
    "phases": "Phases: {phases}",
    "dates": "Dates: from {start} to {last}, {steps} steps",
    "wells_named": "Wells: {count} ({names})",
    "wells_count": "Wells: {count}",
    "results_present": "Simulation results: available ({attributes})",
    "results_absent": "Simulation results: the model has not been simulated yet",
    "user_message": "User message: {text}",

    # ── Pro preamble ──
    "pro_header": "[GeoView context] ",
    "pro_model": "Loaded model: {path}. ",
    "pro_no_model": "No model is loaded. ",
    "pro_instructions": "Results directory: {directory}. Answer in English.",

    # ── System lines ──
    "no_sdk": (
        "⚠ Chat unavailable: the langgraph-sdk package is not installed "
        "(pip install langgraph-sdk)."
    ),
    "send_failed": "⚠ Could not reach the agent: {error}",
    "resume_failed": "⚠ Could not resume the agent: {error}",
    "states_no_model": (
        "⚠ The run is ready, but no model is loaded in GeoView — press Load first."
    ),
    "states_applied": "✓ The run was picked up in the 3D view tab.",
    "load_no_path": "⚠ The agent did not say which model to open.",
    "load_busy": "⚠ GeoView is already loading a model — request skipped.",
    "load_started": "📂 Opening the model: {path}",
    "simulate_no_model": "⚠ Cannot simulate: no model is loaded in GeoView.",
    "simulate_busy": "⚠ A run is already in progress — request skipped.",
    "simulate_started": (
        "▶ Starting the run — the result will appear in the 3D view tab."
    ),
    "opt_missing": "⚠ The optimization parameters are missing fields: {fields}",
    "opt_filled": (
        "📝 The optimization form is filled in — check the values and press Optimize."
    ),
    "result_failed": "Simulation failed.",
    "result_unknown": "⚠ Unknown result type: {type}",
}

RU = {
    "tool_notices": {
        "run_simulation_in_geoview":
            "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
        "load_model_in_geoview": "📂 Загружаю модель в GeoView…",
        "prepare_optimization_in_geoview": "📝 Заполняю форму оптимизации…",
        "simulate_reservoir_for_geoview":
            "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
    },
    "approval_args": {
        "Command": ("GeoAgent хочет выполнить команду в терминале", "Команда", True),
        "Code": ("GeoAgent хочет выполнить Julia-код", "Код", True),
        "Filepath": ("GeoAgent хочет перезаписать файл", "Файл", False),
        "Query": ("GeoAgent уточняет поисковый запрос", "Запрос", False),
    },

    # ── Panel chrome ──
    "fab_tooltip": "Чат с GeoAgent",
    "empty_state": "Спросите агента или попросите посчитать загруженную модель.",
    "input_placeholder": "Напишите сообщение…",
    "input_placeholder_edit": "Исправьте значение и нажмите Enter…",
    "input_placeholder_respond": "Напишите агенту, что сделать иначе…",

    # ── Approval card ──
    "approval_headline": "GeoAgent просит подтверждение",
    "approval_hint": (
        "Отклонение не прерывает диалог: агент узнает об отказе и предложит другое."
    ),
    "approval_reject": "Отклонить",
    "approval_accept": "Разрешить",
    "approval_pending": "⏸ Требуется ваше подтверждение.",
    "approval_edited": "✏ Исправлено и подтверждено: {value}",
    "approval_answer": "💬 Ответ агенту: {value}",
    "approval_accepted": "✓ Подтверждено.",
    "approval_rejected": "✗ Отклонено.",

    # ── Model summary (the context block) ──
    "context_header": "[Контекст GeoView]",
    "no_model": "Модель не загружена.",
    "loaded_model": "Загруженная модель: {path}",
    "grid": "Сетка: {nx}x{ny}x{nz}, ячеек всего {total}, активных {active}",
    "phases": "Фазы: {phases}",
    "dates": "Даты: с {start} по {last}, шагов {steps}",
    "wells_named": "Скважин: {count} ({names})",
    "wells_count": "Скважин: {count}",
    "results_present": "Результаты расчёта: есть ({attributes})",
    "results_absent": "Результаты расчёта: модель ещё не считалась",
    "user_message": "Сообщение пользователя: {text}",

    # ── Pro preamble ──
    "pro_header": "[Контекст GeoView] ",
    "pro_model": "Загруженная модель: {path}. ",
    "pro_no_model": "Модель не загружена. ",
    "pro_instructions": "Каталог результатов: {directory}. Отвечай по-русски.",

    # ── System lines ──
    "no_sdk": (
        "⚠ Чат недоступен: не установлен пакет langgraph-sdk "
        "(pip install langgraph-sdk)."
    ),
    "send_failed": "⚠ Не удалось связаться с агентом: {error}",
    "resume_failed": "⚠ Не удалось продолжить работу агента: {error}",
    "states_no_model": (
        "⚠ Расчёт готов, но в GeoView не загружена модель — сначала нажмите Load."
    ),
    "states_applied": "✓ Расчёт подхватился во вкладке 3D view.",
    "load_no_path": "⚠ Агент не указал, какую модель открыть.",
    "load_busy": "⚠ GeoView уже загружает модель — запрос пропущен.",
    "load_started": "📂 Открываю модель: {path}",
    "simulate_no_model": "⚠ Расчёт невозможен: в GeoView не загружена модель.",
    "simulate_busy": "⚠ Расчёт уже идёт — запрос пропущен.",
    "simulate_started": (
        "▶ Запускаю расчёт — результат появится во вкладке 3D view."
    ),
    "opt_missing": "⚠ В параметрах оптимизации не хватает полей: {fields}",
    "opt_filled": (
        "📝 Форма оптимизации заполнена — проверьте значения и нажмите Optimize."
    ),
    "result_failed": "Ошибка расчёта.",
    "result_unknown": "⚠ Неизвестный тип результата: {type}",
}

# Bound once at import: the language is a launch flag, not a runtime setting.
TEXT = RU if CHAT_LANG == "ru" else EN
