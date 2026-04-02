"Timeseries and PVT pages."
import numpy as np
import pandas as pd
import plotly.express as px
from plotly.subplots import make_subplots
import plotly.graph_objects as go

from trame.widgets import trame, html, plotly, vuetify3 as vuetify

from .config import state, ctrl, FIELD

state.plot_content = ""

PLOTS = {"plot_ts": None,
         "plot_pvt": None,
         "df": pd.DataFrame()}

CHART_STYLE = {
    "mode_bar_buttons_to_remove": (
        "chart_buttons",
        [
            "resetScale2d",
            "zoomIn2d",
            "zoomOut2d",
            "toggleSpikelines",
            "hoverClosestCartesian",
            "hoverCompareCartesian",
        ],
    ),
    "display_logo": ("false",),
}

def reset_ts_widgets():
    "Reset timeseries widgets"
    state.data1dToShow = None
    state.wellNameToShow = None
    state.i_cell = 'Average'
    state.j_cell = 'Average'
    state.k_cell = 'Average'
    state.secondAxis = False
reset_ts_widgets()

def reset_pvt_widgets():
    "Reset pvt widgets"
    state.tableToShow = None
    state.tableXAxis = None
    state.domains = []
    state.domainMin = 0
    state.domainMax = 0
    state.domainStep = None
    state.domainToShow = None
    state.needDomain = False
    state.domainName = None
    state.gridData = True
    state.wellData = True
reset_pvt_widgets()

@state.change('modelID')
def reset_plots(*args, **kwargs):
    "Reset all 1d plots."
    _ = args, kwargs
    clean_ts_plot()
    reset_ts_widgets()

    clean_pvt_plot()
    reset_pvt_widgets()

@state.change("plotlyTheme")
def change_plotly_theme(plotlyTheme, **kwargs):
    "Change plotly theme."
    _ = kwargs
    fig = PLOTS['plot_ts']
    if fig is not None:
        fig.layout.template = plotlyTheme
        ctrl.update_ts_plot(fig)
    fig = PLOTS['plot_pvt']
    if fig is not None:
        fig.layout.template = plotlyTheme
        ctrl.update_pvt_plot(fig)

@state.change("data1dToShow")
def update_ts_widgets(data1dToShow, **kwargs):
    "Update timeseries widgets."
    _ = kwargs
    if data1dToShow is None:
        return
    state.gridData = data1dToShow in state.statesAttrs
    state.wellData = data1dToShow in state.wellsAttrs
    if state.wellData:
        state.gridItemToShow = None
        wellnames = []
        if 'RESULTS' in FIELD['model'].wells:
            wellnames = FIELD['model'].wells.names
        state.wellnames = wellnames
    if state.gridData:
        state.wellNameToShow = None

def add_line_to_plot():
    "Add line to timeseries plot."
    fig = PLOTS['plot_ts']
    if fig is None:
        return

    if state.data1dToShow is None:
        return

    if state.gridData:
        data = getattr(FIELD['model'].states, state.data1dToShow)
        cells = np.array([state.i_cell, state.j_cell, state.k_cell])
        avr = cells == 'Average'
        if np.any(avr):
            ids = np.where(avr)[0]
            data = data.mean(axis=tuple(ids+1))
        icells = cells[~avr].astype(int)
        if len(icells) > 0:
            data = data[:, *icells]
        dates = [t.strftime('%Y-%m-%d') for t in FIELD['dates']]
        if np.any(avr):
            cells[avr] = ":"
        name = '{} ({}, {}, {})'.format(state.data1dToShow, *cells)

    if state.wellData:
        if state.wellNameToShow is None:
            return
        df = FIELD['model'].wells[state.wellNameToShow].RESULTS
        data = df[state.data1dToShow].values
        dates = df.DATE.dt.strftime("%Y-%m-%d")
        name = state.wellNameToShow + '/' + state.data1dToShow

    fig.add_trace(go.Scatter(
        x=dates,
        y=data,
        name=name,
        line=dict(width=2)
    ), secondary_y=state.secondAxis)

    fig.update_xaxes(title_text="Date")

    dates = pd.to_datetime(dates)
    if PLOTS['df'].empty:
        PLOTS['df'] = pd.DataFrame({name: data}, index=dates)
        PLOTS['df'].index.rename('DATE', inplace=True)
    else:
        try:
            PLOTS['df'].loc[dates, name] = data
        except Exception as err:
            PLOTS['df'][name] = None
    state.plot_content = PLOTS['df'].to_csv()
    ctrl.update_ts_plot(fig)

ctrl.add_line_to_plot = add_line_to_plot

def clean_ts_plot():
    "Clean timeseries plot."
    if PLOTS['plot_ts'] is None:
        return
    PLOTS['plot_ts'].data = []
    PLOTS['df'] = pd.DataFrame()
    ctrl.update_ts_plot(PLOTS['plot_ts'])

ctrl.clean_ts_plot = clean_ts_plot

def remove_last_line():
    "Remove last line from timeseries plot."
    if not PLOTS['plot_ts'].data:
        return
    PLOTS['plot_ts'].data = PLOTS['plot_ts'].data[:-1]
    PLOTS['df'] = PLOTS['df'].drop(labels=PLOTS['df'].columns[-1], axis=1) 
    ctrl.update_ts_plot(PLOTS['plot_ts'])

ctrl.remove_last_line = remove_last_line

@state.change("figure_size_1d")
def update_ts_plot(figure_size_1d, **kwargs):
    "Update timeseries plot size."
    _ = kwargs
    if figure_size_1d is None:
        return
    bounds = figure_size_1d.get("size", {})
    width = bounds.get("width", 300)
    height = bounds.get("height", 100)
    if PLOTS['plot_ts'] is None:
        PLOTS['plot_ts'] = make_subplots(specs=[[{"secondary_y": True}]])
        PLOTS['plot_ts'].update_layout(
            showlegend=True,
            margin={'t': 30, 'r': 10, 'l': 80, 'b': 30},
            legend={'x': 1.01,},
            template=state.plotlyTheme,
            )
    PLOTS['plot_ts'].update_layout(height=height, width=width)
    ctrl.update_ts_plot(PLOTS['plot_ts'])

@state.change("tableToShow", "tableXAxis")
def update_pvt_widgets(tableToShow, tableXAxis, **kwargs):
    "Update pvt widgets."
    _ = kwargs
    if tableToShow is None:
        return
    table = getattr(FIELD['model'].tables, tableToShow)[0]
    if len(table.domain) == 1:
        state.needDomain = False
    elif len(table.domain) == 2:
        state.domains = list(table.index.names)
        if tableXAxis is not None:
            i = (state.domains.index(tableXAxis) + 1)%2
            state.domainName = state.domains[i]
            state.domainMin = table.index.get_level_values(i).min()
            state.domainMax = table.index.get_level_values(i).max()
            state.domainStep = (state.domainMax - state.domainMin) / 100
            state.domainToShow = (state.domainMin + state.domainMax) / 2
        state.needDomain = True

def plot_1d_table(fig, table):
    "Plot 1d table."
    colors = px.colors.qualitative.Plotly
    x = table.index.values
    layout = {}

    for i, col in enumerate(table.columns):
        c = colors[i%len(colors)]
        fig.add_trace(go.Scatter(
            x=x,
            y=table[col].values,
            yaxis=None if i==0 else 'y'+str(i+1),
            name=col,
            line=dict(width=2, color=c)
            ))
        key = 'yaxis' if i==0 else 'yaxis' + str(i+1)
        layout[key] = dict(
            title=dict(text=col, font=dict(color=c)),
            side="right" if i > 0 else None,
            anchor="free" if i > 0 else None,
            overlaying="y" if i > 0 else None,
            autoshift=True if i > 0 else None,
            tickfont=dict(color=c)
            )

    fig.update_layout(
        xaxis=dict(domain=[0, 1.02-0.02*len(table.columns)]),
        **layout)
    fig.update_xaxes(title_text=table.index.name)
    return fig

def plot_table(tableToShow, tableXAxis, domainToShow, height, width):
    "Plot table."
    fig = go.Figure()
    fig.update_layout(
        height=height,
        width=width,
        showlegend=False,
        template=state.plotlyTheme,
        margin={'t': 30, 'r': 50, 'l': 80, 'b': 30},
        )

    if tableToShow is None:
        return fig

    table = getattr(FIELD['model'].tables, tableToShow)[0]
    domain = list(table.domain)

    if len(domain) == 1:
        fig = plot_1d_table(fig, table)
    elif len(domain) == 2:
        if tableXAxis is None:
            return fig
        if domainToShow is None:
            return fig

        new_table = pd.DataFrame(columns=table.columns)
        vals = [list(set(table.index.get_level_values(0))),
                list(set(table.index.get_level_values(1)))]

        i = list(table.index.names).index(tableXAxis)
        x = np.linspace(min(vals[i])*1.001, max(vals[i])*0.999, 100)

        inp = np.zeros((len(x), 2))
        inp[:, i] = x
        inp[:, (i+1)%2] = domainToShow

        new_table = pd.DataFrame(table(inp),
                                 columns=table.columns,
                                 index=x)
        new_table.index.name = tableXAxis
        fig = plot_1d_table(fig, new_table)

    return fig

@state.change("figure_size_1d", "tableToShow", "tableXAxis", "domainToShow")
def update_pvt_plot(figure_size_1d, tableToShow, tableXAxis, domainToShow, **kwargs):
    "Update pvt plot."
    _ = kwargs
    if figure_size_1d is None:
        return
    bounds = figure_size_1d.get("size", {})
    width = bounds.get("width", 300)
    height = bounds.get("height", 100)
    PLOTS['plot_pvt'] = plot_table(tableToShow, tableXAxis, domainToShow, height, width)
    ctrl.update_pvt_plot(PLOTS['plot_pvt'])

def clean_pvt_plot():
    "Delete lines in pvt plot."
    if PLOTS['plot_pvt'] is None:
        return
    PLOTS['plot_pvt'].data = []
    ctrl.update_pvt_plot(PLOTS['plot_pvt'])

def render_ts():
    "Timeseries page layout."
    with vuetify.VContainer(fluid=True, style='align-items: top', classes="pa-0 ma-0"):
        with vuetify.VRow(classes='pa-0 ma-0'):
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    v_model=("data1dToShow",),
                    items=("data1d", ),
                    label="Select data"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    disabled=("wellData",),
                    v_model=("i_cell",),
                    items=("i_cells", ),
                    label="I index"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    disabled=("wellData",),
                    v_model=("j_cell",),
                    items=("j_cells", ),
                    label="J index"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    disabled=("wellData",),
                    v_model=("k_cell",),
                    items=("k_cells", ),
                    label="K index"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    disabled=("gridData",),
                    v_model=("wellNameToShow",),
                    items=("wellnames", ),
                    label="Select well"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSwitch(
                    v_model=("secondAxis",),
                    color="primary",
                    label="Second Axis",
                    hide_details=True)
            with vuetify.VCol(classes='pa-0 ma-0', style='flex-grow: 0'):
                with vuetify.VBtn('Add line',
                    click=ctrl.add_line_to_plot,
                    classes='mt-2'):
                    vuetify.VTooltip(
                        text='Add line to the plot',
                        activator="parent",
                        location="bottom")
            with vuetify.VCol(classes='pa-0 mt-0', style='flex-grow: 0'):
                with vuetify.VBtn('Undo',
                    click=ctrl.remove_last_line,
                    classes='mt-2'):
                    vuetify.VTooltip(
                        text='Delete last line from the plot',
                        activator="parent",
                        location="bottom")
            with vuetify.VCol(classes='pa-0 ma-0', style='flex-grow: 0'):
                with vuetify.VBtn('Clean',
                    click=ctrl.clean_ts_plot,
                    classes='mt-2'):
                    vuetify.VTooltip(
                        text='Delete lines from the plot',
                        activator="parent",
                        location="bottom")

        with vuetify.VRow(style="width: 100%; height: 75vh", classes='pa-0 ma-0'):
            with vuetify.VCol(classes='pa-0'):
                with trame.SizeObserver("figure_size_1d"):
                    ctrl.update_ts_plot = plotly.Figure(**CHART_STYLE).update
                    update_ts_plot(state.figure_size_1d)

    with html.Div(style='position: fixed; bottom: 3px; right: 0;'):
        with vuetify.VBtn("Export",
            click="utils.download('data.csv', plot_content, 'text/csv')",
            color=("max_timestep == 0 ? '' : '#51b03c'",),
            disabled=('max_timestep == 0',)):
            vuetify.VTooltip(
                text='Export plot data to csv',
                activator="parent",
                location="left")


def render_pvt():
    "PVT page layout."
    with vuetify.VContainer(fluid=True, style='align-items: top', classes="pa-0 ma-0"):
        with vuetify.VRow(classes='pa-0 ma-0'):
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    v_model=("tableToShow",),
                    items=("tables", ),
                    label="Select data"
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                vuetify.VSelect(
                    v_model=("tableXAxis",),
                    items=("domains", ),
                    label="Select x-axis",
                    disabled=("!needDomain",),
                    )
            with vuetify.VCol(classes='pa-0 ma-0'):
                with vuetify.VSlider(
                    label=('domainName',),
                    disabled=("!needDomain",),
                    v_model=("domainToShow", ),
                    min=("domainMin",),
                    max=("domainMax",),
                    step=("domainStep",),
                    hide_details=False,
                    classes='mt-2',
                    dense=False
                    ):
                    with vuetify.Template(v_slot_append=True,
                        properties=[("v_slot_append", "v-slot:append")],):
                        vuetify.VTextField(
                            v_model=("domainToShow",),
                            density="compact",
                            style="width: 80px",
                            type="number",
                            variant="outlined",
                            hide_details=True)
        with vuetify.VRow(style="width: 100%; height: 75vh", classes='pa-0 ma-0'):
            with vuetify.VCol(classes='pa-0'):
                with trame.SizeObserver("figure_size_1d"):
                    ctrl.update_pvt_plot = plotly.Figure(**CHART_STYLE).update
                    update_pvt_plot(state.figure_size_1d, None, None, None)
