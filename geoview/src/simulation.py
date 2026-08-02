"""JutulDarcy simulation utils."""
import importlib
from datetime import timedelta
from queue import Empty
import pandas as pd
import numpy as np
import time


def well_states(well, rates, dates, start_date):
    "Create dataframe with well results."
    states_df = pd.concat([dates, pd.DataFrame(rates)], axis=1)
    record0 = pd.DataFrame([[start_date] + [0.0]*(len(rates.columns))],
                           columns=states_df.columns)
    states_df = pd.concat([record0, states_df])
    states_df['WELL'] = well
    return states_df[['WELL'] + [col for col in states_df.columns if col != 'WELL']]

def results2field(case, res, output):
    "Convert from JutulDarcy to Field data."
    jl = importlib.import_module('juliacall').Main
    
    sat_map = {'JutulDarcy.AqueousPhase()': 'SWAT',
               'JutulDarcy.LiquidPhase()': 'SOIL',
               'JutulDarcy.VaporPhase()': 'SGAS'}

    sat_names = [sat_map[str(k)] for k in case.model.models.Reservoir.system.phases]

    state0_pressure = np.array(
        jl.seval("state0 -> state0[:Reservoir][:Pressure]")(case.state0)).reshape(1, -1)

    state0_sats = np.array(
        jl.seval("state0 -> state0[:Reservoir][:Saturations]")(case.state0)
        ).reshape(1, len(sat_names), -1)

    n_steps = len(res['STATES'])
    jd_pressure = np.array([res['STATES'][i]['Pressure'] for i in range(n_steps)])
    jd_sats = np.array([res['STATES'][i]['Saturations'] for i in range(n_steps)])

    jd_pressure = np.vstack([state0_pressure, jd_pressure])
    jd_sats = np.vstack([state0_sats, jd_sats])

    output['saturations'] = dict(zip(sat_names, np.moveaxis(jd_sats, 1, 0)))

    output['pressure'] = jd_pressure

    n_timestamps = len(res["DAYS"])
    start_date = case.input_data["RUNSPEC"]["START"]
    timestamps = [start_date + timedelta(days=res["DAYS"][i]) for i in range(n_timestamps)]
    dates = pd.DataFrame({"DATE": timestamps})

    welldata = {}

    wellnames = res["WELLS"].keys()
    if wellnames:
        welldata = pd.concat([well_states(w,
                                          pd.DataFrame(res["WELLS"][w]),
                                          dates,
                                          start_date) for w in wellnames])
    else:
        wellnames = pd.DataFrame({'WELL': wellnames})

    output['wellnames'] = wellnames
    output['welldata'] = welldata

def simulate(queue, results, timeout=1):
    "Simulation pipeline."
    while True:
        task_id, path = queue.get()
        try:
            jd = importlib.import_module('jutuldarcy')
            case = jd.setup_case_from_data_file(path)
            sim = jd.simulate_reservoir(case)
            pydict = jd.convert_to_pydict(sim, case=case)
            results2field(case, pydict, results)
            results['status'] = None
        except Exception as err:
            results['status'] = str(err)
        results[task_id] = None
