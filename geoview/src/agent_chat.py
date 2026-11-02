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

# AGENT_PROFILE picks which agent is on the other end of the socket, and with it
# which preamble to send: the public one states GeoView's state as facts, the pro
# one names GeoAgentPro's bridge tool explicitly. Both are kept below.
from .config import (
    AGENT_PROFILE, AGENT_RESULT_DIR, CHAT_LANG, state, ctrl, FIELD, agent_enabled)
# Every user-visible string, in English and in Russian; --ru picks the language.
from .agent_text import TEXT

# GeoAgent langgraph server (started by app.py with --agent).
AGENT_URL = "http://127.0.0.1:2024"
AGENT_ASSISTANT_ID = "GeoAgent"

(AGENT_RESULT_DIR / "results").mkdir(parents=True, exist_ok=True)

state.agentMode = bool(agent_enabled)
state.showChat = False
state.chat_messages = []
state.chat_input = ""
state.chat_busy = False
state.chat_run_id = ""
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

    headline = TEXT["approval_headline"]
    fields = []
    for key, value in raw_args.items():
        summary, label, code_block = TEXT["approval_args"].get(key, (None, key, False))
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


def _tool_notice(part):
    """Return ``(tool_call_id, status line)`` for a tool call in this chunk, else None.

    The four GeoView-operating tools have their own wording. With the Pro agent
    every other tool call is announced by name as well, so the chat shows what
    the agent is doing; the public profile keeps the silent default. The id lets
    the caller announce a repeated call of the same tool again.
    """
    data = getattr(part, "data", None)
    if not isinstance(data, (list, tuple)) or not data:
        return None
    msg = data[0]
    if not isinstance(msg, dict):
        return None
    notices = TEXT["tool_notices"]
    for call in msg.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if not name:
            continue
        call_id = call.get("id") or name
        if name in notices:
            return call_id, notices[name]
        if AGENT_PROFILE == "pro":
            return call_id, TEXT["tool_notice_generic"].format(name=name)
    return None


def _stage_line(part):
    """Return the system line for a stage event on the ``custom`` stream, else ''.

    The Pro agent emits ``{"stage": key, "detail": text}`` while it works; the
    wording lives in ``agent_text.TEXT["stages"]`` and unknown keys fall back to
    a generic line, so a new stage never passes unseen.
    """
    if AGENT_PROFILE != "pro":
        return ""
    if (getattr(part, "event", "") or "") != "custom":
        return ""
    data = getattr(part, "data", None)
    if not isinstance(data, dict) or "stage" not in data:
        return ""
    key = str(data.get("stage"))
    detail = str(data.get("detail", ""))
    template = TEXT["stages"].get(key)
    if template is None:
        return TEXT["stage_generic"].format(key=key, detail=detail)
    return template.format(detail=detail)


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
        return TEXT["no_model"]

    lines = [TEXT["loaded_model"].format(path=state.loadedModelPath)]
    if state.dimens and any(state.dimens):
        nx, ny, nz = state.dimens
        lines.append(
            TEXT["grid"].format(
                nx=nx, ny=ny, nz=nz,
                total=state.total_cells, active=state.active_cells,
            )
        )
    if state.fluids:
        lines.append(TEXT["phases"].format(phases=", ".join(state.fluids)))
    if state.startDate and state.lastDate:
        lines.append(
            TEXT["dates"].format(
                start=state.startDate, last=state.lastDate, steps=state.max_timestep
            )
        )

    try:
        names = list(FIELD["model"].wells.names)
    except Exception:  # noqa: BLE001 - the summary must never break the chat
        names = []
    if names:
        shown = ", ".join(names[:12]) + (" …" if len(names) > 12 else "")
        lines.append(TEXT["wells_named"].format(count=len(names), names=shown))
    elif state.num_wells:
        lines.append(TEXT["wells_count"].format(count=state.num_wells))

    try:
        attributes = list(FIELD["model"].states.attributes)
    except Exception:  # noqa: BLE001
        attributes = []
    lines.append(
        TEXT["results_present"].format(attributes=", ".join(attributes)) if attributes
        else TEXT["results_absent"]
    )
    return "\n".join(lines)


def _project_line(deck, limit=50):
    """The deck's folder is the project: relative paths are read from it.

    Mirrored in GeoAgentPro's eval_runner.py (``project_line``); English on purpose,
    like the tool output the agent reads.
    """
    folder = Path(deck).expanduser().parent
    try:
        names = sorted(
            p.name + ("/" if p.is_dir() else "")
            for p in folder.iterdir()
            if not p.name.startswith(".")
        )
    except OSError:
        return ""
    more = f", … ({len(names) - limit} more)" if len(names) > limit else ""
    return (
        f"Project folder: {folder} (relative paths are read from here). "
        f"Files: {', '.join(names[:limit])}{more}."
    )


def _pro_preamble():
    """The preamble GeoAgentPro expects.

    Facts only: the loaded model, the results directory, the answer language, and
    (when a model is loaded) the same summary the public profile sends, so "what is
    loaded?" costs the Pro agent no tool call either. The Russian wording of the
    first sentences is kept as it was; the summary is appended after them.
    """
    model_path = state.loadedModelPath or state.user_request or ""
    project = _project_line(model_path) if model_path else ""
    text = (
        TEXT["pro_header"]
        + (TEXT["pro_model"].format(path=model_path) if model_path
           else TEXT["pro_no_model"])
        + (project + " " if project else "")
        + TEXT["pro_instructions"].format(directory=state.agent_result_dir)
    )
    if FIELD.get("model") is not None and state.loadedModelPath:
        text += "\n" + _model_summary()
    return text


def _app_context():
    """GeoView's state as a structured object, for the Pro agent's graph input.

    The agent reads the deck path and the results directory from here, never
    from the prose preamble, so a path the model makes up cannot replace them.
    ``user_text`` is the raw typed message, before the preamble is prepended.
    """
    return {
        "loaded_model_path": state.loadedModelPath or "",
        "results_dir": state.agent_result_dir,
        "language": CHAT_LANG,
        "user_text": (state.chat_input or "").strip(),
        "model_summary": _model_summary()[:600],
        "recent_models": list(state.recentFiles or [])[-5:],
    }


def _public_preamble():
    """State of the app, as facts.

    No instructions on which tool to call — the public agent's own prompt covers
    that — and nothing telling it to skip questions: it is supposed to ask for the
    optimization parameters it cannot know.
    """
    return TEXT["context_header"] + "\n" + _model_summary()


def _preamble():
    "The context block prepended to every user message."
    return _pro_preamble() if AGENT_PROFILE == "pro" else _public_preamble()


async def _consume(client, **stream_kwargs):
    """Stream one run to the panel; stop early if the graph asks for approval.

    Shared by a fresh message and by resuming an approved one, so both render
    identically. Returns nothing: everything lands in trame state.

    The Pro team agent checks its answer after writing it, so its text is held
    behind a "…" bubble until the next event: a tool call or stage shows it, a
    passing verdict shows it, a failing verdict drops it (the fixed answer
    follows), and the end of the run shows whatever is left.
    """
    assistant_text = ""
    assistant_idx = None
    announced = set()
    hold = AGENT_PROFILE == "pro"

    def release(keep=True):
        "Show (or drop) the held text; the next text starts a new bubble."
        nonlocal assistant_text, assistant_idx
        if assistant_idx is not None:
            msgs = list(state.chat_messages)
            if keep and assistant_text:
                msgs[assistant_idx] = {"role": "assistant", "text": assistant_text}
            else:
                del msgs[assistant_idx]
            state.chat_messages = msgs
        assistant_text = ""
        assistant_idx = None

    try:
        async for part in client.runs.stream(
            _thread_id,
            AGENT_ASSISTANT_ID,
            # "custom" carries the Pro agent's stage events; the public agent emits
            # none, so the extra mode is harmless there.
            stream_mode=["messages-tuple", "updates", "custom"],
            # The server default is 25 graph steps (about 12 tool calls); the Pro
            # agent's cheap probes (Phase 4d) need more before it answers.
            config={"recursion_limit": 120},
            **stream_kwargs,
        ):
            # The first event names the run; the Stop button needs it.
            if (getattr(part, "event", "") or "") == "metadata":
                data = getattr(part, "data", None)
                if isinstance(data, dict) and data.get("run_id"):
                    with state:
                        state.chat_run_id = str(data["run_id"])
                continue

            request = _extract_interrupt(part)
            if request is not None:
                with state:
                    release()
                    state.pending_approval = _build_approval(request)
                    _append_message("system", TEXT["approval_pending"])
                return

            stage = _stage_line(part)
            if stage:
                data = getattr(part, "data", None) or {}
                verdict_failed = data.get("stage") == "verify" and not stage.lstrip().startswith("✅")
                with state:
                    release(keep=not verdict_failed)
                    _append_message("system", stage)
                continue

            notice = _tool_notice(part)
            if notice is not None:
                call_id, text = notice
                if call_id not in announced:
                    announced.add(call_id)
                    # The tool call closes the assistant bubble; text after it starts a new one.
                    with state:
                        release()
                        _append_message("system", text)
                continue

            delta = _extract_ai_text(part)
            if not delta:
                continue
            assistant_text += delta
            shown = "…" if hold else assistant_text
            with state:
                if assistant_idx is None:
                    _append_message("assistant", shown)
                    assistant_idx = len(state.chat_messages) - 1
                elif not hold:
                    msgs = list(state.chat_messages)
                    msgs[assistant_idx] = {"role": "assistant", "text": shown}
                    state.chat_messages = msgs
    finally:
        # an error mid-run must not leave the "…" bubble behind
        with state:
            release()


def _agent_unavailable():
    "Report the missing SDK once, in the chat, instead of raising."
    if get_client is not None:
        return False
    with state:
        _append_message("system", TEXT["no_sdk"])
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

    # Built before the input box is cleared: it carries the raw typed text.
    app_context = _app_context() if AGENT_PROFILE == "pro" else None

    with state:
        _append_message("user", text)
        state.chat_input = ""
        state.chat_busy = True
        # A new run: Stop must never cancel the previous run's id.
        state.chat_run_id = ""

    context = _preamble() + "\n\n" + TEXT["user_message"].format(text=text)
    run_input = {"messages": [{"role": "user", "content": context}]}
    if app_context is not None:
        run_input["app_context"] = app_context

    try:
        client = get_client(url=AGENT_URL)
        if _thread_id is None:
            thread = await client.threads.create()
            _thread_id = thread["thread_id"]
        await _consume(client, input=run_input)
    except Exception as err:  # noqa: BLE001 - surface any transport error in chat
        # A restarted server no longer knows our thread: forget it so the next
        # message opens a fresh one instead of failing the same way again.
        if _status_code(err) == 404:
            _thread_id = None
        with state:
            _append_message("system", TEXT["send_failed"].format(error=err))
    finally:
        with state:
            state.chat_busy = False


def _status_code(err):
    "HTTP status of a transport error, or None."
    response = getattr(err, "response", None)
    return getattr(response, "status_code", None)


async def chat_stop(**kwargs):
    """Stop the running turn: flag the Julia job, cancel the run, forget the thread.

    The flag carries the run id, so only the job started by this run honours it
    (jobs.consume_cancel_flag on the agent side). The thread is dropped because a
    cancelled run leaves the graph mid-step; the next message starts clean.
    """
    global _thread_id
    run_id = state.chat_run_id or ""
    thread_id = _thread_id
    if not thread_id:
        return
    try:
        control = AGENT_RESULT_DIR / "control"
        control.mkdir(parents=True, exist_ok=True)
        (control / f"cancel_{thread_id}.flag").write_text(run_id, encoding="utf-8")
    except OSError:
        pass
    if run_id:
        try:
            await get_client(url=AGENT_URL).runs.cancel(thread_id, run_id)
        except Exception:  # noqa: BLE001 - the flag already stops the job
            pass
    _thread_id = None
    with state:
        state.pending_approval = None
        state.chat_busy = False
        _append_message("system", TEXT["stages"]["cancelled"].format(detail=TEXT["stopped_by_user"]))


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
        note = TEXT["approval_edited"].format(value=value)
    elif response_type == "response":
        value = (text or "").strip()
        if not value:
            return
        args = value
        note = TEXT["approval_answer"].format(value=value)
    else:
        args = None
        note = (TEXT["approval_accepted"] if response_type == "accept"
                else TEXT["approval_rejected"])

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
            _append_message("system", TEXT["resume_failed"].format(error=err))
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
ctrl.chat_stop = chat_stop
ctrl.approval_accept = approval_accept
ctrl.approval_reject = approval_reject


# ── Result auto-pickup (artifact contract) ────────────────────────────────


def _apply_field_states(result):
    "Apply a field_states artifact to the loaded model; 3D view updates via modelID."
    from .home import update_dynamics

    if FIELD.get("model") is None or state.loadedModelPath is None:
        _append_message("system", TEXT["states_no_model"])
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
    _append_message("system", TEXT["states_applied"])


# ── Commands from the agent ───────────────────────────────────────────────
#
# The public GeoAgent computes nothing; it asks GeoView to do what the user could
# do by hand. A handler prepares state and may return a controller to run *after*
# the state lock is released — load_file_async and simulate_async open their own.


def _apply_load_model(result):
    "Open the model the agent picked."
    data_file = result.get("data_file")
    if not data_file:
        _append_message("system", TEXT["load_no_path"])
        return None
    if state.loading:
        _append_message("system", TEXT["load_busy"])
        return None

    state.user_request = data_file
    state.activeTab = "home"
    _append_message("system", TEXT["load_started"].format(path=data_file))
    _report_when_done("loading")
    return ctrl.load_file_async


def _apply_run_simulation(result):
    "Press Simulate for the agent."
    _ = result
    if FIELD.get("model") is None or state.loadedModelPath is None:
        _append_message("system", TEXT["simulate_no_model"])
        return None
    if state.simulating:
        _append_message("system", TEXT["simulate_busy"])
        return None

    _append_message("system", TEXT["simulate_started"])
    _report_when_done("simulating")
    return ctrl.simulate_async


@asynchronous.task
async def _report_when_done(flag):
    """Tell the chat how a load or a run the agent asked for ended.

    The agent only presses GeoView's button and says "GeoView reports the outcome
    in the chat": this is that report. ``flag`` is ``loading`` or ``simulating``.
    """
    # the controller starts after the state lock is released: wait for it to begin
    for _ in range(20):
        if state[flag]:
            break
        await asyncio.sleep(0.5)
    while state[flag]:
        await asyncio.sleep(1.0)
    with state:
        if flag == "loading":
            if state.loadFailed:
                _append_message("system", TEXT["load_failed"].format(error=state.errMessage))
            elif state.loadedModelPath:
                _append_message("system", TEXT["load_done"].format(path=state.loadedModelPath))
        elif state.simulationFailed:
            _append_message("system", TEXT["simulate_failed"].format(error=state.errMessage))
        elif state.simulationResultDir:
            _append_message("system", TEXT["simulate_done"])


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
        _append_message("system", TEXT["opt_missing"].format(fields=", ".join(missing)))
        return None

    for key in _OPT_PARAM_KEYS:
        setattr(state, f"opt_{key}", params[key])
    state.activeTab = "opt"
    _append_message("system", TEXT["opt_filled"])
    return None


def apply_result(result):
    """Route a manifest to its handler based on `type`.

    Returns a callable to invoke once the state lock is released, or None.
    """
    if result.get("status") != "ok":
        _append_message("system", "⚠ " + result.get("message", TEXT["result_failed"]))
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
            "system", TEXT["result_unknown"].format(type=result.get("type"))
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
                text=TEXT["fab_tooltip"], activator="parent", location="left"
            )


def render_approval_card():
    """Pending-approval card: what the agent wants to do, and the answer buttons.

    Deliberately not a chat bubble — an irreversible action must not look like
    conversation. The reject button comes first so the safe answer is the easy one,
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
            TEXT["approval_hint"],
            v_if="!pending_approval.allow_edit",
            style="font-size: 11px; opacity: 0.7;",
            classes="mt-1",
        )

        with html.Div(classes="d-flex ga-2 mt-2"):
            vuetify.VBtn(
                TEXT["approval_reject"],
                v_if="pending_approval.allow_ignore",
                size="small",
                variant="flat",
                color="error",
                disabled=("chat_busy",),
                click=ctrl.approval_reject,
            )
            vuetify.VBtn(
                TEXT["approval_accept"],
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
                    html.Div(TEXT["empty_state"])
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
            with vuetify.VBtn(
                v_if="chat_busy",
                size="small",
                variant="text",
                color="error",
                classes="ml-2",
                click=ctrl.chat_stop,
            ):
                vuetify.VIcon("mdi-stop", start=True)
                html.Span(TEXT["stop_button"])

            with vuetify.VCardActions(classes="pa-2"):
                # While an approval is pending the box answers it rather than
                # starting a second run, so the placeholder has to say so —
                # a silently repurposed input is how people approve the wrong
                # thing.
                # !r quotes and escapes each translation the way a JS string
                # literal needs, so an apostrophe cannot break the expression.
                vuetify.VTextField(
                    v_model=("chat_input",),
                    placeholder=(
                        "pending_approval "
                        "? (pending_approval.allow_edit "
                        f"? {TEXT['input_placeholder_edit']!r} "
                        f": {TEXT['input_placeholder_respond']!r}) "
                        f": {TEXT['input_placeholder']!r}",
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
