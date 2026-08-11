"App layout."
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

from trame.widgets import html, client, vuetify3 as vuetify
from trame.ui.vuetify3 import VAppLayout

try:
    from geocode import Field
except ModuleNotFoundError:
    try:
        sys.path.append('../GeoCode')
    except:
        raise ModuleNotFoundError("Module GeoCode is not found.")

from .src.agent_setup import configure_agent
from .src.config import (
    AGENT_DIR_NAME, AGENT_PROFILE, AGENT_RESULT_DIR, args, agent_enabled, server,
    state, ctrl, jserver)
from .src.home import render_home, make_empty_grid
from .src.view_3d import render_3d
from .src.view_2d import render_2d
from .src.view_1d import render_ts, render_pvt
from .src.common import reset_camera
from .src.info import render_info
from .src.script import render_script
from .src.help import render_help
from .src.simulation import simulate
from .src.agent_chat import render_chat_fab, render_chat_panel, watch_agent_results
from .src.optimization import render_optimization

state.theme = 'light'
state.sideBarColor = "grey-lighten-4"
state.plotlyTheme = 'plotly'
state.bgColor = 'white'


def _project_root():
    """Return the directory containing the GeoView and GeoAgent projects."""
    return Path(__file__).resolve().parents[2]


def _agent_root():
    """Return the agent project directory checked out next to GeoView.

    ``GeoAgent`` by default; ``GEOVIEW_AGENT_PROFILE=pro`` selects ``GeoAgentPro``
    (see src/config.py), so a demo switches between the two without editing code.
    """
    return _project_root() / AGENT_DIR_NAME


def _load_agent_env():
    """Fill provider credentials from ``GeoAgent/.env`` so the picker need not ask.

    Reads simple ``KEY=VALUE`` lines (``#`` comments and blanks ignored) and only
    sets names not already present, so a value exported in the real environment
    still wins. This is why the OpenAI/other API keys are picked up automatically
    instead of prompting for them.
    """
    env_file = _agent_root() / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _agent_langgraph(agent_dir):
    """Return the langgraph CLI executable from GeoAgent's virtual environment."""
    if os.name == "nt":
        return agent_dir / ".venv" / "Scripts" / "langgraph.exe"
    return agent_dir / ".venv" / "bin" / "langgraph"


def _start_agent_process(qualified_model, environment):
    """Start the GeoAgent LangGraph server so the in-app chat can reach it.

    ``qualified_model`` is the ``provider:model`` string chosen in GeoView and
    ``environment`` the provider credentials/URLs prepared by ``configure_agent``.
    Both are handed to the child so the LangGraph server boots already using the
    selected model (GeoAgent reads ``GEOAGENT_MODEL`` at import).
    """
    agent_dir = _agent_root()
    langgraph_executable = _agent_langgraph(agent_dir)

    for path, description in (
        (agent_dir, "GeoAgent project directory"),
        (langgraph_executable, "GeoAgent langgraph executable"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{description} was not found: {path}")

    # Force UTF-8 stdio so GeoAgent's rich console does not crash with
    # UnicodeEncodeError on legacy Windows code pages (e.g. cp1251).
    # GEOVIEW_RESULT_DIR is the agent's half of the artifact contract: passing it
    # here keeps it out of the prompt, so the model cannot get the path wrong.
    agent_env = {
        **environment,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "GEOAGENT_MODEL": qualified_model,
        "GEOVIEW_RESULT_DIR": str(AGENT_RESULT_DIR),
    }

    process = subprocess.Popen(
        [
            str(langgraph_executable), "dev",
            "--host", "127.0.0.1",
            "--port", "2024",
            "--no-browser",
            "--no-reload",
            # GeoAgent's tools (Julia simulation, file IO) make synchronous blocking
            # calls; without this the dev server aborts runs with BlockingError.
            "--allow-blocking",
        ],
        cwd=agent_dir,
        env=agent_env,
    )
    # Name the agent that actually started: the profile is an environment
    # variable, so the console is the only place to catch a stale one.
    print(
        f"{AGENT_DIR_NAME} LangGraph server started (PID {process.pid}) on "
        f"http://127.0.0.1:2024 using {qualified_model} "
        f"[profile={AGENT_PROFILE}, dir={agent_dir}]."
    )
    return process


def _stop_agent_process(process):
    """Stop a GeoAgent process started by this application."""
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    print("GeoAgent stopped.")


def change_theme(*args, **kwargs):
    "Change app theme."
    _ = args, kwargs
    if state.theme == 'light':
        state.theme = 'dark'
        state.sideBarColor = "grey-darken-4"
        state.plotlyTheme = 'plotly_dark'
        state.bgColor = 'black'
    else:
        state.theme = 'light'
        state.sideBarColor = "grey-lighten-4"
        state.plotlyTheme = 'plotly'
        state.bgColor = 'white'
ctrl.change_theme = change_theme

make_empty_grid()
reset_camera()

with VAppLayout(server, theme=('theme',)) as layout:
    style = client.Style("body { background-color: white }")
    ctrl.update_style = style.update
    with layout.root:
        with vuetify.VAppBar(app=True, clipped_left=True, density="compact"):
            vuetify.VToolbarTitle("GeoView")
            vuetify.VSpacer()
            with vuetify.VTabs(v_model=('activeTab', 'home')):
                vuetify.VTab('Home', value="home")
                vuetify.VTab('Optimization', value="opt")
                vuetify.VTab('3d view', value="3d")
                vuetify.VTab('2d view', value="2d")
                vuetify.VTab('Timeseries', value="ts")
                vuetify.VTab('PVT/RP', value="pvt")
                vuetify.VTab('Info', value="info")
                vuetify.VTab('Script', value="script")
            vuetify.VSpacer()

            with vuetify.VBtn(icon=True, click=ctrl.change_theme):
                vuetify.VIcon("mdi-lightbulb-multiple-outline")
                vuetify.VTooltip(
                    text='Switch between light and dark theme',
                    activator="parent",
                    location="bottom")
            with vuetify.VBtn(icon=True):
                vuetify.VTooltip(
                    text='Help page',
                    activator="parent",
                    location="bottom")
                vuetify.VIcon("mdi-help-circle-outline")
                with vuetify.VOverlay(activator="parent",
                    location_strategy="connected"):
                    render_help()

        with vuetify.VMain():
            with html.Div(v_if="activeTab === 'home'", classes="fill-height"):
                render_home()
                render_chat_fab()
                render_chat_panel()
            with html.Div(v_if="activeTab === '3d'", classes="fill-height"):
                render_3d()
            with html.Div(v_if="activeTab === '2d'", classes="fill-height"):
                render_2d()
            with html.Div(v_if="activeTab === 'ts'", classes="fill-height"):
                render_ts()
            with html.Div(v_if="activeTab === 'pvt'", classes="fill-height"):
                render_pvt()
            with html.Div(v_if="activeTab === 'info'"):
                render_info()
            with html.Div(v_if="activeTab === 'script'"):
                render_script()
            with html.Div(v_if="activeTab === 'opt'", classes="fill-height"):
                render_optimization()


def server_start():
    # Select the GeoAgent provider/model *before* anything is launched, so the
    # LangGraph server later comes up already using that choice. Pull provider
    # credentials from GeoAgent/.env first so known API keys aren't prompted for.
    if agent_enabled:
        _load_agent_env()
    try:
        agent_launch = configure_agent(args) if agent_enabled else None
    except RuntimeError as error:
        raise SystemExit(f"GeoAgent setup failed: {error}") from None

    manager = multiprocessing.Manager()
    jserver['queue'] = manager.Queue()
    jserver['results'] = manager.dict()
    process = multiprocessing.Process(target=simulate,
                                      args=[jserver['queue'], jserver['results']])
    process.daemon = True
    process.start()

    agent_process = None
    try:
        if agent_launch:
            agent_process = _start_agent_process(*agent_launch)
            ctrl.on_server_ready.add(lambda *a, **kw: watch_agent_results())
        server.start(timeout=100)
    finally:
        _stop_agent_process(agent_process)


if __name__ == "__main__":
    server_start()
