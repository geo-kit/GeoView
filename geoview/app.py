"App layout."
import sys
import pandas as pd
import multiprocessing
from trame.widgets import html, client, vuetify3 as vuetify
from trame.ui.vuetify3 import VAppLayout

try:
    from geocode import Field
except ModuleNotFoundError:
    try:
        sys.path.append('../GeoCode')
    except:
        raise ModuleNotFoundError("Module GeoCode is not found.")

from .src.config import server, state, ctrl, renderer, jserver
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
    manager = multiprocessing.Manager()
    jserver['queue'] = manager.Queue()
    jserver['results'] = manager.dict()
    process = multiprocessing.Process(target=simulate,
                                      args=[jserver['queue'], jserver['results']])
    process.daemon = True
    process.start()

    server.start(timeout=100)
