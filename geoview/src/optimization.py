"Forecast BHP optimization page."
import os
import json
import asyncio
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

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

PLOTS = {"plot_opt": None}


def _out_dir():
    "Where the driver writes its output, mirroring the simulation pipeline."
    case_path = Path(state.loadedModelPath)
    out_root_env = os.environ.get("JUTUL_OUT_ROOT")
    out_root = Path(out_root_env) if out_root_env else case_path.parent / "jutul_runs"
    return out_root / f"{case_path.stem}_optimization"


def _build_figure(df):
    "Base-vs-optimized field production rates."
    fig = go.Figure()
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

        out_dir = _out_dir()
        params = {
            "months": int(state.opt_months),
            "granularity": "per-well",
            "oil-price": float(state.opt_oil_price),
            "gas-price": float(state.opt_gas_price),
            # produced water is a cost -> negative price for npv_objective
            "water-price": -abs(float(state.opt_water_price)),
            "water-cost": float(state.opt_water_cost),
            "gas-cost": float(state.opt_gas_cost),
            "discount-rate": float(state.opt_discount_rate) / 100.0,
            "bhp-prod-min": float(state.opt_bhp_prod_min),
            "bhp-prod-max": float(state.opt_bhp_prod_max),
            "bhp-inj-min": float(state.opt_bhp_inj_min),
            "bhp-inj-max": float(state.opt_bhp_inj_max),
        }
        result_dir = getattr(state, "simulationResultDir", None)
        if result_dir:
            params["history-cache"] = str(Path(result_dir) / "jutul_state")
        timeout_env = os.environ.get("JUTUL_TIMEOUT_S")
        await asyncio.to_thread(
            execute_julia_optimize,
            state.loadedModelPath, out_dir,
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
        ctrl.update_opt_plot(fig)
        state.optimizing = False
        state.optResultReady = True

ctrl.optimize_async = optimize_async


@state.change("figure_size_opt", "plotlyTheme")
def update_opt_plot(figure_size_opt, **kwargs):
    "Resize/retheme the optimization plot."
    _ = kwargs
    fig = PLOTS["plot_opt"]
    if fig is None or figure_size_opt is None:
        return
    bounds = figure_size_opt.get("size", {})
    fig.update_layout(
        width=bounds.get("width", 300),
        height=bounds.get("height", 100),
        template=state.plotlyTheme,
    )
    ctrl.update_opt_plot(fig)


def _num_field(model, label, suffix=""):
    "A compact numeric input bound to a state variable."
    vuetify.VTextField(
        v_model=(model,),
        label=label,
        type="number",
        suffix=suffix,
        density="compact",
        hide_details=True,
        variant="outlined",
    )


def render_optimization():
    "Optimization page layout."
    with vuetify.VContainer(fluid=True, classes="pa-2"):
        with vuetify.VRow(
            classes="pa-0 ma-0",
            style="flex-wrap: nowrap; align-items: center",
        ):
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_oil_price", "Oil price", "$/m3")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_gas_price", "Gas price", "$/m3")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_water_price", "Water handling", "$/m3")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_water_cost", "Water injection", "$/m3")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_gas_cost", "Gas injection", "$/m3")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_discount_rate", "Discount rate", "%/yr")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_months", "Forecast months")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_bhp_prod_min", "Prod BHP min", "bar")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_bhp_prod_max", "Prod BHP max", "bar")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_bhp_inj_min", "Inj BHP min", "bar")
            with vuetify.VCol(classes="pa-1", style="min-width: 0"):
                _num_field("opt_bhp_inj_max", "Inj BHP max", "bar")
            with vuetify.VCol(cols="auto", classes="pa-1"):
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

        with vuetify.VRow(style="width: 100%; height: 78vh", classes="pa-0 ma-0"):
            with vuetify.VCol(classes="pa-0"):
                with trame.SizeObserver("figure_size_opt"):
                    ctrl.update_opt_plot = plotly.Figure(**CHART_STYLE).update
