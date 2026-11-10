"""In-app chat with GeoAgent + result auto-pickup.

A floating button on the Home tab opens a chat panel talking to the real GeoAgent
(served by a local ``langgraph dev`` server). When the agent computes a reservoir
model it writes a result artifact following the GeoView contract (see
``GeoAgent/src/GeoAgent/tools/geoview_bridge.py``). A background watcher notices new
results and routes them to a display handler; ``field_states`` results are applied to
the loaded model so the 3D view updates automatically.
"""
import asyncio
import logging
from datetime import timedelta

import numpy as np
from trame.app import asynchronous
from trame.widgets import html
from trame.widgets import vuetify3 as vuetify

try:
    from langgraph_sdk import get_client
except ModuleNotFoundError:
    # Only the chat needs it; a plain GeoView launch must still start without it.
    get_client = None

# AGENT_PROFILE picks which agent is on the other end of the socket. The public
# agent receives its legacy text preamble; GeoAgentPro receives structured state.
from .agent_results import (
    DuplicateAgentResultError,
    InvalidAgentResultError,
    SourceModelMismatchError,
    TransientAgentResultError,
    apply_staged_field_states,
    build_model_snapshot,
    load_field_states,
    load_optimization_result,
    read_latest_run_id,
    read_run_manifest,
    source_model_id,
    to_spatial_states,
)
from .config import (
    AGENT_ASSISTANT_ID,
    AGENT_GRAPH,
    AGENT_PROFILE,
    AGENT_RESULT_DIR,
    FIELD,
    agent_enabled,
    ctrl,
    state,
)

logger = logging.getLogger(__name__)

# GeoAgent langgraph server (started by app.py with --agent).
AGENT_URL = "http://127.0.0.1:2024"
# connect, read, write and pool timeouts; a cold Jutul run can exceed five minutes.
_AGENT_TIMEOUT = (5.0, 1800.0, 300.0, 5.0)

_INJECTION_CONTROL_COLUMNS = {
    "RATE": ("SURFACE_RATE", "sm3/day"),
    "RESV": ("RESERVOIR_RATE", "m3/day"),
    "BHP": ("BHP", "bar"),
    "THP": ("THP", "bar"),
}
_PRODUCTION_CONTROL_COLUMNS = {
    "ORAT": ("OIL_RATE", "sm3/day"),
    "WRAT": ("WATER_RATE", "sm3/day"),
    "GRAT": ("GAS_RATE", "sm3/day"),
    "LRAT": ("SURFACE_LIQUID_RATE", "sm3/day"),
    "RESV": ("RESERVOIR_LIQUID_RATE", "m3/day"),
    "BHP": ("BHP", "bar"),
    "THP": ("THP", "bar"),
}

(AGENT_RESULT_DIR / "results").mkdir(parents=True, exist_ok=True)

state.agentMode = bool(agent_enabled)
state.showChat = False
state.chat_messages = []
state.chat_input = ""
state.chat_busy = False
state.agent_result_dir = str(AGENT_RESULT_DIR)

# Pending tool approval (a LangGraph interrupt), or None. Rendered as a card in
# the panel; the run stays paused server-side until it is answered.
state.pending_approval = None

# LangGraph conversation thread (kept across messages for dialogue context).
_thread_id = None
_announced_tool_call_ids = set()
_forecast_notice_state = {"running": False, "result_pending": False}


# ── Tool approvals (LangGraph interrupts) ─────────────────────────────────
#
# GeoAgent pauses the graph with ``interrupt([HumanInterrupt])`` before anything
# irreversible: a shell command, Julia code, overwriting a file. The pause lives
# in the checkpointed thread, so closing the panel does not cancel or approve it
# — only an explicit answer resumes the run.
#
# The audience here is reservoir engineers, not developers, so the card leads
# with a plain sentence and shows the raw argument underneath.

# arg key -> (plain-language headline, field label, render as a code block)
_APPROVAL_ARGS = {
    "Command": ("GeoAgent хочет выполнить команду в терминале", "Команда", True),
    "Code": ("GeoAgent хочет выполнить Julia-код", "Код", True),
    "Filepath": ("GeoAgent хочет перезаписать файл", "Файл", False),
    "Query": ("GeoAgent уточняет поисковый запрос", "Запрос", False),
}

_OPTIMIZATION_APPROVAL_LABELS = {
    "model_name": "Модель",
    "objective": "Цель",
    "method": "Метод",
    "baseline": "Базовый сценарий",
    "well": "Скважина",
    "horizon_months": "Горизонт, мес.",
    "lower_bhp_bar": "Нижняя граница давления, бар",
    "upper_bhp_bar": "Верхняя граница давления, бар",
    "forecast_evaluations": "Лимит прогнозов",
    "bounds_bar": "Границы давления по скважинам, бар",
    "injection_rate_bounds_sm3_per_day": "Границы расхода закачки, ст. м³/сут",
    "production_oil_rate_bounds_sm3_per_day": "Границы дебита нефти, ст. м³/сут",
    "group_injection_limit": "Общий лимит закачки по группе, ст. м³/сут",
    "objective_wells": "Скважины, чья добыча учитывается",
    "economics": "Экономические параметры",
    "max_iterations": "Лимит итераций",
}
_OPTIMIZATION_APPROVAL_VALUES = {
    "field_cumulative_oil": "Накопленная добыча нефти по модели",
    "group_cumulative_oil": "Накопленная добыча нефти по группе скважин",
    "well_cumulative_oil": "Накопленная добыча нефти по выбранной скважине",
    "bhp_grid": "Сравнение трёх забойных давлений",
    "bhp_refine": "Сравнение давлений с уточнением около лучшего варианта",
    "bhp_adjoint": "Градиентный поиск помесячных режимов (adjoint + L-BFGS)",
    "discounted_npv": "Дисконтированный NPV",
    "continue_final_scheduled_controls": "Продолжение текущих режимов",
}
_NPV_ECONOMICS_LABELS = {
    "currency": "Валюта",
    "oil_price": "Цена нефти за ст. м³",
    "gas_price": "Цена газа за ст. м³",
    "produced_water_cost": "Стоимость обработки добытой воды за ст. м³",
    "water_injection_cost": "Стоимость закачки воды за ст. м³",
    "gas_injection_cost": "Стоимость закачки газа за ст. м³",
    "discount_rate_percent": "Ставка дисконтирования, % в год",
}


def _extract_interrupt(part):
    """Return the HumanInterrupt dict of an ``__interrupt__`` event, else None."""
    data = getattr(part, "data", None)
    if not isinstance(data, dict):
        return None
    items = data.get("__interrupt__")
    if not items:
        return None
    first = items[0] if isinstance(items, (list, tuple)) else items
    value = first.get("value") if isinstance(first, dict) else None
    # GeoAgent calls interrupt([request]), so the value is a one-item list.
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    return value if isinstance(value, dict) else None


def _build_approval(request):
    """Turn a HumanInterrupt into the card model the panel renders."""
    action_request = request.get("action_request") or {}
    raw_args = action_request.get("args") or {}
    config = request.get("config") or {}

    preview_id = request.get("preview_id")
    model_id = request.get("source_model_id")
    optimization = isinstance(preview_id, str) and isinstance(model_id, str)
    headline = (
        "Подтвердите постановку оптимизации"
        if optimization
        else "GeoAgent просит подтверждение"
    )
    fields = []
    for key, value in raw_args.items():
        summary, label, code_block = _APPROVAL_ARGS.get(key, (None, key, False))
        if optimization:
            label = _OPTIMIZATION_APPROVAL_LABELS.get(key, key)
            value = _OPTIMIZATION_APPROVAL_VALUES.get(str(value), value)
            if key == "economics" and isinstance(value, dict):
                value = "\n".join(f"{_NPV_ECONOMICS_LABELS.get(name, name)}: {number}" for name, number in value.items())
        if summary and len(fields) == 0:
            headline = summary
        fields.append(
            {"key": key, "label": label, "value": str(value), "code": code_block}
        )

    # A single scalar argument can be corrected in the text box. Anything with
    # more fields would need a form we deliberately do not build into a 420px
    # panel; there the user rejects and says what to change instead.
    allow_edit = bool(config.get("allow_edit")) and len(fields) == 1
    return {
        "headline": headline,
        "action": action_request.get("action", ""),
        "fields": fields,
        "allow_accept": bool(config.get("allow_accept", True)),
        "allow_ignore": bool(config.get("allow_ignore", True)),
        "allow_respond": bool(config.get("allow_respond")),
        "allow_edit": allow_edit,
        "edit_key": fields[0]["key"] if allow_edit else None,
        "edit_value": fields[0]["value"] if allow_edit else "",
        **({"preview_id": preview_id, "source_model_id": model_id} if optimization else {}),
    }


# ── Talking to the agent ──────────────────────────────────────────────────


def _extract_agent_text(part):
    """Return only the final user-facing message from an agent update."""
    event = getattr(part, "event", "") or ""
    data = getattr(part, "data", None)
    if not event.startswith("updates") or not isinstance(data, dict):
        return ""

    for update in reversed(tuple(data.values())):
        if not isinstance(update, dict):
            continue
        messages = update.get("messages") or []
        if not messages or not isinstance(messages[-1], dict):
            continue
        message = messages[-1]
        if message.get("type") not in ("ai", "AIMessage"):
            continue
        if message.get("tool_calls"):
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
    return ""


def _extract_supervisor_text(part):
    """Return only the final user-facing message from the Supervisor graph."""
    event = getattr(part, "event", "") or ""
    data = getattr(part, "data", None)
    if not event.startswith("updates") or not isinstance(data, dict):
        return ""
    update = data.get("answer") or data.get("finish")
    if not isinstance(update, dict):
        return ""
    messages = update.get("messages") or []
    if not messages or not isinstance(messages[-1], dict):
        return ""
    content = messages[-1].get("content", "")
    return content if isinstance(content, str) else ""


def _extract_workflow_status(part):
    event = getattr(part, "event", "") or ""
    data = getattr(part, "data", None)
    if not event.startswith("custom") or not isinstance(data, dict):
        return ""
    if data.get("type") != "workflow_started":
        return ""
    title = data.get("title")
    return f"Запускаю сценарий «{title}»…" if isinstance(title, str) else ""


# Tool call -> the line shown in the chat while it runs. Anything not listed here
# passes silently; the agent narrates it in its own reply.
_FORECAST_RUN_NOTICE = (
    "🔧 Запускаю прогноз JutulDarcy — первый прогон может занять несколько минут…"
)
_TOOL_NOTICES = {
    "run_simulation_in_geoview":
        "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
    "load_model_in_geoview": "📂 Загружаю модель в GeoView…",
    "prepare_optimization_in_geoview": "📝 Заполняю форму оптимизации…",
    # GeoAgentPro computes in its own process instead of pressing GeoView's button.
    "simulate_reservoir_for_geoview":
        "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
    "run_forecast": _FORECAST_RUN_NOTICE,
}

_RESULT_APPLIED_NOTICE = "✓ Расчёт подхватился во вкладке 3D view."


def _tool_notice(part):
    """Return the tool-call id, name and status line from this chunk, if present."""
    data = getattr(part, "data", None)
    if not isinstance(data, (list, tuple)) or not data:
        return None, None, ""
    msg = data[0]
    if not isinstance(msg, dict):
        return None, None, ""
    for call in msg.get("tool_calls") or []:
        if isinstance(call, dict) and call.get("name") in _TOOL_NOTICES:
            call_id = call.get("id")
            name = call["name"]
            return (
                call_id if isinstance(call_id, str) else None,
                name,
                _TOOL_NOTICES[name],
            )
    return None, None, ""


def _append_message(role, text):
    "Append a chat message (reassign list so trame reacts)."
    state.chat_messages = state.chat_messages + [{"role": role, "text": text}]


def _append_result_applied_notice(workflow_id):
    """Keep the forecast completion notice behind its delayed start notice."""
    if workflow_id != "reservoir_forecast":
        _append_message("system", _RESULT_APPLIED_NOTICE)
        return
    if not _forecast_notice_state["running"]:
        _forecast_notice_state["result_pending"] = True
        return
    _append_message("system", _RESULT_APPLIED_NOTICE)
    _forecast_notice_state.update(running=False, result_pending=False)


# ── Request context ───────────────────────────────────────────────────────
#
# The agent has no way to query GeoView, so every message carries a snapshot of
# what is on screen. It is rebuilt each time, which is why "what is loaded?" needs
# no tool call at all.


def _model_summary():
    "Describe the loaded model from the values the Info tab already computes."
    snapshot = _structured_model_snapshot()
    if snapshot is None:
        return "Модель не загружена."

    lines = [f"Загруженная модель: {snapshot['model_name']}"]
    if snapshot["grid_dimensions"]:
        nx, ny, nz = snapshot["grid_dimensions"]
        lines.append(
            f"Сетка: {nx}x{ny}x{nz}, ячеек всего {snapshot['total_cells']}, "
            f"активных {snapshot['active_cells']}"
        )
    if snapshot["phases"]:
        lines.append(f"Фазы: {', '.join(snapshot['phases'])}")
    if snapshot["start_date"] and snapshot["end_date"]:
        lines.append(
            f"Даты: с {snapshot['start_date']} по {snapshot['end_date']}, "
            f"шагов {snapshot['time_steps']}"
        )
    names = snapshot["well_names"]
    if names:
        shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
        lines.append(f"Скважин: {len(names)} ({shown})")
    elif state.num_wells:
        lines.append(f"Скважин: {state.num_wells}")
    attributes = snapshot["state_attributes"]
    lines.append(
        f"Результаты расчёта: есть ({', '.join(attributes)})" if attributes
        else "Результаты расчёта: модель ещё не считалась"
    )
    return "\n".join(lines)


def _structured_model_snapshot():
    """Return compact model facts without exposing the trusted deck path."""
    field = FIELD.get("model")
    if field is None or not state.loadedModelPath:
        return None
    try:
        well_names = list(field.wells.names)
    except (AttributeError, TypeError):
        well_names = []
    try:
        state_attributes = list(field.states.attributes)
    except (AttributeError, TypeError):
        state_attributes = []
    return build_model_snapshot(
        loaded_model_path=state.loadedModelPath,
        grid_dimensions=state.dimens if state.dimens and any(state.dimens) else None,
        total_cells=state.total_cells,
        active_cells=state.active_cells,
        phases=state.fluids or (),
        start_date=state.startDate,
        end_date=state.lastDate,
        schedule_end_date=_schedule_end_date(field),
        time_steps=state.max_timestep,
        well_names=well_names,
        well_controls=_last_well_controls(field.wells),
        available_properties=state.field_attrs or (),
        state_attributes=state_attributes,
    )


def _schedule_end_date(field):
    """Return the final ECLIPSE schedule date from already loaded GeoCode data."""
    runspec = field._data.get("RUNSPEC", ())
    start = next((value for keyword, value in runspec if keyword == "START"), None)
    if start is None:
        return None

    current = start
    for keyword, value in field._data.get("SCHEDULE", ()):
        if keyword == "DATES" and len(value):
            current = value[-1]
        elif keyword == "TSTEP":
            steps = np.asarray(value, dtype=float)
            if not np.isfinite(steps).all() or (steps < 0).any():
                raise ValueError(
                    "Schedule TSTEP values must be finite and non-negative"
                )
            current += timedelta(days=float(steps.sum()))
    return current.strftime("%Y-%m-%d")


def _last_well_controls(wells):
    """Return the final loaded ECLIPSE control for each well."""
    controls = {}
    schedules = (
        ("wconinje", "injection", _INJECTION_CONTROL_COLUMNS),
        ("wconprod", "production", _PRODUCTION_CONTROL_COLUMNS),
    )
    for attribute, role, columns in schedules:
        table = getattr(wells, attribute, None)
        if table is None or table.empty:
            continue
        if "DATE" in table.columns:
            table = table.sort_values("DATE", kind="stable", na_position="first")
        for _, row in table.iterrows():
            well = str(row.get("WELL", "")).strip()
            if not well:
                continue
            status = str(row.get("MODE", "OPEN")).strip().upper() or "OPEN"
            control = str(row.get("CONTROL", "")).strip().upper()
            value_column, unit = columns.get(control, (None, None))
            value = row.get(value_column) if value_column else None
            try:
                value = float(value) if np.isfinite(value) else None
            except (TypeError, ValueError):
                value = None
            controls[well] = {
                "well": well,
                "role": role,
                "status": status,
                "control": control or None,
                "value": value,
                "unit": unit,
            }
    return [controls[well] for well in sorted(controls)]


def _public_preamble():
    """State of the app, as facts.

    No instructions on which tool to call — the public agent's own prompt covers
    that — and nothing telling it to skip questions: it is supposed to ask for the
    optimization parameters it cannot know.
    """
    return "[Контекст GeoView]\n" + _model_summary()


def _graph_input(text):
    if AGENT_PROFILE != "pro" and AGENT_GRAPH != "supervisor":
        text = _public_preamble() + f"\n\nСообщение пользователя: {text}"
        return {"messages": [{"role": "user", "content": text}]}

    trusted_inputs = {}
    if state.loadedModelPath:
        trusted_inputs["deck_path"] = state.loadedModelPath
    model_snapshot = _structured_model_snapshot()
    active_result = state.agent_active_result
    if not isinstance(active_result, dict) or (
        model_snapshot is None
        or active_result.get("source_model_id") != model_snapshot["source_model_id"]
    ):
        active_result = None
    return {
        "messages": [{"role": "user", "content": text}],
        "runtime_context": {
            "trusted_inputs": trusted_inputs,
            "model_snapshot": model_snapshot,
            "active_result": active_result,
        },
    }


async def _consume(client, **stream_kwargs):
    """Stream one run to the panel; stop early if the graph asks for approval.

    Shared by a fresh message and by resuming an approved one, so both render
    identically. Returns nothing: everything lands in trame state.
    """
    assistant_idx = None
    announced = set()

    stream_mode = (
        ["custom", "updates"]
        if AGENT_GRAPH == "supervisor"
        else ["messages-tuple", "updates"]
    )
    async for part in client.runs.stream(
        _thread_id,
        AGENT_ASSISTANT_ID,
        stream_mode=stream_mode,
        **stream_kwargs,
    ):
        request = _extract_interrupt(part)
        if request is not None:
            with state:
                state.pending_approval = _build_approval(request)
                _append_message("system", "⏸ Требуется ваше подтверждение.")
            return

        status = _extract_workflow_status(part)
        if status:
            with state:
                _append_message("system", status)
            continue

        tool_call_id, tool_name, notice = _tool_notice(part)
        notice_key = tool_call_id or notice
        if notice and notice_key not in announced:
            announced.add(notice_key)
            if tool_call_id in _announced_tool_call_ids:
                continue
            if tool_call_id is not None:
                _announced_tool_call_ids.add(tool_call_id)
            with state:
                _append_message("system", notice)
                if tool_name == "run_forecast":
                    _forecast_notice_state["running"] = True
                    if _forecast_notice_state["result_pending"]:
                        _append_message("system", _RESULT_APPLIED_NOTICE)
                        _forecast_notice_state.update(
                            running=False,
                            result_pending=False,
                        )
            continue

        answer = (
            _extract_supervisor_text(part)
            if AGENT_GRAPH == "supervisor"
            else _extract_agent_text(part)
        )
        if not answer:
            continue
        with state:
            if assistant_idx is None:
                _append_message("assistant", answer)
                assistant_idx = len(state.chat_messages) - 1
            else:
                msgs = list(state.chat_messages)
                msgs[assistant_idx] = {"role": "assistant", "text": answer}
                state.chat_messages = msgs


def _agent_unavailable():
    "Report the missing SDK once, in the chat, instead of raising."
    if get_client is not None:
        return False
    with state:
        _append_message(
            "system",
            "⚠ Чат недоступен: не установлен пакет langgraph-sdk "
            "(pip install langgraph-sdk).",
        )
    return True


def _agent_client():
    return get_client(url=AGENT_URL, timeout=_AGENT_TIMEOUT)


def _error_detail(error):
    return str(error).strip() or type(error).__name__


@asynchronous.task
async def chat_send(**kwargs):
    "Send the current input to GeoAgent and stream the reply."
    global _thread_id
    _ = kwargs
    text = (state.chat_input or "").strip()
    if not text or state.chat_busy:
        return

    # While a run is paused the box answers the approval instead of starting a
    # second run against the same thread.
    if state.pending_approval:
        await _resume(
            "response" if state.pending_approval.get("allow_respond") else "edit", text
        )
        return

    if _agent_unavailable():
        return

    with state:
        _append_message("user", text)
        state.chat_input = ""
        state.chat_busy = True

    try:
        client = _agent_client()
        if _thread_id is None:
            thread = await client.threads.create()
            _thread_id = thread["thread_id"]
            _announced_tool_call_ids.clear()
            _forecast_notice_state.update(running=False, result_pending=False)
        await _consume(client, input=_graph_input(text))
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        logger.exception("GeoAgent request failed")
        with state:
            _append_message(
                "system", f"⚠ Не удалось связаться с агентом: {_error_detail(err)}"
            )
    finally:
        with state:
            state.chat_busy = False


async def _resume(response_type, text=""):
    """Answer a pending approval and let the paused run continue.

    ``response_type`` is a HumanResponse literal: accept / ignore / response /
    edit. Only the answer resumes the graph — never a timeout and never the
    panel being closed.
    """
    approval = state.pending_approval
    if not approval or _agent_unavailable():
        return

    preview_id = approval.get("preview_id")
    loaded_model = state.loadedModelPath if preview_id else None
    current_model_id = source_model_id(loaded_model) if loaded_model else None
    if (
        preview_id
        and response_type != "ignore"
        and current_model_id != approval["source_model_id"]
    ):
        response_type = "ignore"
        args = None
        note = "Модель сменилась. Запросите новый предпросмотр оптимизации."
    elif response_type == "accept" and preview_id:
        args = {"preview_id": preview_id, "source_model_id": current_model_id}
        note = "✓ Отправлено подтверждение постановки."
    elif response_type == "edit":
        value = (text or "").strip()
        if not value:
            return
        args = {"action": approval["action"], "args": {approval["edit_key"]: value}}
        note = f"✏ Исправлено и подтверждено: {value}"
    elif response_type == "response":
        value = (text or "").strip()
        if not value:
            return
        args = value
        note = f"💬 Ответ агенту: {value}"
    else:
        args = None
        note = "✓ Подтверждено." if response_type == "accept" else "✗ Отклонено."

    with state:
        state.pending_approval = None
        state.chat_input = ""
        state.chat_busy = True
        _append_message("system", note)

    try:
        client = _agent_client()
        await _consume(
            client, command={"resume": [{"type": response_type, "args": args}]}
        )
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        logger.exception("GeoAgent resume failed")
        with state:
            _append_message(
                "system",
                f"⚠ Не удалось продолжить работу агента: {_error_detail(err)}",
            )
    finally:
        with state:
            state.chat_busy = False


@asynchronous.task
async def approval_accept(**kwargs):
    "Approve the pending tool call as proposed."
    _ = kwargs
    await _resume("accept")


@asynchronous.task
async def approval_reject(**kwargs):
    "Refuse the pending tool call; the agent is told and can propose something else."
    _ = kwargs
    await _resume("ignore")


ctrl.chat_send = chat_send
ctrl.approval_accept = approval_accept
ctrl.approval_reject = approval_reject


# ── Result auto-pickup (artifact contract) ────────────────────────────────


def _apply_field_states(result):
    "Apply a field_states artifact to the loaded model; 3D view updates via modelID."
    from .home import update_dynamics

    if FIELD.get("model") is None or state.loadedModelPath is None:
        _append_message(
            "system",
            "⚠ Расчёт готов, но в GeoView не загружена модель — сначала нажмите Load.",
        )
        return

    field = FIELD["model"]
    dimensions = tuple(
        int(value) for value in np.asarray(field.grid.dimens.values).reshape(-1)
    )
    try:
        current_well_names = list(field.wells.names)
    except (AttributeError, TypeError):
        current_well_names = []
    try:
        validated = load_field_states(
            AGENT_RESULT_DIR / "results",
            result,
            loaded_model_path=state.loadedModelPath,
            grid_dimensions=dimensions,
            actnum=field.grid.actnum,
            current_well_names=current_well_names,
        )
        staged = to_spatial_states(
            validated,
            grid_dimensions=dimensions,
            actnum=field.grid.actnum,
        )
    except SourceModelMismatchError:
        _append_message(
            "system",
            "⚠ Расчёт относится к другой модели и не был применён.",
        )
        return
    except InvalidAgentResultError as err:
        logger.warning("Rejected GeoAgent field states: %s", err)
        _append_message(
            "system",
            "⚠ Результат расчёта не прошёл проверку и не был применён.",
        )
        return

    # Validation and spatial expansion are complete before the first mutation.
    apply_staged_field_states(field, staged, update_dynamics)

    state.agent_active_result = staged.active_result_reference
    state.modelID += 1
    _append_result_applied_notice(result.get("workflow_id"))


def _apply_optimization_result(result):
    """Validate and display an optimization result without changing the field."""
    if FIELD.get("model") is None or state.loadedModelPath is None:
        _append_message(
            "system",
            "⚠ Оптимизация готова, но в GeoView не загружена исходная модель.",
        )
        return None
    try:
        current_well_names = list(FIELD["model"].wells.names)
    except (AttributeError, TypeError):
        current_well_names = []
    try:
        validated = load_optimization_result(
            AGENT_RESULT_DIR / "results",
            result,
            loaded_model_path=state.loadedModelPath,
            current_well_names=current_well_names,
            active_result_reference=state.agent_active_result,
        )
        from .optimization import (
            apply_staged_agent_optimization,
            stage_agent_optimization_result,
        )

        staged = stage_agent_optimization_result(validated)
    except DuplicateAgentResultError:
        logger.info("Ignored duplicate GeoAgent optimization run %s", result.get("run_id"))
        return None
    except SourceModelMismatchError:
        _append_message(
            "system",
            "⚠ Результат оптимизации относится к другой модели и отклонён.",
        )
        return None
    except InvalidAgentResultError as err:
        logger.warning("Rejected GeoAgent optimization result: %s", err)
        _append_message(
            "system",
            "⚠ Результат оптимизации не прошёл проверку и не был показан.",
        )
        return None

    apply_staged_agent_optimization(staged)
    _append_message(
        "system",
        "✓ Проверенный результат оптимизации показан во вкладке Optimization; "
        "управления не применялись к модели.",
    )
    return None


# ── Commands from the agent ───────────────────────────────────────────────
#
# The public GeoAgent computes nothing; it asks GeoView to do what the user could
# do by hand. A handler prepares state and may return a controller to run *after*
# the state lock is released — load_file_async and simulate_async open their own.


def _apply_load_model(result):
    "Open the model the agent picked."
    data_file = result.get("data_file")
    if not data_file:
        _append_message("system", "⚠ Агент не указал, какую модель открыть.")
        return None
    if state.loading:
        _append_message("system", "⚠ GeoView уже загружает модель — запрос пропущен.")
        return None

    state.user_request = data_file
    state.activeTab = "home"
    _append_message("system", f"📂 Открываю модель: {data_file}")
    return ctrl.load_file_async


def _apply_run_simulation(result):
    "Press Simulate for the agent."
    _ = result
    if FIELD.get("model") is None or state.loadedModelPath is None:
        _append_message(
            "system", "⚠ Расчёт невозможен: в GeoView не загружена модель."
        )
        return None
    if state.simulating:
        _append_message("system", "⚠ Расчёт уже идёт — запрос пропущен.")
        return None

    _append_message(
        "system", "▶ Запускаю расчёт — результат появится во вкладке 3D view."
    )
    return ctrl.simulate_async


# Tool argument -> GeoView form field (state.opt_<key>), see optimization.OPT_FIELDS.
_OPT_PARAM_KEYS = (
    "oil_price", "gas_price", "water_price", "water_cost", "gas_cost",
    "discount_rate", "months", "max_iterations",
    "bhp_prod_min", "bhp_prod_max", "bhp_inj_min", "bhp_inj_max",
)


def _apply_optimization_setup(result):
    """Fill the optimization form and show it.

    Deliberately does not start the run: the form's own validator enables the
    Optimize button, and pressing it stays with the user.
    """
    params = result.get("params") or {}
    missing = [key for key in _OPT_PARAM_KEYS if params.get(key) is None]
    if missing:
        _append_message(
            "system", f"⚠ В параметрах оптимизации не хватает полей: {', '.join(missing)}"
        )
        return None

    for key in _OPT_PARAM_KEYS:
        setattr(state, f"opt_{key}", params[key])
    state.activeTab = "opt"
    _append_message(
        "system",
        "📝 Форма оптимизации заполнена — проверьте значения и нажмите Optimize.",
    )
    return None


def apply_result(result):
    """Route a manifest to its handler based on `type`.

    Returns a callable to invoke once the state lock is released, or None.
    """
    if result.get("status") != "ok":
        _append_message("system", "⚠ " + result.get("message", "Ошибка расчёта."))
        return None

    handlers = {
        # Computed elsewhere and handed over (GeoAgentPro).
        "field_states": _apply_field_states,
        "optimization_result": _apply_optimization_result,
        # Asked of GeoView (GeoAgent).
        "load_model": _apply_load_model,
        "run_simulation": _apply_run_simulation,
        "optimization_setup": _apply_optimization_setup,
    }
    handler = handlers.get(result.get("type"))
    if handler is None:
        _append_message(
            "system", f"⚠ Неизвестный тип результата: {result.get('type')}"
        )
        return None
    return handler(result)


@asynchronous.task
async def watch_agent_results(**kwargs):
    "Poll latest.json; apply new results as they appear."
    _ = kwargs
    results_root = AGENT_RESULT_DIR / "results"
    latest = results_root / "latest.json"
    # Ignore any result left over from a previous session.
    try:
        last_seen_run_id = read_latest_run_id(latest) if latest.exists() else None
    except (TransientAgentResultError, InvalidAgentResultError):
        last_seen_run_id = None
    invalid_pointer_reported = False

    while True:
        run_id = None
        try:
            if latest.exists():
                run_id = read_latest_run_id(latest)
                invalid_pointer_reported = False
                if run_id != last_seen_run_id:
                    result = read_run_manifest(results_root, run_id)
                    with state:
                        followup = apply_result(result)
                    # Outside the lock: these controllers acquire state themselves.
                    if followup is not None:
                        followup()
                    last_seen_run_id = run_id
        except TransientAgentResultError:
            # Pointer/manifest/artifact may be temporarily unreadable. Do not
            # mark run_id as handled; the next poll retries the same run.
            pass
        except InvalidAgentResultError as err:
            if run_id is not None:
                last_seen_run_id = run_id
            if not invalid_pointer_reported:
                logger.warning("Rejected GeoAgent result pointer: %s", err)
                with state:
                    _append_message(
                        "system",
                        "⚠ Опубликованный результат агента имеет неверный формат.",
                    )
            invalid_pointer_reported = run_id is None
        except Exception:  # noqa: BLE001 - never let the watcher die
            if run_id is not None:
                last_seen_run_id = run_id
            logger.exception("Could not apply GeoAgent result")
        await asyncio.sleep(1.0)


# ── UI ────────────────────────────────────────────────────────────────────


def render_chat_fab():
    "Floating action button in the bottom-right corner of the Home tab."
    with html.Div(
        v_if="agentMode",
        style="position: fixed; right: 24px; bottom: 24px; z-index: 2000;"
    ):
        with vuetify.VBtn(
            icon=True,
            color="primary",
            size="large",
            elevation=6,
            click="showChat = !showChat",
        ):
            vuetify.VIcon("mdi-robot-happy-outline", size="large")
            vuetify.VTooltip(
                text="Чат с GeoAgent", activator="parent", location="left"
            )


def render_approval_card():
    """Pending-approval card: what the agent wants to do, and the answer buttons.

    Deliberately not a chat bubble — an irreversible action must not look like
    conversation. "Отклонить" comes first so the safe answer is the easy one,
    and the raw argument is always shown, never only the headline.
    """
    with vuetify.VCard(
        v_if="pending_approval",
        variant="tonal",
        color="warning",
        classes="ma-2 pa-2",
        style="max-height: 260px; overflow-y: auto;",
    ):
        with html.Div(classes="d-flex align-center mb-1"):
            vuetify.VIcon("mdi-shield-alert-outline", size="small", classes="mr-2")
            html.Span(
                "{{ pending_approval.headline }}",
                style="font-weight: 600; font-size: 13px;",
            )

        with html.Div(v_for="f, i in pending_approval.fields", key="i", classes="mb-1"):
            html.Div(
                "{{ f.label }}",
                style="font-size: 11px; opacity: 0.75; text-transform: uppercase;",
            )
            html.Div(
                "{{ f.value }}",
                style=(
                    "f.code "
                    "? 'font-family: monospace; font-size: 12px; white-space: pre-wrap; "
                    "word-break: break-all; background: rgba(0,0,0,0.06); padding: 6px; "
                    "border-radius: 4px; max-height: 120px; overflow-y: auto;' "
                    ": 'font-size: 12px; word-break: break-all;'",
                ),
            )

        html.Div(
            "Отклонение не прерывает диалог: агент узнает об отказе и предложит другое.",
            v_if="!pending_approval.allow_edit",
            style="font-size: 11px; opacity: 0.7;",
            classes="mt-1",
        )

        with html.Div(classes="d-flex ga-2 mt-2"):
            vuetify.VBtn(
                "Отклонить",
                v_if="pending_approval.allow_ignore",
                size="small",
                variant="flat",
                color="error",
                disabled=("chat_busy",),
                click=ctrl.approval_reject,
            )
            vuetify.VBtn(
                "Разрешить",
                v_if="pending_approval.allow_accept",
                size="small",
                variant="outlined",
                disabled=("chat_busy",),
                click=ctrl.approval_accept,
            )


def render_chat_panel():
    "Chat window anchored to the bottom-right, toggled by the FAB."
    with html.Div(
        v_if="showChat",
        style=(
            "position: fixed; right: 24px; bottom: 96px; z-index: 2000; "
            "width: 420px; max-width: 90vw;"
        ),
    ):
        with vuetify.VCard(
            elevation=12,
            style="height: 600px; max-height: 70vh;",
            classes="d-flex flex-column",
        ):
            with vuetify.VToolbar(density="compact", color="primary"):
                vuetify.VToolbarTitle("GeoAgent")
                vuetify.VSpacer()
                with vuetify.VBtn(icon=True, click="showChat = false"):
                    vuetify.VIcon("mdi-close")

            with vuetify.VCardText(
                classes="flex-grow-1 overflow-auto pa-3",
                style="background-color: rgba(0,0,0,0.02);",
            ):
                with html.Div(
                    v_if="chat_messages.length === 0",
                    classes="text-center text-medium-emphasis mt-4",
                ):
                    html.Div("Спросите агента или попросите посчитать загруженную модель.")
                with html.Div(
                    v_for="msg, i in chat_messages",
                    key="i",
                    classes="mb-2 d-flex",
                    style=(
                        "msg.role === 'user' ? 'justify-content: flex-end' : "
                        "'justify-content: flex-start'",
                    ),
                ):
                    html.Div(
                        "{{ msg.text }}",
                        style=(
                            "msg.role === 'user' "
                            "? 'white-space: pre-wrap; max-width: 85%; padding: 8px 12px; "
                            "border-radius: 12px; background:#1976d2; color:white;' "
                            ": (msg.role === 'system' "
                            "? 'white-space: pre-wrap; max-width: 100%; font-size: 12px; "
                            "font-style: italic; color:#666; text-align:center; width:100%' "
                            ": 'white-space: pre-wrap; max-width: 85%; padding: 8px 12px; "
                            "border-radius: 12px; background:#eceff1; color:#111;')",
                        ),
                    )

            render_approval_card()

            vuetify.VProgressLinear(v_if="chat_busy", indeterminate=True, color="primary")

            with vuetify.VCardActions(classes="pa-2"):
                # While an approval is pending the box answers it rather than
                # starting a second run, so the placeholder has to say so —
                # a silently repurposed input is how people approve the wrong
                # thing.
                vuetify.VTextField(
                    v_model=("chat_input",),
                    placeholder=(
                        "pending_approval "
                        "? (pending_approval.allow_edit "
                        "? 'Исправьте значение и нажмите Enter…' "
                        ": 'Напишите агенту, что сделать иначе…') "
                        ": 'Напишите сообщение…'",
                    ),
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    disabled=(
                        "chat_busy || (pending_approval && "
                        "!pending_approval.allow_edit && "
                        "!pending_approval.allow_respond)",
                    ),
                    bg_color=("pending_approval ? 'amber-lighten-5' : undefined",),
                    keyup_enter=ctrl.chat_send,
                )
                with vuetify.VBtn(
                    icon=True,
                    color="primary",
                    click=ctrl.chat_send,
                    disabled=("chat_busy",),
                ):
                    vuetify.VIcon("mdi-send")
