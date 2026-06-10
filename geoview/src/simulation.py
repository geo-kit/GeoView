"""JutulDarcy simulation pipeline.

The worker process pulls (task_id, path) tasks from a queue, runs the Julia
driver via execute_julia_models and loads its on-disk output through
georead.jutul.load.
"""
import hashlib
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd


_SAT_NAME_TO_ATTR = {"SWAT": "swat", "SOIL": "soil", "SGAS": "sgas"}


def _stable_runid(case_path):
    "Build a runid from the .DATA file name and content hash."
    digest = hashlib.sha256(case_path.read_bytes()).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", case_path.stem)[:50]
    return f"{stem}-{digest}"


def _scatter_to_natural(arr, active_to_natural, n_natural):
    "Expand (n_steps, n_active) to the natural grid with NaN in inactive cells."
    nat = np.full((arr.shape[0], n_natural), np.nan, dtype=arr.dtype)
    nat[:, active_to_natural] = arr
    return nat


def jutul_results_to_field(jr, output):
    "Convert from JutulResults to Field data."
    grid = jr.manifest["grid"]
    n_natural = int(grid["nx"]) * int(grid["ny"]) * int(grid["nz"])

    output["pressure"] = _scatter_to_natural(jr.pressure, jr.active_to_natural, n_natural)

    sats = {}
    for out_name, attr in _SAT_NAME_TO_ATTR.items():
        arr = getattr(jr, attr)
        if arr is not None:
            sats[out_name] = _scatter_to_natural(arr, jr.active_to_natural, n_natural)
    output["saturations"] = sats

    welldata_frames = []
    for name, df in jr.wells.items():
        # Well rows cover the report steps while dates also include the start
        # date (state0), so prepend a zero-rate record to align row s with
        # dates[s].
        wf = df.drop(columns="time_days")
        record0 = pd.DataFrame([{c: 0.0 for c in wf.columns}])
        wf = pd.concat([record0, wf], ignore_index=True)
        wf.insert(0, "WELL", name)
        wf.insert(1, "DATE", pd.to_datetime(jr.dates[: len(wf)]))
        welldata_frames.append(wf)
    output["welldata"] = (
        pd.concat(welldata_frames, ignore_index=True) if welldata_frames
        else pd.DataFrame()
    )
    output["wellnames"] = list(jr.wells.keys())
    output["dates"] = jr.dates


def _simulate_subprocess(path, results, *, out_root, runid, restart, timeout_s):
    "Run the Julia driver and load its on-disk output."
    from geocode.field.utils.misc import execute_julia_models
    from georead.jutul import load as jutul_load

    case_dir = execute_julia_models(
        runid=runid,
        case_path=path,
        out_root=out_root,
        restart=restart,
        timeout_s=timeout_s,
    )
    jutul_results_to_field(jutul_load(case_dir), results)


def simulate(queue, results, timeout=1):
    """Simulation pipeline.

    Environment toggles:
        JUTUL_OUT_ROOT  -> output directory, defaults to <case_dir>/jutul_runs
        JUTUL_RESTART   -> none|latest|step:N, default 'none' (always
                           recompute); 'latest' reuses the JLD2 cache
        JUTUL_TIMEOUT_S -> per-run timeout in seconds, default unlimited
    """
    _ = timeout
    while True:
        task_id, path = queue.get()
        try:
            case_path = Path(path)
            out_root_env = os.environ.get("JUTUL_OUT_ROOT")
            out_root = Path(out_root_env) if out_root_env else case_path.parent / "jutul_runs"
            out_root.mkdir(parents=True, exist_ok=True)
            restart = os.environ.get("JUTUL_RESTART", "none")
            if restart.startswith("step:"):
                restart = int(restart.split(":", 1)[1])
            timeout_env = os.environ.get("JUTUL_TIMEOUT_S")
            _simulate_subprocess(
                path, results,
                out_root=out_root,
                runid=_stable_runid(case_path),
                restart=restart,
                timeout_s=int(timeout_env) if timeout_env else None,
            )
            results['status'] = None
        except Exception as err:  # pylint: disable=broad-except
            results['status'] = str(err)
        results[task_id] = None
