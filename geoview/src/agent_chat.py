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
from pathlib import Path

from trame.widgets import html, vuetify3 as vuetify
from trame.app import asynchronous

try:
    from langgraph_sdk import get_client
except ModuleNotFoundError:
    # Only the chat needs it; a plain GeoView launch must still start without it.
    get_client = None

from .config import state, ctrl, FIELD, agent_enabled

# GeoAgent langgraph server (started by app.py with --agent).
AGENT_URL = "http://127.0.0.1:2024"
AGENT_ASSISTANT_ID = "GeoAgent"

# Shared result directory (GeoView side of the artifact contract).
AGENT_RESULT_DIR = Path(__file__).resolve().parents[2] / ".agent_runtime"
(AGENT_RESULT_DIR / "results").mkdir(parents=True, exist_ok=True)

state.agentMode = bool(agent_enabled)
state.showChat = False
state.chat_messages = []
state.chat_input = ""
state.chat_busy = False
state.agent_result_dir = str(AGENT_RESULT_DIR)

# LangGraph conversation thread (kept across messages for dialogue context).
_thread_id = None


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


def _mentions_simulation_tool(part):
    """True if this chunk is an assistant tool call to the simulation bridge."""
    data = getattr(part, "data", None)
    if not isinstance(data, (list, tuple)) or not data:
        return False
    msg = data[0]
    if not isinstance(msg, dict):
        return False
    for call in msg.get("tool_calls") or []:
        if isinstance(call, dict) and call.get("name") == "simulate_reservoir_for_geoview":
            return True
    return False


def _append_message(role, text):
    "Append a chat message (reassign list so trame reacts)."
    state.chat_messages = state.chat_messages + [{"role": role, "text": text}]


@asynchronous.task
async def chat_send(**kwargs):
    "Send the current input to GeoAgent and stream the reply."
    global _thread_id
    _ = kwargs
    text = (state.chat_input or "").strip()
    if not text or state.chat_busy:
        return

    if get_client is None:
        with state:
            _append_message(
                "system",
                "⚠ Чат недоступен: не установлен пакет langgraph-sdk "
                "(pip install langgraph-sdk).",
            )
        return

    with state:
        _append_message("user", text)
        state.chat_input = ""
        state.chat_busy = True

    model_path = state.loadedModelPath or state.user_request or ""
    context = (
        "[Контекст GeoView] "
        + (f"Загруженная модель: {model_path}. " if model_path else "Модель не загружена. ")
        + f"Каталог результатов: {state.agent_result_dir}. "
        "Чтобы посчитать/симулировать загруженную модель, вызывай инструмент "
        "simulate_reservoir_for_geoview(data_file, output_dir), где data_file — путь "
        "модели выше, output_dir — этот каталог результатов. Не проси подтверждений."
        f"\n\nСообщение пользователя: {text}"
    )

    assistant_text = ""
    assistant_idx = None
    announced_sim = False
    try:
        client = get_client(url=AGENT_URL)
        if _thread_id is None:
            thread = await client.threads.create()
            _thread_id = thread["thread_id"]

        async for part in client.runs.stream(
            _thread_id,
            AGENT_ASSISTANT_ID,
            input={"messages": [{"role": "user", "content": context}]},
            stream_mode="messages-tuple",
        ):
            if not announced_sim and _mentions_simulation_tool(part):
                announced_sim = True
                assistant_text = ""
                assistant_idx = None
                with state:
                    _append_message(
                        "system",
                        "🔧 Запускаю расчёт JutulDarcy — первый прогон может занять "
                        "несколько минут…",
                    )
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
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        with state:
            _append_message("system", f"⚠ Не удалось связаться с агентом: {err}")
    finally:
        with state:
            state.chat_busy = False


ctrl.chat_send = chat_send


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


def apply_result(result):
    "Route a result manifest to its display handler based on `type`."
    if result.get("status") != "ok":
        _append_message("system", "⚠ " + result.get("message", "Ошибка расчёта."))
        return

    handlers = {
        "field_states": _apply_field_states,
        # future: "optimization_report": _apply_optimization_report, ...
    }
    handler = handlers.get(result.get("type"))
    if handler is None:
        _append_message(
            "system", f"⚠ Неизвестный тип результата: {result.get('type')}"
        )
        return
    handler(result)


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
                        apply_result(result)
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

            vuetify.VProgressLinear(v_if="chat_busy", indeterminate=True, color="primary")

            with vuetify.VCardActions(classes="pa-2"):
                vuetify.VTextField(
                    v_model=("chat_input",),
                    placeholder="Напишите сообщение…",
                    density="compact",
                    variant="outlined",
                    hide_details=True,
                    disabled=("chat_busy",),
                    keyup_enter=ctrl.chat_send,
                )
                with vuetify.VBtn(
                    icon=True,
                    color="primary",
                    click=ctrl.chat_send,
                    disabled=("chat_busy",),
                ):
                    vuetify.VIcon("mdi-send")
