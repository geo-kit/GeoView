"App layout."
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
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
from .src.config import args, agent_enabled, server, state, ctrl, renderer, jserver
from .src.home import render_home, make_empty_grid
from .src.view_3d import render_3d
from .src.view_2d import render_2d
from .src.view_1d import render_ts, render_pvt
from .src.common import reset_camera
from .src.info import render_info
from .src.script import render_script
from .src.help import render_help
from .src.simulation import simulate

state.theme = 'light'
state.sideBarColor = "grey-lighten-4"
state.plotlyTheme = 'plotly'
state.bgColor = 'white'


def _project_root():
    """Return the directory containing the GeoView and GeoAgent projects."""
    return Path(__file__).resolve().parents[2]


def _agent_python(agent_dir):
    """Return the Python executable from GeoAgent's virtual environment."""
    if os.name == "nt":
        return agent_dir / ".venv" / "Scripts" / "python.exe"
    return agent_dir / ".venv" / "bin" / "python"


def _start_agent_process(model, environment):
    """Start GeoAgent in its own Python environment."""
    agent_dir = _project_root() / "GeoAgent"
    agent_script = agent_dir / "examples" / "agent.py"
    python_executable = _agent_python(agent_dir)

    for path, description in (
        (agent_dir, "GeoAgent project directory"),
        (python_executable, "GeoAgent Python executable"),
        (agent_script, "GeoAgent entry point"),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{description} was not found: {path}")

    print(f"Starting GeoAgent with {model}...")
    process = subprocess.Popen(
        [str(python_executable), str(agent_script), "--model", model],
        cwd=agent_dir,
        env=environment,
    )
    print(f"GeoAgent started (PID {process.pid}).")
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


if __name__ == "__main__":
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
            print("Starting GeoView...")
        server.start(timeout=100)
    finally:
        _stop_agent_process(agent_process)
