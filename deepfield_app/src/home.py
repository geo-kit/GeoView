"Home page."
import os
from glob import glob
from uuid import uuid4
import asyncio
import vtk

from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkDataSetMapper,
)

from trame.widgets import html, vuetify3 as vuetify
from trame.app import asynchronous

from geocode import Field

from .config import state, ctrl, FIELD, renderer, actor_names, jserver
from .common import reset_camera
from .view_3d import render_window
from .processing import (process_grid, prepare_slices, get_field_attributes,
                         get_field_meta, compute_initial_content, compute_total_rates,
                         get_simulation_dates, add_scalars, add_wells, add_faults)


USER_DIR = os.path.expanduser("~")

state.user_request = USER_DIR
state.user_click_request = None
state.dirList = []
state.pathIndex = None
state.updateDirList = True
state.initialDirState = True
state.showDirList = False
state.recentFiles = []
state.loading = False
state.simulating = False
state.showHistory = False
state.emptyHistory = True
state.errMessage = ''
state.loadFailed = False
state.loadedModelPath = None
state.simulationFailed = False
state.modelID = 0

state.field_attrs = []
state.activeField = None
state.wellnames = []
state.dimens = [0, 0, 0]
state.max_timestep = 0
state.stateDate = None
state.startDate = None
state.lastDate = None
state.data1d = []
state.tables = []
state.i_cells = []
state.j_cells = []
state.k_cells = []
state.i_slice = [0, 0]
state.i_slice_0 = state.i_slice_1 = 0
state.j_slice = [0, 0]
state.j_slice_0 = state.j_slice_1 = 0
state.k_slice = [0, 0]
state.k_slice_0 = state.k_slice_1 = 0
state.field_slice = [0, 0]
state.field_slice_0 = state.field_slice_1 = 0
state.field_slice_min = 0
state.field_slice_max = 0
state.n_field_steps = 100
state.field_slice_step = 0
state.show_well_blocks = False
state.total_cells = 0
state.active_cells = 0
state.units = 0
state.pore_volume = 0
state.num_wells = 0
state.fluids = []
state.total_oil_production = 0
state.total_wat_production = 0
state.total_gas_production = 0
state.components_attrs = {
    'grid': [],
    'rock': [],
    'states': [],
    'tables': [],
    'wells': [],
    'faults': [],
    'aquifers': [],
    }
state.units1 = ''
state.units2 = ''
state.units3 = ''
state.units4 = ''
state.units5 = ''

state.pore_vol = 0
state.oil_vol = 0
state.wat_vol = 0
state.gas_vol = 0

def filter_path(path):
    "True if path is a directory or has .data or .hdf5 extension."
    if os.path.isdir(path):
        return True
    _, ext = os.path.splitext(path)
    return ext.lower() in ['.data', '.hdf5']

@state.change("user_click_request")
def handle_user_click_request(user_click_request, **kwargs):
    "Handle user click."
    if user_click_request is None:
        return
    state.updateDirList = True
    _, ext = os.path.splitext(user_click_request)
    if ext.lower() in ['.data', '.hdf5']:
        state.user_request = user_click_request
        return
    if os.path.isdir(user_click_request):
        user_click_request += os.sep
    state.user_request = user_click_request
    state.pathIndex = None

@state.change("user_request")
def get_path_variants(user_request, **kwargs):
    "Collect and filter paths."
    _ = kwargs
    if state.loading or state.simulating:
        return
    state.showHistory = False
    if user_request is not None:
        _, ext = os.path.splitext(user_request)
        arrived = ext.lower() == '.data'
    else:
        arrived = False
    state.showDirList = (not state.initialDirState) & (not arrived)
    paths = list(glob(user_request + "*")) if user_request is not None else []
    if state.updateDirList:
        state.dirList = [p for p in paths if filter_path(p)]

@asynchronous.task
async def load_file_async():
    "Load file async."
    with state:
        state.loading = True
        state.showHistory = False
        state.showDirList = False
        state.simulationFailed = False

    field = Field(state.user_request)

    try:
        await asyncio.to_thread(field.load)
    except Exception as err:
        with state:
            state.errMessage = str(err)
            state.loadFailed = True
            state.loadedModelPath = None
            state.loading = False
        return

    FIELD['model'] = field
    FIELD["model_copy"] = None

    with state:
        try:
            process_field(field)
        except Exception as err:
            state.errMessage = str(err)
            state.loadFailed = True
            state.loadedModelPath = None
            state.loading = False
            return

        if state.user_request not in state.recentFiles:
            state.recentFiles = state.recentFiles + [state.user_request]
            state.emptyHistory = False
        state.loading = False
        state.errMessage = ''
        state.loadFailed = False
        state.modelID += 1
        state.loadedModelPath = state.user_request

ctrl.load_file_async = load_file_async

def process_field(field):
    "Prepare field data for visualization."
    for name in actor_names.__dict__.values():
        if name in FIELD:
            renderer.RemoveActor(FIELD[name])

    render_window.Render()
    reset_camera()
    ctrl.view_update()

    process_grid(field)
    prepare_slices()
    get_field_attributes(field)
    get_field_meta(field)

    compute_initial_content(field)
    compute_total_rates(field)
    get_simulation_dates(field)

    add_scalars()
    add_wells(field)
    add_faults(field)

    render_window.Render()
    reset_camera()
    ctrl.view_update()
    ctrl.default_view()

def update_dynamics(field):
    "Update dynamic data."
    get_field_attributes(field)
    compute_initial_content(field)
    compute_total_rates(field)
    get_simulation_dates(field)

def make_empty_grid():
    "Init variables."
    grid = vtk.vtkUnstructuredGrid()

    mapper = vtkDataSetMapper()
    mapper.SetInputData(grid)
    mapper.SetScalarRange(0, 1)

    actor = vtkActor()
    actor.SetMapper(mapper)

    renderer.AddActor(actor)
    renderer.ResetCamera()

    FIELD[actor_names.main] = actor
    FIELD['grid'] = grid

def on_keydown(key_code):
    "Autocomplete path input."
    state.initialDirState = False
    state.showDirList = True
    if key_code == 'ArrowDown':
        if state.pathIndex is None:
            state.pathIndex = 0
        else:
            state.pathIndex = (state.pathIndex + 1) % len(state.dirList)
        state.updateDirList = False
        state.user_request = state.dirList[state.pathIndex]
        return
    if key_code == 'ArrowUp':
        if state.pathIndex is None:
            state.pathIndex = -1
        else:
            state.pathIndex = (state.pathIndex - 1) % len(state.dirList)
        state.updateDirList = False
        state.user_request = state.dirList[state.pathIndex]
        return
    if key_code == "Enter":
        state.updateDirList = True
        _, ext = os.path.splitext(state.user_request)
        if ext.lower() in ['.data', '.hdf5']:
            ctrl.load_file_async()
            return
        if state.pathIndex is None:
            state.pathIndex = 0
        if state.pathIndex < len(state.dirList):
            path = state.dirList[state.pathIndex]
            if os.path.isdir(path):
                path += os.sep
            state.user_request = path
            state.pathIndex = None
        return
    state.updateDirList = True

async def submit_sumulation_task(queue, results, path):
    "Submit simulation task."
    task_id = str(uuid4())

    queue.put((task_id, path))

    while task_id not in results:
        await asyncio.sleep(1)


@asynchronous.task
async def simulate_async():
    "Simulate async."
    with state:
        state.simulating = True

    try:
        if state.loadedModelPath is None:
            raise ValueError('Model is not loaded.')

        await submit_sumulation_task(jserver['queue'],
                                     jserver['results'],
                                     state.loadedModelPath)
    
        results = jserver['results']

        if results['status'] is not None:
            raise ValueError(results['status'])

        field = FIELD['model']

        for k in field.states.attributes:
            delattr(field.states, k)

        field.states['PRESSURE'] = results['pressure']
        for k, v in results['saturations'].items():
            field.states[k] = v
        field.states.to_spatial()
        
        field.wells.update(results['welldata'])

        field.states.dates = field.result_dates

        update_dynamics(field)

    except Exception as err:
        with state:
            state.errMessage = str(err)
            state.simulationFailed = True
            state.simulating = False
        return

    with state:
        state.modelID += 1
        state.simulating = False
        state.simulationFailed = False
        state.errMessage = ''

ctrl.simulate_async = simulate_async

def render_home():
    "Home page layout."
    text_style = "font-size: 16px;"

    with html.Div(
        style='position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 80vw; height: 10vh;'
    ):
        with vuetify.VContainer():
            with vuetify.VRow():
                with vuetify.VCol():
                    with vuetify.VTextField(
                        ref="searchInput",
                        v_model=("user_request",),
                        label="Input reservoir model path",
                        clearable=True,
                        name="searchInput",
                        autofocus=True,
                        keydown=(on_keydown, "[$event.code]"),
                        __events=["keydown"]
                    ):
                        with vuetify.Template(
                            v_slot_append=True,
                            properties=[("v_slot_append", "v-slot:append")]
                        ):
                            with vuetify.VBtn(
                                'Load',
                                click=ctrl.load_file_async,
                                disabled=("loading | simulating",)
                            ):
                                vuetify.VTooltip(
                                    text='Start reading data',
                                    activator="parent",
                                    location="top"
                                )
                            with vuetify.VBtn(
                                'Simulate',
                                color=("(loading | simulating | (modelID == 0)) ? '' : '#51b03c'",),
                                click=ctrl.simulate_async,
                                disabled=("loading | loadFailed | simulating | (modelID == 0)",)
                            ):
                                vuetify.VTooltip(
                                    text='Start model simulation',
                                    activator="parent",
                                    location="top"
                                )
                        with vuetify.Template(
                            v_slot_prepend=True,
                            properties=[("v_slot_prepend", "v-slot:prepend")]
                        ):
                            with vuetify.VBtn(
                                icon=True,
                                click='showHistory = !showHistory',
                                flat=True,
                                active=('showHistory',),
                                style="background-color:transparent; backface-visibility:visible;"
                            ):
                                vuetify.VIcon("mdi-history")
                                vuetify.VTooltip(
                                    text='Show recent files',
                                    activator="parent",
                                    location="top"
                                )
                        with vuetify.Template(
                            v_slot_loader=True,
                            properties=[("v_slot_loader", "v-slot:loader")]
                        ):
                            with vuetify.VCard(
                                v_if='!loading & !simulating',
                                classes="overflow-auto",
                                max_width="100%",
                                max_height="30vh"
                            ):
                                with vuetify.VList(v_if='showDirList'):
                                    with vuetify.VListItem(
                                        v_for="item, index in dirList",
                                        click="user_click_request = item"
                                    ):
                                        vuetify.VListItemTitle("{{item}}")
                                with vuetify.VList(v_if='showHistory'):
                                    with vuetify.VListItem(
                                        v_for="item, index in recentFiles",
                                        click="user_click_request = item"
                                    ):
                                        vuetify.VListItemTitle("{{item}}")
            with vuetify.VRow(classes="pa-0 ma-0"):
                with vuetify.VCol(classes="pa-0 ma-0 text-center"):
                    vuetify.VProgressCircular(
                        v_if='loading | simulating',
                        color="primary",
                        indeterminate=True,
                        size="60",
                        width="7"
                    )
                    with vuetify.VCard(v_if='loading', variant='text'):
                        vuetify.VCardText('Loading data, please wait', style=text_style)
                    with vuetify.VCard(v_if='simulating', variant='text'):
                        vuetify.VCardText('Simulating model, please wait', style=text_style)
                    with vuetify.VCard(
                        v_if='!showDirList & !showHistory & !loading & !simulating & !loadFailed & !simulationFailed & (modelID > 0)',
                        variant='text'
                    ):
                        vuetify.VIcon('mdi-check-bold', color='#51b03c', size='large')
                        vuetify.VCardText('Completed', style=text_style)
                    with vuetify.VCard(
                        v_if='!showDirList & !showHistory & !loading & !simulating & (loadFailed | simulationFailed)',
                        variant='text'
                    ):
                        vuetify.VIcon('mdi-close-thick', color="error", size='large')
                        vuetify.VCardText('Failed: ' + '{{errMessage}}', style=text_style)
                    with vuetify.VCard(
                        v_if='showHistory & emptyHistory',
                        variant='text'
                    ):
                        vuetify.VCardText('History is empty.', style=text_style)
