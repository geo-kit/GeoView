"Forecast BHP optimization page."
import os
import json
import asyncio
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trame.widgets import trame, html, plotly, vuetify3 as vuetify
from trame.app import asynchronous

from geocode.field.utils.misc import execute_julia_optimize

from .config import state, ctrl
from .view_1d import CHART_STYLE

# Optimization inputs have no defaults: the user must fill every field before
# the optimization can start.
OPT_FIELDS = ["opt_oil_price", "opt_gas_price", "opt_water_price",
              "opt_water_cost", "opt_gas_cost", "opt_discount_rate", "opt_months",
              "opt_bhp_prod_min", "opt_bhp_prod_max",
              "opt_bhp_inj_min", "opt_bhp_inj_max"]
for _f in OPT_FIELDS:
    setattr(state, _f, None)
state.opt_form_complete = False


def _valid_opt_values(values):
    "Whether all optimization inputs are filled and BHP bounds are ordered."
    if any(value in (None, "") for value in values):
        return False
    try:
        prod_min, prod_max, inj_min, inj_max = map(float, values[-4:])
    except (TypeError, ValueError):
        return False
    return prod_min < prod_max and inj_min < inj_max


@state.change(*OPT_FIELDS)
def _validate_opt_form(**kwargs):
    "Enable the Optimize button only once every input is provided."
    _ = kwargs
    state.opt_form_complete = _valid_opt_values(
        [getattr(state, field) for field in OPT_FIELDS])

state.optimizing = False
state.optimizationFailed = False
state.optResultReady = False
state.opt_errMessage = ""
state.opt_base_npv = 0.0
state.opt_opt_npv = 0.0
state.opt_improvement = 0.0
state.opt_converged = True
state.opt_n_variables = 0

PLOTS = {"plot_opt": None, "opt_df": None}

# Label -> production.csv column, for the per-well/field curve picker below the plot.
OPT_SERIES = {
    "Oil rate (base)": "base_oil_rate_m3_day",
    "Oil rate (optimized)": "opt_oil_rate_m3_day",
    "Water prod (base)": "base_water_rate_m3_day",
    "Water prod (optimized)": "opt_water_rate_m3_day",
    "Water inj (base)": "base_water_inj_m3_day",
    "Water inj (optimized)": "opt_water_inj_m3_day",
}
state.opt_dataOptions = list(OPT_SERIES)
state.opt_dataToShow = None
state.opt_wellnames = ["Field"]
state.opt_wellToShow = "Field"
state.opt_exportPath = ""
state.opt_secondAxis = False


def _build_figure(df):
    "Base-vs-optimized field production rates."
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    series = [
        ("base_oil_rate_m3_day", "Oil (base)", "#888", "solid"),
        ("opt_oil_rate_m3_day", "Oil (optimized)", "#1f9d3c", "solid"),
        ("base_water_rate_m3_day", "Water prod (base)", "#9ab", "dot"),
        ("opt_water_rate_m3_day", "Water prod (optimized)", "#1f77b4", "dot"),
        ("base_water_inj_m3_day", "Water inj (base)", "#d9a", "dash"),
        ("opt_water_inj_m3_day", "Water inj (optimized)", "#d62728", "dash"),
    ]
    if "well" in df:
        rate_columns = [column for column, *_ in series if column in df]
        df = df.groupby(["period", "end_date"], as_index=False)[rate_columns].sum()
    x = df["end_date"]
    for col, name, color, dash in series:
        if col in df:
            fig.add_trace(go.Scatter(
                x=x, y=df[col], name=name,
                line=dict(width=2, color=color, dash=dash)))
    fig.update_layout(
        template=state.plotlyTheme,
        showlegend=True,
        margin={"t": 30, "r": 10, "l": 80, "b": 30},
        legend={"x": 1.01},
    )
    fig.update_xaxes(title_text="Date")
    fig.update_yaxes(title_text="Rate, m3/day")
    return fig


@asynchronous.task
async def optimize_async():
    "Run the forecast BHP optimization driver and plot the result."
    with state:
        state.optimizing = True
        state.optimizationFailed = False
        state.optResultReady = False
        state.opt_errMessage = ""

    try:
        if state.loadedModelPath is None:
            raise ValueError("Model is not loaded.")
        if not state.opt_form_complete:
            raise ValueError("Fill all optimization inputs before optimizing.")

        params = {
            "months": int(state.opt_months),
            "oil-price": float(state.opt_oil_price),
            "gas-price": float(state.opt_gas_price),
            "water-price": float(state.opt_water_price),
            "water-cost": float(state.opt_water_cost),
            "gas-cost": float(state.opt_gas_cost),
            "discount-rate": float(state.opt_discount_rate),
            "bhp-prod-min": float(state.opt_bhp_prod_min),
            "bhp-prod-max": float(state.opt_bhp_prod_max),
            "bhp-inj-min": float(state.opt_bhp_inj_min),
            "bhp-inj-max": float(state.opt_bhp_inj_max),
        }
        result_dir = getattr(state, "simulationResultDir", None)
        if result_dir:
            params["history-cache"] = str(Path(result_dir) / "jutul_state")
        timeout_env = os.environ.get("JUTUL_TIMEOUT_S")
        out_dir = await asyncio.to_thread(
            execute_julia_optimize,
            state.loadedModelPath,
            params=params,
            timeout_s=int(timeout_env) if timeout_env else None,
        )

        summary = json.loads((out_dir / "summary.json").read_text())
        df = pd.read_csv(out_dir / "production.csv")
        fig = _build_figure(df)

    except Exception as err:  # pylint: disable=broad-except
        with state:
            state.opt_errMessage = str(err)
            state.optimizationFailed = True
            state.optimizing = False
        return

    with state:
        state.opt_base_npv = summary["base_npv"]
        state.opt_opt_npv = summary["opt_npv"]
        state.opt_improvement = summary["improvement_pct"]
        state.opt_converged = summary["converged"]
        state.opt_n_variables = summary["n_variables"]
        PLOTS["plot_opt"] = fig
        PLOTS["opt_df"] = df
        wells = sorted(df["well"].unique()) if "well" in df else []
        state.opt_wellnames = ["Field"] + wells
        state.opt_wellToShow = "Field"
        ctrl.update_opt_plot(fig)
        state.optimizing = False
        state.optResultReady = True

ctrl.optimize_async = optimize_async


@state.change("figure_size_opt")
def update_opt_plot(figure_size_opt, **kwargs):
    "Resize the optimization plot."
    _ = kwargs
    if figure_size_opt is None:
        return
    bounds = figure_size_opt.get("size", {})
    width = bounds.get("width", 300)
    height = bounds.get("height", 100)
    if PLOTS['plot_opt'] is None:
        PLOTS['plot_opt'] = make_subplots(specs=[[{"secondary_y": True}]])
        PLOTS['plot_opt'].update_layout(
            showlegend=True,
            margin={'t': 30, 'r': 10, 'l': 80, 'b': 30},
            legend={'x': 1.01,},
            template=state.plotlyTheme,
            )
    PLOTS['plot_opt'].update_layout(height=height, width=width)
    ctrl.update_opt_plot(PLOTS['plot_opt'])


@state.change("plotlyTheme")
def change_plotly_theme_opt(plotlyTheme, **kwargs):
    "Change plotly theme."
    _ = kwargs
    fig = PLOTS['plot_opt']
    if fig is not None:
        fig.layout.template = plotlyTheme
        ctrl.update_opt_plot(fig)


def _select_curve(df, well, col):
    "Per-well rows for `well`, or the field sum across wells when well == 'Field'."
    if "well" in df and well != "Field":
        return df[df["well"] == well]
    if "well" in df:
        return df.groupby(["period", "end_date"], as_index=False)[col].sum()
    return df


def add_opt_line():
    "Overlay the selected well/field production curve onto the optimization plot."
    fig, df = PLOTS["plot_opt"], PLOTS["opt_df"]
    if fig is None or df is None or state.opt_dataToShow is None:
        return
    col = OPT_SERIES[state.opt_dataToShow]
    if col not in df:
        return
    well = state.opt_wellToShow or "Field"
    sub = _select_curve(df, well, col)
    fig.add_trace(go.Scatter(
        x=sub["end_date"], y=sub[col],
        name=f"{well}/{state.opt_dataToShow}", line=dict(width=2)),
        secondary_y=state.opt_secondAxis)
    ctrl.update_opt_plot(fig)
ctrl.add_opt_line = add_opt_line


def clean_opt_plot():
    "Remove every trace from the optimization plot."
    if PLOTS["plot_opt"] is None:
        return
    PLOTS["plot_opt"].data = []
    ctrl.update_opt_plot(PLOTS["plot_opt"])
ctrl.clean_opt_plot = clean_opt_plot


def remove_last_opt_line():
    "Drop the most recently added trace."
    fig = PLOTS["plot_opt"]
    if fig is None or not fig.data:
        return
    fig.data = fig.data[:-1]
    ctrl.update_opt_plot(fig)
ctrl.remove_last_opt_line = remove_last_opt_line


def export_opt_plot():
    "Write the plotted curves to a CSV next to the loaded model."
    fig = PLOTS["plot_opt"]
    if fig is None or not fig.data or not state.loadedModelPath:
        return
    df = pd.concat(
        [pd.Series(tr.y, index=tr.x, name=tr.name) for tr in fig.data],
        axis=1)
    df.index.name = "end_date"
    out = Path(state.loadedModelPath).parent / "optimization_plot.csv"
    df.to_csv(out)
    state.opt_exportPath = str(out)
ctrl.export_opt_plot = export_opt_plot


def _num_field(model, label, suffix=""):
    "A compact numeric input bound to a state variable."
    vuetify.VTextField(
        v_model=(model,),
        label=label,
        type="number",
        suffix=suffix,
        density="compact",
        variant="underlined",
    )


def render_optimization():
    "Optimization page layout."
    with vuetify.VContainer(fluid=True, classes="pa-2"):
        with vuetify.VRow(classes="pa-0 ma-0 justify-center"):
            with vuetify.VBtn("Settings"):
                with vuetify.VMenu(activator="parent", location='bottom', close_on_content_click=False):
                    with vuetify.VContainer(classes="pa-0 ma-0"):
                        with vuetify.VCard(classes="pa-0 ma-0", variant='flat'):
                            with vuetify.VRow(classes="pa-0 ma-0"):
                                with vuetify.VCol(classes="pa-0 ma-2"):
                                        vuetify.VCardText('Production profit', classes="pl-0")
                                        _num_field("opt_oil_price", "Oil price", "$/m3")
                                        _num_field("opt_gas_price", "Gas price", "$/m3")
                                with vuetify.VCol(classes="pa-0 ma-2"):
                                    with vuetify.VCard(variant='flat'):
                                        vuetify.VCardText('Production costs', classes="pl-0")
                                        _num_field("opt_water_cost", "Water injection cost", "$/m3")
                                        _num_field("opt_gas_cost", "Gas injection cost", "$/m3")
                                        _num_field("opt_water_price", "Water production cost", "$/m3")
                                with vuetify.VCol(classes="pa-0 ma-2"):
                                    with vuetify.VCard(variant='flat'):
                                        vuetify.VCardText('Time & discount', classes="pl-0")
                                        _num_field("opt_discount_rate", "Discount rate", "%/yr")
                                        _num_field("opt_months", "Forecast months")
                                with vuetify.VCol(classes="pa-0 ma-2"):
                                    with vuetify.VCard(variant='flat'):
                                        vuetify.VCardText('BHP range', classes="pl-0")
                                        _num_field("opt_bhp_prod_min", "Prod BHP min", "bar")
                                        _num_field("opt_bhp_prod_max", "Prod BHP max", "bar")
                                        _num_field("opt_bhp_inj_min", "Inj BHP min", "bar")
                                        _num_field("opt_bhp_inj_max", "Inj BHP max", "bar")

            with vuetify.VBtn(
                "Optimize",
                color=("(loading | simulating | optimizing | (modelID == 0) | !opt_form_complete) ? '' : '#51b03c'",),
                click=ctrl.optimize_async,
                disabled=("loading | loadFailed | simulating | optimizing | (modelID == 0) | !opt_form_complete",),
            ):
                vuetify.VTooltip(
                    text="Run forecast BHP optimization",
                    activator="parent",
                    location="top")
        with vuetify.VRow(classes="pa-0 ma-0", style="align-items: center"):
            with vuetify.VCol(classes="pa-1 text-center"):
                vuetify.VProgressCircular(
                    v_if="optimizing",
                    color="primary",
                    indeterminate=True,
                    size="28",
                    width="4")
                with vuetify.VCard(
                    v_if="optResultReady & !optimizing",
                    variant="text",
                    classes="pa-0",
                ):
                    vuetify.VCardText(
                        "NPV without optimization {{ (opt_base_npv/1e6).toFixed(3) }} MM$  →  "
                        "with optimization {{ (opt_opt_npv/1e6).toFixed(3) }} MM$   |   "
                        "gain +{{ ((opt_opt_npv-opt_base_npv)/1e6).toFixed(3) }} MM$ "
                        "({{ opt_improvement.toFixed(1) }}%), "
                        "{{ opt_n_variables }} variables",
                        classes="pa-0")
                vuetify.VAlert(
                    v_if="optResultReady & !opt_converged & !optimizing",
                    type="warning",
                    density="compact",
                    text="Optimizer did not improve on continued historical controls.")
                vuetify.VAlert(
                    v_if="optimizationFailed",
                    type="error",
                    density="compact",
                    text=("'Failed: ' + opt_errMessage",))

        with vuetify.VRow(style="width: 100%; height: 70vh", classes="pa-0 ma-0"):
            with vuetify.VCol(classes="pa-0"):
                with trame.SizeObserver("figure_size_opt"):
                    ctrl.update_opt_plot = plotly.Figure(**CHART_STYLE).update
                    update_opt_plot(state.figure_size_opt)

        with vuetify.VRow(
            classes="pa-0 ma-0",
            style="flex-wrap: nowrap; align-items: center",
        ):
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                vuetify.VSelect(
                    v_model=("opt_wellToShow",),
                    items=("opt_wellnames",),
                    label="Select well",
                    density="compact",
                    hide_details=True,
                    variant="outlined")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                vuetify.VSelect(
                    v_model=("opt_dataToShow",),
                    items=("opt_dataOptions",),
                    label="Select data",
                    density="compact",
                    hide_details=True,
                    variant="outlined")
            with vuetify.VCol(cols="auto", classes="pa-1"):
                vuetify.VSwitch(
                    v_model=("opt_secondAxis",),
                    color="primary",
                    label="Second Axis",
                    hide_details=True)
            with vuetify.VCol(cols="auto", classes="pa-1"):
                vuetify.VBtn(
                    "Add line",
                    click=ctrl.add_opt_line,
                    disabled=("!optResultReady",))
            with vuetify.VCol(cols="auto", classes="pa-1"):
                vuetify.VBtn(
                    "Undo",
                    click=ctrl.remove_last_opt_line,
                    disabled=("!optResultReady",))
            with vuetify.VCol(cols="auto", classes="pa-1"):
                vuetify.VBtn(
                    "Clean",
                    click=ctrl.clean_opt_plot,
                    disabled=("!optResultReady",))
            with vuetify.VCol(cols="auto", classes="pa-1"):
                with vuetify.VBtn(
                    "Export",
                    click=ctrl.export_opt_plot,
                    color=("optResultReady ? '#51b03c' : ''",),
                    disabled=("!optResultReady",)):
                    vuetify.VTooltip(
                        text="Export plot data to a csv next to the model",
                        activator="parent",
                        location="top")
