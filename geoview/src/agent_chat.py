"""In-app chat with GeoAgent + result auto-pickup.

A floating button on the Home tab opens a chat panel talking to the real GeoAgent
(served by a local ``langgraph dev`` server). When the agent computes a reservoir
model it writes a result artifact following the GeoView contract (see
``GeoAgent/src/GeoAgent/tools/geoview_bridge.py``). A background watcher notices new
results and routes them to a display handler; ``field_states`` results are applied to
the loaded model so the 3D view updates automatically.
"""
import asyncio
import json
import pickle

from trame.widgets import html, vuetify3 as vuetify
from trame.app import asynchronous

try:
    from langgraph_sdk import get_client
except ModuleNotFoundError:
    # Only the chat needs it; a plain GeoView launch must still start without it.
    get_client = None

# AGENT_PROFILE picks which agent is on the other end of the socket, and with it
# which preamble to send: the public one states GeoView's state as facts, the pro
# one names GeoAgentPro's bridge tool explicitly. Both are kept below.
from .config import (
    AGENT_PROFILE, AGENT_RESULT_DIR, state, ctrl, FIELD, agent_enabled)

# GeoAgent langgraph server (started by app.py with --agent).
AGENT_URL = "http://127.0.0.1:2024"
AGENT_ASSISTANT_ID = "GeoAgent"

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

    headline = "GeoAgent просит подтверждение"
    fields = []
    for key, value in raw_args.items():
        summary, label, code_block = _APPROVAL_ARGS.get(key, (None, key, False))
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
    }


# ── Talking to the agent ──────────────────────────────────────────────────


def _extract_ai_text(part):
    """Return the text delta of an assistant message chunk, else ''."""
    event = getattr(part, "event", "") or ""
    data = getattr(part, "data", None)
    if not event.startswith("messages"):
        return ""
    if not isinstance(data, (list, tuple)) or not data:
        return ""
    msg = data[0]
    if not isinstance(msg, dict):
        return ""
    if msg.get("type") not in ("ai", "AIMessageChunk", "AIMessage"):
        return ""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return ""


# Tool call -> the line shown in the chat while it runs. Anything not listed here
# passes silently; the agent narrates it in its own reply.
_TOOL_NOTICES = {
    "run_simulation_in_geoview":
        "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
    "load_model_in_geoview": "📂 Загружаю модель в GeoView…",
    "prepare_optimization_in_geoview": "📝 Заполняю форму оптимизации…",
    # GeoAgentPro computes in its own process instead of pressing GeoView's button.
    "simulate_reservoir_for_geoview":
        "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять несколько минут…",
}


def _tool_notice(part):
    """Return the status line for a tool call in this chunk, or '' if there is none."""
    data = getattr(part, "data", None)
    if not isinstance(data, (list, tuple)) or not data:
        return ""
    msg = data[0]
    if not isinstance(msg, dict):
        return ""
    for call in msg.get("tool_calls") or []:
        if isinstance(call, dict) and call.get("name") in _TOOL_NOTICES:
            return _TOOL_NOTICES[call["name"]]
    return ""


def _append_message(role, text):
    "Append a chat message (reassign list so trame reacts)."
    state.chat_messages = state.chat_messages + [{"role": role, "text": text}]


# ── Request context ───────────────────────────────────────────────────────
#
# The agent has no way to query GeoView, so every message carries a snapshot of
# what is on screen. It is rebuilt each time, which is why "what is loaded?" needs
# no tool call at all.


def _model_summary():
    "Describe the loaded model from the values the Info tab already computes."
    if FIELD.get("model") is None or not state.loadedModelPath:
        return "Модель не загружена."

    lines = [f"Загруженная модель: {state.loadedModelPath}"]
    if state.dimens and any(state.dimens):
        nx, ny, nz = state.dimens
        lines.append(
            f"Сетка: {nx}x{ny}x{nz}, ячеек всего {state.total_cells}, "
            f"активных {state.active_cells}"
        )
    if state.fluids:
        lines.append(f"Фазы: {', '.join(state.fluids)}")
    if state.startDate and state.lastDate:
        lines.append(
            f"Даты: с {state.startDate} по {state.lastDate}, "
            f"шагов {state.max_timestep}"
        )

    try:
        names = list(FIELD["model"].wells.names)
    except Exception:  # noqa: BLE001 - the summary must never break the chat
        names = []
    if names:
        shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
        lines.append(f"Скважин: {len(names)} ({shown})")
    elif state.num_wells:
        lines.append(f"Скважин: {state.num_wells}")

    try:
        attributes = list(FIELD["model"].states.attributes)
    except Exception:  # noqa: BLE001
        attributes = []
    lines.append(
        f"Результаты расчёта: есть ({', '.join(attributes)})" if attributes
        else "Результаты расчёта: модель ещё не считалась"
    )
    return "\n".join(lines)


def _pro_preamble():
    """The preamble GeoAgentPro expects.

    Kept verbatim: Pro's bridge tool takes data_file and output_dir from this text,
    and its flow assumes it may act without asking.
    """
    model_path = state.loadedModelPath or state.user_request or ""
    return (
        "[Контекст GeoView] "
        + (f"Загруженная модель: {model_path}. " if model_path else "Модель не загружена. ")
        + f"Каталог результатов: {state.agent_result_dir}. "
        "Чтобы посчитать/симулировать загруженную модель, вызывай инструмент "
        "simulate_reservoir_for_geoview(data_file, output_dir), где data_file — путь "
        "модели выше, output_dir — этот каталог результатов. Не проси подтверждений."
    )


def _public_preamble():
    """State of the app, as facts.

    No instructions on which tool to call — the public agent's own prompt covers
    that — and nothing telling it to skip questions: it is supposed to ask for the
    optimization parameters it cannot know.
    """
    return "[Контекст GeoView]\n" + _model_summary()


def _preamble():
    "The context block prepended to every user message."
    return _pro_preamble() if AGENT_PROFILE == "pro" else _public_preamble()


async def _consume(client, **stream_kwargs):
    """Stream one run to the panel; stop early if the graph asks for approval.

    Shared by a fresh message and by resuming an approved one, so both render
    identically. Returns nothing: everything lands in trame state.
    """
    assistant_text = ""
    assistant_idx = None
    announced = set()

    async for part in client.runs.stream(
        _thread_id,
        AGENT_ASSISTANT_ID,
        stream_mode=["messages-tuple", "updates"],
        **stream_kwargs,
    ):
        request = _extract_interrupt(part)
        if request is not None:
            with state:
                state.pending_approval = _build_approval(request)
                _append_message("system", "⏸ Требуется ваше подтверждение.")
            return

        notice = _tool_notice(part)
        if notice and notice not in announced:
            announced.add(notice)
            # The tool call closes the assistant bubble; text after it starts a new one.
            assistant_text = ""
            assistant_idx = None
            with state:
                _append_message("system", notice)
            continue

        delta = _extract_ai_text(part)
        if not delta:
            continue
        assistant_text += delta
        with state:
            if assistant_idx is None:
                _append_message("assistant", assistant_text)
                assistant_idx = len(state.chat_messages) - 1
            else:
                msgs = list(state.chat_messages)
                msgs[assistant_idx] = {"role": "assistant", "text": assistant_text}
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

    context = _preamble() + f"\n\nСообщение пользователя: {text}"

    try:
        client = get_client(url=AGENT_URL)
        if _thread_id is None:
            thread = await client.threads.create()
            _thread_id = thread["thread_id"]
        await _consume(
            client, input={"messages": [{"role": "user", "content": context}]}
        )
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        with state:
            _append_message("system", f"⚠ Не удалось связаться с агентом: {err}")
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

    if response_type == "edit":
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
        client = get_client(url=AGENT_URL)
        await _consume(
            client, command={"resume": [{"type": response_type, "args": args}]}
        )
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        with state:
            _append_message("system", f"⚠ Не удалось продолжить работу агента: {err}")
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

    run_dir = AGENT_RESULT_DIR / "results" / result["run_id"]
    with open(run_dir / result["artifacts"]["states"], "rb") as f:
        states = pickle.load(f)

    field = FIELD["model"]
    field.states.pressure = states["pressure"]
    for key, value in states["saturations"].items():
        setattr(field.states, key, value)

    new_attrs = ["PRESSURE"] + list(states["saturations"].keys())
    for key in list(field.states.attributes):
        if key not in new_attrs:
            delattr(field.states, key)

    field.states.to_spatial()
    field.wells.results = states["welldata"]
    update_dynamics(field)

    state.modelID += 1
    _append_message("system", "✓ Расчёт подхватился во вкладке 3D view.")


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
    latest = AGENT_RESULT_DIR / "results" / "latest.json"
    # Ignore any result left over from a previous session.
    last_seen = latest.stat().st_mtime if latest.exists() else None

    while True:
        try:
            if latest.exists():
                mtime = latest.stat().st_mtime
                if mtime != last_seen:
                    last_seen = mtime
                    run_id = json.loads(latest.read_text(encoding="utf-8"))["run_id"]
                    manifest_path = AGENT_RESULT_DIR / "results" / run_id / "result.json"
                    result = json.loads(manifest_path.read_text(encoding="utf-8"))
                    with state:
                        followup = apply_result(result)
                    # Outside the lock: these controllers acquire state themselves.
                    if followup is not None:
                        followup()
        except Exception:  # noqa: BLE001 - never let the watcher die
            pass
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
