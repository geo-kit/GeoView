"""Validation helpers for local artifacts published by GeoAgentPro."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
WORKFLOW_ID = "baseline_reservoir_simulation"
FIELD_STATE_WORKFLOW_IDS = frozenset({WORKFLOW_ID, "reservoir_forecast"})
RESULT_TYPE = "field_states"
OPTIMIZATION_WORKFLOW_ID = "reservoir_optimization"
OPTIMIZATION_RESULT_TYPE = "optimization_result"
OPTIMIZATION_STRATEGY = {"id": "well_control_bhp_npv", "version": 1}
OPTIMIZATION_NUMERICAL_VERSIONS = {
    "julia_version": "1.11.6",
    "jutul_version": "0.4.25",
    "jutuldarcy_version": "0.3.9",
}
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SATURATION_NAMES = frozenset({"SWAT", "SOIL", "SGAS"})
_OPTIMIZATION_ARTIFACTS = {
    "backend_result": "backend_result.json",
    "controls": "controls.csv",
    "objective_history": "objective_history.csv",
    "problem": "problem.json",
    "timeseries": "timeseries.csv",
}
_CONTROLS_COLUMNS = {
    "period",
    "start_date",
    "end_date",
    "well",
    "role",
    "optimized",
    "baseline_control_type",
    "baseline_control_value",
    "baseline_control_unit",
    "candidate_bhp_bar",
    "lower_bound_bar",
    "upper_bound_bar",
    "bounds_unit",
    "at_bound",
}
_TIMESERIES_COLUMNS = {
    "period",
    "start_date",
    "end_date",
    "well",
    "role",
    "baseline_bhp_bar",
    "candidate_bhp_bar",
    "baseline_oil_production_sm3_per_day",
    "candidate_oil_production_sm3_per_day",
    "baseline_gas_production_sm3_per_day",
    "candidate_gas_production_sm3_per_day",
    "baseline_water_production_sm3_per_day",
    "candidate_water_production_sm3_per_day",
    "baseline_water_injection_sm3_per_day",
    "candidate_water_injection_sm3_per_day",
    "baseline_gas_injection_sm3_per_day",
    "candidate_gas_injection_sm3_per_day",
}


class AgentResultError(RuntimeError):
    """Base error for a published agent result."""


class TransientAgentResultError(AgentResultError):
    """The pointer or artifact may still become readable; retry later."""


class InvalidAgentResultError(AgentResultError):
    """The run is readable but violates the production artifact contract."""


class SourceModelMismatchError(InvalidAgentResultError):
    """The result belongs to a model other than the one currently loaded."""


class DuplicateAgentResultError(InvalidAgentResultError):
    """The result was already validated and applied to the current UI."""


@dataclass(frozen=True)
class ValidatedFieldStates:
    pressure: np.ndarray
    saturations: dict[str, np.ndarray]
    welldata: pd.DataFrame
    active_result_reference: dict[str, Any] | None = None


@dataclass(frozen=True)
class ValidatedOptimizationResult:
    """Fully read and validated optimization data, not yet applied to UI state."""

    summary: dict[str, Any]
    controls: pd.DataFrame
    timeseries: pd.DataFrame
    active_result_reference: dict[str, Any]


def source_model_id(path: str | Path) -> str:
    """Return an opaque stable identity without exposing the trusted path."""
    canonical = canonical_model_path(path)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_model_snapshot(
    *,
    loaded_model_path: str | Path,
    grid_dimensions: Sequence[int] | None,
    total_cells: int | None,
    active_cells: int | None,
    phases: Sequence[str],
    start_date: Any,
    end_date: Any,
    time_steps: int | None,
    well_names: Sequence[str],
    available_properties: Sequence[str],
    state_attributes: Sequence[str],
    well_controls: Sequence[Mapping[str, Any]] = (),
    schedule_end_date: Any = None,
) -> dict[str, Any]:
    """Build the compact path-free model facts sent to the Supervisor."""
    dimensions = None
    if grid_dimensions is not None:
        values = tuple(int(value) for value in grid_dimensions)
        if len(values) == 3 and all(value > 0 for value in values):
            dimensions = list(values)
    return {
        "schema_version": 1,
        "model_name": Path(loaded_model_path).name,
        "source_model_id": source_model_id(loaded_model_path),
        "grid_dimensions": dimensions,
        "total_cells": _optional_non_negative_int(total_cells),
        "active_cells": _optional_non_negative_int(active_cells),
        "phases": _safe_strings(phases),
        "start_date": str(start_date) if start_date else None,
        "end_date": str(end_date) if end_date else None,
        "schedule_end_date": (
            str(schedule_end_date) if schedule_end_date else None
        ),
        "time_steps": _optional_non_negative_int(time_steps),
        "well_names": _safe_strings(well_names),
        "well_controls": [
            {
                "well": item.get("well"),
                "role": item.get("role"),
                "status": item.get("status"),
                "control": item.get("control"),
                "value": item.get("value"),
                "unit": item.get("unit"),
            }
            for item in well_controls
            if isinstance(item, Mapping)
        ],
        "available_properties": _safe_strings(available_properties),
        "state_attributes": _safe_strings(state_attributes),
    }


def read_latest_run_id(latest_path: Path) -> str:
    """Read an atomic pointer; malformed JSON is treated as transient."""
    try:
        value = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransientAgentResultError("latest pointer is not readable") from exc
    if not isinstance(value, Mapping):
        raise InvalidAgentResultError("latest pointer must be an object")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise InvalidAgentResultError("latest pointer has an invalid run_id")
    return run_id


def read_run_manifest(results_root: Path, run_id: str) -> dict[str, Any]:
    """Read a run manifest from a path confined below ``results_root``."""
    run_dir = _safe_run_dir(results_root, run_id)
    try:
        value = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TransientAgentResultError("run manifest is not readable") from exc
    if not isinstance(value, dict):
        raise InvalidAgentResultError("run manifest must be an object")
    if value.get("run_id") != run_id:
        raise InvalidAgentResultError("manifest run_id does not match the pointer")
    return value


def load_field_states(
    results_root: Path,
    manifest: Mapping[str, Any],
    *,
    loaded_model_path: str | Path,
    grid_dimensions: Sequence[int],
    actnum: Any,
    current_well_names: Sequence[str],
) -> ValidatedFieldStates:
    """Validate manifest, source identity, pickle payload, and all array shapes."""
    active_reference = _validate_manifest(manifest, loaded_model_path)
    run_id = active_reference["run_id"]
    run_dir = _safe_run_dir(results_root, run_id)
    artifacts = manifest["artifacts"]
    artifact_path = _safe_artifact_file(run_dir, artifacts["states"])
    try:
        with artifact_path.open("rb") as stream:
            payload = pickle.load(stream)
    except (OSError, EOFError) as exc:
        raise TransientAgentResultError("states artifact is not readable") from exc
    except (pickle.PickleError, AttributeError, ImportError, IndexError) as exc:
        raise InvalidAgentResultError("states artifact is invalid") from exc
    validated = validate_field_states(
        payload,
        grid_dimensions=grid_dimensions,
        actnum=actnum,
        current_well_names=current_well_names,
    )
    return ValidatedFieldStates(
        pressure=validated.pressure,
        saturations=validated.saturations,
        welldata=validated.welldata,
        active_result_reference=active_reference,
    )


def load_optimization_result(
    results_root: Path,
    manifest: Mapping[str, Any],
    *,
    loaded_model_path: str | Path,
    current_well_names: Sequence[str],
    active_result_reference: Mapping[str, Any] | None = None,
) -> ValidatedOptimizationResult:
    """Validate source binding and stage the artifacts displayed by GeoView."""
    reference, summary = _validate_optimization_manifest(
        manifest,
        loaded_model_path,
    )
    if (
        active_result_reference is not None
        and active_result_reference.get("workflow_id") == OPTIMIZATION_WORKFLOW_ID
        and active_result_reference.get("run_id") == reference["run_id"]
    ):
        raise DuplicateAgentResultError("optimization result was already applied")

    run_dir = _safe_run_dir(results_root, reference["run_id"])
    artifacts = manifest["artifacts"]
    paths = {
        name: _safe_artifact_file(run_dir, artifacts[name])
        for name in ("controls", "timeseries")
    }
    try:
        total_artifact_bytes = sum(path.stat().st_size for path in paths.values())
    except OSError as exc:
        raise TransientAgentResultError(
            "optimization artifacts are not readable"
        ) from exc
    if total_artifact_bytes > 100 * 1024 * 1024:
        raise InvalidAgentResultError("optimization artifacts exceed the size budget")
    controls = _read_csv_artifact(paths["controls"], _CONTROLS_COLUMNS)
    timeseries = _read_csv_artifact(paths["timeseries"], _TIMESERIES_COLUMNS)
    selected = _validate_controls(controls, current_well_names)
    _validate_timeseries(timeseries, current_well_names, selected)
    return ValidatedOptimizationResult(
        summary=summary,
        controls=controls,
        timeseries=timeseries,
        active_result_reference=reference,
    )


def validate_field_states(
    payload: Any,
    *,
    grid_dimensions: Sequence[int],
    actnum: Any,
    current_well_names: Sequence[str],
) -> ValidatedFieldStates:
    """Validate the complete payload without mutating the current GeoView field."""
    if not isinstance(payload, Mapping):
        raise InvalidAgentResultError("states payload must be an object")
    required = {"pressure", "saturations", "welldata", "wellnames", "dates"}
    if not required.issubset(payload):
        raise InvalidAgentResultError("states payload is missing required fields")

    dimensions = tuple(int(value) for value in grid_dimensions)
    if len(dimensions) != 3 or any(value <= 0 for value in dimensions):
        raise InvalidAgentResultError("loaded grid dimensions are invalid")
    active_mask = np.asarray(actnum).ravel(order="F").astype(bool)
    if active_mask.size != int(np.prod(dimensions)):
        raise InvalidAgentResultError("ACTNUM does not match loaded grid dimensions")
    active_cells = int(np.count_nonzero(active_mask))

    pressure = np.asarray(payload["pressure"], dtype=float)
    if pressure.ndim != 2 or pressure.shape[0] < 2:
        raise InvalidAgentResultError("pressure must have shape (time, active_cell)")
    if pressure.shape[1] != active_cells:
        raise InvalidAgentResultError("pressure does not match loaded active cells")

    raw_saturations = payload["saturations"]
    if not isinstance(raw_saturations, Mapping) or not raw_saturations:
        raise InvalidAgentResultError("saturations must be a non-empty object")
    if not set(raw_saturations).issubset(_SATURATION_NAMES):
        raise InvalidAgentResultError("saturations contain an unknown phase")
    saturations: dict[str, np.ndarray] = {}
    for name, values in raw_saturations.items():
        array = np.asarray(values, dtype=float)
        if array.shape != pressure.shape:
            raise InvalidAgentResultError("saturation shape does not match pressure")
        saturations[str(name)] = array

    raw_wellnames = payload["wellnames"]
    if not isinstance(raw_wellnames, (list, tuple)) or not all(
        isinstance(name, str) and name for name in raw_wellnames
    ):
        raise InvalidAgentResultError("wellnames must be a list of names")
    wellnames = tuple(raw_wellnames)
    if len(wellnames) != len(set(wellnames)):
        raise InvalidAgentResultError("wellnames must be unique")
    if set(wellnames) != set(current_well_names):
        raise InvalidAgentResultError("wellnames do not match the loaded model")

    welldata = payload["welldata"]
    if not isinstance(welldata, pd.DataFrame):
        raise InvalidAgentResultError("welldata must be a DataFrame")
    if wellnames:
        if not {"WELL", "DATE"}.issubset(welldata.columns):
            raise InvalidAgentResultError("welldata is missing WELL or DATE")
        if set(welldata["WELL"].unique()) != set(wellnames):
            raise InvalidAgentResultError("welldata names do not match wellnames")
        counts = welldata.groupby("WELL").size()
        if not np.all(counts.to_numpy() == pressure.shape[0]):
            raise InvalidAgentResultError(
                "welldata time dimension does not match states"
            )
    elif not welldata.empty:
        raise InvalidAgentResultError("welldata must be empty when there are no wells")

    raw_dates = payload["dates"]
    if not isinstance(raw_dates, (list, tuple)) or len(raw_dates) != pressure.shape[0]:
        raise InvalidAgentResultError("dates must match the state time dimension")
    return ValidatedFieldStates(
        pressure=pressure,
        saturations=saturations,
        welldata=welldata,
    )


def to_spatial_states(
    states: ValidatedFieldStates,
    *,
    grid_dimensions: Sequence[int],
    actnum: Any,
) -> ValidatedFieldStates:
    """Prepare fully spatial arrays before the first mutation of GeoView state."""
    dimensions = tuple(int(value) for value in grid_dimensions)
    active_mask = np.asarray(actnum).ravel(order="F").astype(bool)

    def spatial(values: np.ndarray) -> np.ndarray:
        padded = np.zeros((values.shape[0], active_mask.size), dtype=float)
        padded[:, active_mask] = values
        return padded.reshape((values.shape[0], *dimensions), order="F")

    return ValidatedFieldStates(
        pressure=spatial(states.pressure),
        saturations={
            name: spatial(values) for name, values in states.saturations.items()
        },
        welldata=states.welldata,
        active_result_reference=states.active_result_reference,
    )


def apply_staged_field_states(
    field: Any,
    states: ValidatedFieldStates,
    update_callback: Callable[[Any], None],
) -> None:
    """Apply prevalidated spatial states and roll back if rendering fails."""
    previous_states = {}
    for key in ("PRESSURE", "SWAT", "SOIL", "SGAS"):
        try:
            previous_states[key] = getattr(field.states, key)
        except AttributeError:
            pass
    previous_welldata = field.wells.results
    try:
        field.states.pressure = states.pressure
        for key in ("SWAT", "SOIL", "SGAS"):
            try:
                setattr(field.states, key, states.saturations.get(key))
            except AttributeError:
                if key in states.saturations:
                    raise
        field.wells.results = states.welldata
        update_callback(field)
    except Exception:
        for key, value in previous_states.items():
            setattr(field.states, key, value)
        field.wells.results = previous_welldata
        raise


def _validate_optimization_manifest(
    manifest: Mapping[str, Any],
    loaded_model_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise InvalidAgentResultError("unsupported optimization schema_version")
    if manifest.get("workflow_id") != OPTIMIZATION_WORKFLOW_ID:
        raise InvalidAgentResultError("unexpected optimization workflow_id")
    if manifest.get("status") != "ok" or manifest.get("error_code") is not None:
        raise InvalidAgentResultError("optimization result is not successful")
    if manifest.get("type") != OPTIMIZATION_RESULT_TYPE:
        raise InvalidAgentResultError("unexpected optimization result type")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise InvalidAgentResultError("optimization manifest has an invalid run_id")
    if manifest.get("strategy") != OPTIMIZATION_STRATEGY:
        raise InvalidAgentResultError("unsupported optimization strategy")
    if manifest.get("numerical_versions") != OPTIMIZATION_NUMERICAL_VERSIONS:
        raise InvalidAgentResultError("unsupported optimization numerical versions")

    source = manifest.get("source_model")
    if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
        raise InvalidAgentResultError("optimization source_model is invalid")
    size = _non_negative_int(source.get("size"), "source size")
    mtime_ns = _non_negative_int(source.get("mtime_ns"), "source mtime")
    digest = source.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise InvalidAgentResultError("optimization source identity is incomplete")
    if canonical_model_path(source["path"]) != canonical_model_path(loaded_model_path):
        raise SourceModelMismatchError("optimization result belongs to another model")
    actual_size, actual_mtime_ns, actual_digest = _source_fingerprint(loaded_model_path)
    if (size, mtime_ns, digest) != (
        actual_size,
        actual_mtime_ns,
        actual_digest,
    ):
        raise SourceModelMismatchError("loaded model changed after optimization")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or dict(artifacts) != _OPTIMIZATION_ARTIFACTS:
        raise InvalidAgentResultError("optimization artifact set is invalid")
    summary = _validate_optimization_summary(manifest.get("summary"))
    reference = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "workflow_id": OPTIMIZATION_WORKFLOW_ID,
        "result_type": OPTIMIZATION_RESULT_TYPE,
        "source_model_id": source_model_id(loaded_model_path),
        "source_size": size,
        "source_mtime_ns": mtime_ns,
        "source_sha256": digest,
    }
    return reference, summary


def _validate_optimization_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidAgentResultError("optimization summary is missing")
    required = {
        "strategy_id",
        "termination_reason",
        "optimizer_converged",
        "candidate_feasible",
        "candidate_improved",
        "recommended_case",
        "objective",
        "iterations",
        "evaluations",
        "wall_time_seconds",
        "warnings",
    }
    if (
        not required.issubset(value)
        or value.get("strategy_id") != OPTIMIZATION_STRATEGY["id"]
    ):
        raise InvalidAgentResultError("optimization summary schema is invalid")
    if value.get("termination_reason") not in {
        "converged",
        "iteration_limit",
        "time_limit",
        "line_search_failed",
        "objective_stalled",
        "numerical_failure",
    }:
        raise InvalidAgentResultError("optimization termination reason is invalid")
    for key in (
        "optimizer_converged",
        "candidate_feasible",
        "candidate_improved",
    ):
        if not isinstance(value.get(key), bool):
            raise InvalidAgentResultError(f"optimization {key} is invalid")
    iterations = _non_negative_int(value.get("iterations"), "iterations")
    evaluations = _non_negative_int(value.get("evaluations"), "evaluations")
    wall_time = _finite_number(value.get("wall_time_seconds"), "wall time")
    if wall_time < 0:
        raise InvalidAgentResultError("optimization wall time is negative")
    warnings = value.get("warnings")
    if not isinstance(warnings, list) or not all(
        isinstance(warning, str) and warning.strip() for warning in warnings
    ):
        raise InvalidAgentResultError("optimization warnings are invalid")
    objective = _validate_objective(value.get("objective"))
    if value.get("recommended_case") not in {"baseline", "optimized"}:
        raise InvalidAgentResultError("optimization recommendation is invalid")
    return {
        **dict(value),
        "objective": objective,
        "iterations": iterations,
        "evaluations": evaluations,
        "wall_time_seconds": wall_time,
        "warnings": [warning.strip() for warning in warnings],
    }


def _validate_objective(value: Any) -> dict[str, Any]:
    required = {
        "name",
        "direction",
        "currency",
        "baseline",
        "candidate",
        "relative_delta_pct",
    }
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise InvalidAgentResultError("optimization objective schema is invalid")
    currency = value.get("currency")
    if (
        value.get("name") != "discounted_npv"
        or value.get("direction") != "maximize"
        or not isinstance(currency, str)
        or re.fullmatch(r"[A-Z]{3}", currency) is None
    ):
        raise InvalidAgentResultError("optimization objective metadata is invalid")
    baseline = _finite_number(value.get("baseline"), "baseline objective")
    candidate = _finite_number(value.get("candidate"), "candidate objective")
    relative = value.get("relative_delta_pct")
    if relative is not None:
        relative = _finite_number(relative, "relative objective delta")
    return {
        **dict(value),
        "baseline": baseline,
        "candidate": candidate,
        "relative_delta_pct": relative,
    }


def _validate_controls(
    controls: pd.DataFrame,
    current_well_names: Sequence[str],
) -> set[tuple[int, str]]:
    known_wells = set(current_well_names)
    seen: set[tuple[int, str]] = set()
    selected: set[tuple[int, str]] = set()
    for _, row in controls.iterrows():
        period_index = _positive_int(row["period"], "controls period")
        well = _text_cell(row["well"], "controls well")
        role = _text_cell(row["role"], "controls role")
        pair = (period_index, well)
        if (
            pair in seen
            or well not in known_wells
            or role not in {"producer", "injector"}
        ):
            raise InvalidAgentResultError("optimization controls mapping is invalid")
        seen.add(pair)
        is_optimized = _bool_cell(row["optimized"], "optimized flag")
        if not is_optimized:
            if any(
                not pd.isna(row[column])
                for column in (
                    "candidate_bhp_bar",
                    "lower_bound_bar",
                    "upper_bound_bar",
                )
            ):
                raise InvalidAgentResultError(
                    "unoptimized controls contain candidate BHP values"
                )
            continue
        candidate = _finite_number(row["candidate_bhp_bar"], "candidate BHP")
        lower = _finite_number(row["lower_bound_bar"], "lower BHP bound")
        upper = _finite_number(row["upper_bound_bar"], "upper BHP bound")
        if not lower < upper or not lower - 1.0e-8 <= candidate <= upper + 1.0e-8:
            raise InvalidAgentResultError("candidate BHP violates bounds")
        selected.add(pair)
    if not selected:
        raise InvalidAgentResultError("optimization controls are missing")
    return selected


def _validate_timeseries(
    timeseries: pd.DataFrame,
    current_well_names: Sequence[str],
    selected: set[tuple[int, str]],
) -> None:
    known_wells = set(current_well_names)
    seen: set[tuple[int, str]] = set()
    numeric = _TIMESERIES_COLUMNS - {
        "period",
        "start_date",
        "end_date",
        "well",
        "role",
    }
    rate_columns = {
        column for column in numeric if "production" in column or "injection" in column
    }
    for _, row in timeseries.iterrows():
        period_index = _positive_int(row["period"], "timeseries period")
        well = _text_cell(row["well"], "timeseries well")
        role = _text_cell(row["role"], "timeseries role")
        pair = (period_index, well)
        if (
            pair in seen
            or well not in known_wells
            or role not in {"producer", "injector"}
        ):
            raise InvalidAgentResultError("optimization timeseries mapping is invalid")
        _text_cell(row["end_date"], "timeseries end date")
        seen.add(pair)
        for column in numeric:
            number = _finite_number(row[column], column)
            if column in rate_columns and number < -1.0e-9:
                raise InvalidAgentResultError(
                    "directional optimization rate is negative"
                )
    if not selected.issubset(seen):
        raise InvalidAgentResultError("timeseries does not cover selected controls")


def _read_csv_artifact(path: Path, columns: set[str]) -> pd.DataFrame:
    try:
        value = pd.read_csv(path)
    except OSError as exc:
        raise TransientAgentResultError("optimization CSV is not readable") from exc
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise InvalidAgentResultError("optimization CSV is invalid") from exc
    if len(value.columns) != len(columns) or set(value.columns) != columns:
        raise InvalidAgentResultError("optimization CSV schema is invalid")
    if value.empty:
        raise InvalidAgentResultError("optimization CSV is empty")
    return value


def _source_fingerprint(path: str | Path) -> tuple[int, int, str]:
    try:
        source = Path(path).resolve(strict=True)
        before = source.stat()
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = source.stat()
    except OSError as exc:
        raise SourceModelMismatchError("loaded model is unavailable") from exc
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise SourceModelMismatchError("loaded model changed during validation")
    return after.st_size, after.st_mtime_ns, digest.hexdigest()


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise InvalidAgentResultError(f"{label} is invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidAgentResultError(f"{label} is invalid") from exc
    if not math.isfinite(number):
        raise InvalidAgentResultError(f"{label} is not finite")
    return number


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, int | np.integer) and not isinstance(value, bool | np.bool_):
        converted = int(value)
        if converted < 0:
            raise InvalidAgentResultError(f"{label} is invalid")
        return converted
    number = _finite_number(value, label)
    converted = int(number)
    if number != converted or converted < 0:
        raise InvalidAgentResultError(f"{label} is invalid")
    return converted


def _positive_int(value: Any, label: str) -> int:
    converted = _non_negative_int(value, label)
    if converted <= 0:
        raise InvalidAgentResultError(f"{label} is invalid")
    return converted


def _text_cell(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAgentResultError(f"{label} is invalid")
    return value.strip()


def _bool_cell(value: Any, label: str) -> bool:
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, str) and value.casefold() in {"true", "false"}:
        return value.casefold() == "true"
    raise InvalidAgentResultError(f"{label} is invalid")


def canonical_model_path(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(Path(path).resolve(strict=False))))


def _validate_manifest(
    manifest: Mapping[str, Any], loaded_model_path: str | Path
) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise InvalidAgentResultError("unsupported result schema_version")
    if manifest.get("workflow_id") not in FIELD_STATE_WORKFLOW_IDS:
        raise InvalidAgentResultError("unexpected workflow_id")
    if manifest.get("status") != "ok":
        raise InvalidAgentResultError("field states result is not successful")
    if manifest.get("type") != RESULT_TYPE:
        raise InvalidAgentResultError("unexpected result type")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str):
        raise InvalidAgentResultError("manifest has an invalid run_id")
    source = manifest.get("source_model")
    if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
        raise InvalidAgentResultError("manifest source_model is invalid")
    for key in ("size", "mtime_ns"):
        if not isinstance(source.get(key), int) or source[key] < 0:
            raise InvalidAgentResultError("manifest source identity is incomplete")
    digest = source.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise InvalidAgentResultError("manifest source identity is incomplete")
    if canonical_model_path(source["path"]) != canonical_model_path(loaded_model_path):
        raise SourceModelMismatchError("result belongs to a different model")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or not isinstance(
        artifacts.get("states"), str
    ):
        raise InvalidAgentResultError("manifest states artifact is missing")
    return {
        "schema_version": manifest["schema_version"],
        "run_id": run_id,
        "workflow_id": manifest["workflow_id"],
        "result_type": manifest["type"],
        "source_model_id": source_model_id(loaded_model_path),
        "source_size": source["size"],
        "source_mtime_ns": source["mtime_ns"],
        "source_sha256": source["sha256"],
    }


def _safe_run_dir(results_root: Path, run_id: str) -> Path:
    if _RUN_ID.fullmatch(run_id) is None:
        raise InvalidAgentResultError("invalid run_id")
    root = results_root.resolve(strict=False)
    run_dir = (root / run_id).resolve(strict=False)
    if run_dir.parent != root:
        raise InvalidAgentResultError("run path escapes the results directory")
    return run_dir


def _safe_artifact_file(run_dir: Path, relative_path: Any) -> Path:
    if not isinstance(relative_path, str):
        raise InvalidAgentResultError("artifact path must be a string")
    path = Path(relative_path)
    if path.is_absolute() or len(path.parts) != 1 or path.name != relative_path:
        raise InvalidAgentResultError("artifact path must be one relative file")
    resolved = (run_dir / path).resolve(strict=False)
    if resolved.parent != run_dir:
        raise InvalidAgentResultError("artifact path escapes the run directory")
    return resolved


def _safe_strings(values: Sequence[str]) -> list[str]:
    return sorted(
        {value.strip() for value in values if isinstance(value, str) and value.strip()}
    )


def _optional_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    converted = int(value)
    return converted if converted >= 0 else None
