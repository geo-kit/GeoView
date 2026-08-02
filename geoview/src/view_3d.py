"3D view page."
import asyncio
import numpy as np
import pandas as pd
from matplotlib.pyplot import get_cmap
import vtk

from trame.app import asynchronous
from trame.widgets import html, vtklocal, vtk as vtk_widgets, vuetify3 as vuetify

from vtkmodules.vtkRenderingCore import vtkRenderWindow, vtkRenderWindowInteractor
from vtkmodules.vtkCommonCore import vtkLookupTable

from .config import dataset_names, state, ctrl, FIELD, renderer, actor_names
from .custom_classes import CustomInteractorStyle
from .common import set_active_scalars


VTK_VIEW_SETTINGS = {}

state.colormaps = sorted(["cividis", "inferno", "jet",
    "hot", "hsv", "magma", "plasma", "rainbow",
    "Spectral", 'turbo', "twilight", "viridis",
    'YlGn', 'YlGnBu', 'RdGy', 'RdYlBu', 'BuGn',
    "gray", 'Blues', 'Greens', 'Oranges', 'Reds'], key=str.casefold)
state.colormap = 'jet'
state.anim_running = False
state.anim_speed = 0.5

state.exportingData = False

render_window = vtkRenderWindow()
render_window.AddRenderer(renderer)
render_window.ShowWindowOff()

rw_interactor = vtkRenderWindowInteractor()
rw_interactor.SetRenderWindow(render_window)

if state.vtk_remote:
    rw_style = CustomInteractorStyle(renderer, render_window)
else:
    rw_style = vtk.vtkInteractorStyleTrackballCamera()

rw_interactor.SetInteractorStyle(rw_style)

scalarWidget = vtk.vtkScalarBarWidget()
scalarWidget.SetInteractor(rw_interactor)
scalarBar = scalarWidget.GetScalarBarActor()
scalarBar.UnconstrainedFontSizeOn()
scalarBar.GetLabelTextProperty().BoldOff()
scalarBar.GetLabelTextProperty().ItalicOff()
scalarBar.GetTitleTextProperty().BoldOff()
scalarBar.GetTitleTextProperty().ItalicOff()
scalarBar.GetLabelTextProperty().SetFontSize(14)
scalarBar.SetVerticalTitleSeparation(2)
scalarBar.SetBarRatio(scalarBar.GetBarRatio() * 1.5)
scalarBar.SetMaximumWidthInPixels(50)


@state.change("theme")
def change_vtk_bgr(theme, **kwargs):
    "Change background in vtk."
    _ = kwargs
    if theme == 'light':
        renderer.SetBackground(1, 1, 1)
        scalarBar.GetLabelTextProperty().SetColor(0, 0, 0)
        scalarBar.GetTitleTextProperty().SetColor(0, 0, 0)
    else:
        renderer.SetBackground(0, 0, 0)
        scalarBar.GetLabelTextProperty().SetColor(1, 1, 1)
        scalarBar.GetTitleTextProperty().SetColor(1, 1, 1)
    if state.vtk_remote:
        rw_style.ChangeTheme(theme)
    render_window.Render()
    ctrl.view_update()

@state.change("activeField", "modelID")
def update_field(activeField, **kwargs):
    "Update field in vtk."
    _ = kwargs

    if activeField is None:
        return

    set_active_scalars(update_range=True)

    comp, _ = activeField.lower().split('_')
    activeStep = int(state.activeStep) if state.activeStep else 0
    if comp == 'states':
        state.stateDate = FIELD['dates'][activeStep].strftime('%Y-%m-%d')
    else:
        state.need_time_slider = False

    mapper = FIELD[actor_names.main].GetMapper()
    mapper.SetScalarRange(FIELD['grid'].GetScalarRange())
    FIELD[actor_names.main].SetMapper(mapper)
    scalarBar.SetTitle(activeField.split('_')[1])

    update_wells_status(activeStep)

    update_threshold_slices(state.i_slice,
                            state.j_slice,
                            state.k_slice,
                            state.field_slice,
                            state.show_well_blocks)

@state.change("activeStep")
def update_active_step(activeStep, **kwargs):
    "Update timestep in vtk."
    _ = kwargs

    activeField = state.activeField
    if activeField is None:
        return

    activeStep = int(activeStep) if activeStep else 0

    if state.vtk_remote:
        rw_style._AnnotatePick(rw_style.currentId, update=True)

    update_wells_status(activeStep)

    if activeField.split("_")[0].lower() != 'states':
        return

    set_active_scalars(update_range=False)

    state.stateDate = FIELD['dates'][activeStep].strftime('%Y-%m-%d')

    vtk_grid = FIELD['grid']

    mapper = FIELD[actor_names.main].GetMapper()
    mapper.SetScalarRange(vtk_grid.GetScalarRange())
    FIELD[actor_names.main].SetMapper(mapper)

    update_threshold_slices(state.i_slice,
                            state.j_slice,
                            state.k_slice,
                            state.field_slice,
                            state.show_well_blocks)

def update_wells_status(activeStep):
    "Get wells status."
    return

    if dataset_names.wells not in FIELD:
        return

    active_step = int(activeStep)
    named_colors = vtk.vtkNamedColors()
    field = FIELD['model']

    well_colors = vtk.vtkUnsignedCharArray()
    well_colors.SetNumberOfComponents(3)
    
    if 'RESULTS' in field.wells.attributes:
        for well in field.wells:
            for col in ('WOPR', 'WWPR', 'WGPR'):
                if col in well.results.columns and well.results[col].iloc[active_step] > 0:
                    well_colors.InsertNextTypedTuple(named_colors.GetColor3ub("Green"))
                    break
            else:
                if 'WWIR' in well.results.columns and well.results['WWIR'].iloc[active_step] > 0:
                    well_colors.InsertNextTypedTuple(named_colors.GetColor3ub("Blue"))
                    continue
                well_colors.InsertNextTypedTuple(named_colors.GetColor3ub("Red"))
        else:
            well_colors.InsertNextTypedTuple(named_colors.GetColor3ub("Red"))

    FIELD[dataset_names.wells].GetCellData().SetScalars(well_colors)
    render_window.Render()
    ctrl.view_update()

@state.change('stateDate')
def update_date(stateDate, **kwargs):
    "Synchronize date and activeStep."
    _ = kwargs
    if stateDate is None:
        return
    if 'dates' in FIELD:
        stateDate = pd.to_datetime(stateDate)
        if FIELD['dates'][-1] < stateDate:
            i = state.max_timestep
        else:
            i = np.argmax(FIELD['dates'] >= stateDate)
        state.activeStep = int(i)

@state.change("colormap")
def update_cmap(colormap, **kwargs):
    "Update colormap."
    _ = kwargs
    
    mapper = FIELD[actor_names.main].GetMapper()
    if state.showScalars:
        cmap = get_cmap(colormap)
        table = vtkLookupTable()
        colors = cmap(np.arange(0, cmap.N))
        table.SetNumberOfTableValues(len(colors))
        for i, val in enumerate(colors):
            table.SetTableValue(i, val[0], val[1], val[2])
        table.Build()
        mapper.SetLookupTable(table)
        scalarWidget.GetScalarBarActor().SetLookupTable(table)
        scalarWidget.On()
    else:
        mapper.ScalarVisibilityOff()

    render_window.Render()
    ctrl.view_update()

def make_threshold(slices, attr, input_threshold=None, ijk=False):
    "Set threshold filter limits."
    threshold = vtk.vtkThreshold()
    threshold.SetInputData(FIELD['grid'])
    if input_threshold:
        threshold.SetInputConnection(input_threshold.GetOutputPort())
    if ijk:
        slices = [int(slices[0]), int(slices[1])]
        if slices[0] == slices[1]:
            threshold.SetUpperThreshold(slices[1]-0.5)
            threshold.SetLowerThreshold(slices[0]-1)
        else:
            threshold.SetUpperThreshold(slices[1]-1)
            threshold.SetLowerThreshold(slices[0]-1)
    else:
        slices = [float(slices[0]), float(slices[1])]
        threshold.SetUpperThreshold(slices[1])
        threshold.SetLowerThreshold(slices[0])
    threshold.SetInputArrayToProcess(0, 0, 0, 1, attr)
    return threshold

@state.change("i_slice_0", "i_slice_1")
def update_i_slice(i_slice_0, i_slice_1, **kwargs):
    "Update slice ranges."
    _ = kwargs
    if (not i_slice_0) or (not i_slice_1):
        return
    state.i_slice = [i_slice_0, i_slice_1]

@state.change("j_slice_0", "j_slice_1")
def update_j_slice(j_slice_0, j_slice_1, **kwargs):
    "Update slice ranges."
    _ = kwargs
    if (not j_slice_0) or (not j_slice_1):
        return
    state.j_slice = [j_slice_0, j_slice_1]

@state.change("k_slice_0", "k_slice_1")
def update_k_slice(k_slice_0, k_slice_1, **kwargs):
    "Update slice ranges."
    _ = kwargs
    if (not k_slice_0) or (not k_slice_1):
        return
    state.k_slice = [k_slice_0, k_slice_1]

@state.change("field_slice_0", "field_slice_1")
def update_field_slice(field_slice_0, field_slice_1, **kwargs):
    "Update slice ranges."
    _ = kwargs
    if (not field_slice_0) or (not field_slice_1):
        return
    state.field_slice = [field_slice_0, field_slice_1]

@state.change("i_slice", "j_slice", "k_slice", "field_slice", "show_well_blocks")
def update_threshold_slices(i_slice, j_slice, k_slice, field_slice, show_well_blocks, **kwargs):
    "Filter scalars based on index and values."
    _ = kwargs

    state.i_slice_0, state.i_slice_1 = state.i_slice
    state.j_slice_0, state.j_slice_1 = state.j_slice
    state.k_slice_0, state.k_slice_1 = state.k_slice
    state.field_slice_0, state.field_slice_1 = state.field_slice

    threshold_i = make_threshold(i_slice, "I", ijk=True)
    threshold_j = make_threshold(j_slice, "J", input_threshold=threshold_i, ijk=True)
    threshold_k = make_threshold(k_slice, "K", input_threshold=threshold_j, ijk=True)
    threshold_r = make_threshold([0.5, 1.5] if show_well_blocks else [-0.5, 1.5],
                                 "WELL_BLOCKS", 
                                 input_threshold=threshold_k)
    threshold_field = make_threshold(field_slice, 
                                     'ActiveScalars',
                                     input_threshold=threshold_r)
    
    gf = vtk.vtkGeometryFilter()
    threshold_field.Update()
    gf.SetInputData(threshold_field.GetOutput())

    mapper = vtk.vtkDataSetMapper()
    mapper.SetInputConnection(gf.GetOutputPort())
    mapper.SetScalarRange(FIELD['grid'].GetScalarRange())
    FIELD[actor_names.main].SetMapper(mapper)
    update_cmap(state.colormap)

@state.change("opacity")
def update_opacity(opacity, **kwargs):
    "Update opacity."
    _ = kwargs
    if opacity is None:
        return
    FIELD[actor_names.main].GetProperty().SetOpacity(opacity)
    render_window.Render()
    ctrl.view_update()

@state.change("showScalars")
def change_field_visibility(showScalars, **kwargs):
    "Set visibility of scalars."
    _ = kwargs
    if showScalars is None:
        return
    if showScalars:
        FIELD[actor_names.main].GetProperty().SetRepresentationToSurface()
        FIELD[actor_names.main].SetVisibility(True)
        FIELD[actor_names.main].GetMapper().ScalarVisibilityOn()
        scalarBar.SetVisibility(True)
    else:
        if state.showWireframe:
            FIELD[actor_names.main].GetProperty().SetRepresentationToWireframe()
            FIELD[actor_names.main].GetMapper().ScalarVisibilityOff()
            scalarBar.SetVisibility(False)
        else:
            FIELD[actor_names.main].SetVisibility(False)
            scalarBar.SetVisibility(False)
    render_window.Render()
    ctrl.view_update()

@state.change("showWireframe")
def change_wireframe_visibility(showWireframe, **kwargs):
    "Set visibility of wireframe."
    _ = kwargs
    if showWireframe is None:
        return
    if state.showScalars:
        return
    if showWireframe:
        FIELD[actor_names.main].GetProperty().SetRepresentationToWireframe()
        FIELD[actor_names.main].GetMapper().ScalarVisibilityOff()
        FIELD[actor_names.main].SetVisibility(True)
    else:
        FIELD[actor_names.main].SetVisibility(False)
    render_window.Render()
    ctrl.view_update()

@state.change("showWells")
def change_wells_visibility(showWells, **kwargs):
    "Set visibility of wells."
    _ = kwargs
    for name in (actor_names.wells, actor_names.well_links, actor_names.well_labels):
        if name in FIELD:
            FIELD[name].SetVisibility(showWells)
    render_window.Render()
    ctrl.view_update()

@state.change("showFaults")
def change_faults_visibility(showFaults, **kwargs):
    "Set visibility of faults."
    _ = kwargs
    for name in [actor_names.faults, actor_names.fault_links, actor_names.fault_labels]:
        if name in FIELD:
            FIELD[name].SetVisibility(showFaults)
    render_window.Render()
    ctrl.view_update()

def default_view():
    "Reset 3d view setting to initial state."
    state.i_slice = [1, state.dimens[0]]
    state.j_slice = [1, state.dimens[1]]
    state.k_slice = [1, state.dimens[2]]
    state.field_slice = [state.field_slice_min, state.field_slice_max]
    state.opacity = 1
    state.showScalars = True
    state.showWireframe = True
    state.showWells = True
    state.showFaults = True
    state.activeStep = 0
    state.show_well_blocks = False
    ctrl.view_reset_camera()

ctrl.default_view = default_view

@asynchronous.task
async def start_animation():
    "Start animation."
    if state.anim_running:
        with state:
            state.anim_running = False
        return
    with state:
        state.anim_running = True
    max_step = int(state.max_timestep) if state.max_timestep else 0
    start = int(state.activeStep) if state.activeStep is not None else 0
    for step in range(start, max_step + 1):
        if not state.anim_running:
            break
        with state:
            state.activeStep = step
        render_window.Render()
        ctrl.view_update()
        await asyncio.sleep(state.anim_speed)
    with state:
        state.anim_running = False

ctrl.startAnimation = start_animation

def change_speed():
    "Change animation speed."
    if state.anim_speed == 0.1:
        state.anim_speed = 1
    elif state.anim_speed == 0.5:
        state.anim_speed = 0.1
    elif state.anim_speed == 1:
        state.anim_speed = 0.5

ctrl.changeSpeed = change_speed


def render_3d():
    "3D view layout."
    with vuetify.VContainer(fluid=True, style='align-items: start', classes="fill-height pa-0 ma-0"):
        with vuetify.VRow(style="height: 100%; width: 100%", classes='pa-0 ma-0'):
            with vuetify.VCol(classes="pa-0"):
                if state.vtk_remote:
                    view = vtk_widgets.VtkRemoteView(
                                render_window,
                                **VTK_VIEW_SETTINGS
                            )
                else:
                    view = vtklocal.LocalView(
                                render_window,
                                **VTK_VIEW_SETTINGS
                            )

                ctrl.view_update.add(view.update)
                ctrl.view_reset_camera.add(view.reset_camera)

    with html.Div(style='position: fixed; width: 80%; bottom: 0; left: 10%;'):
        with vuetify.VTextField(
              v_model=("stateDate",),
              label="Select a date",
              hide_details=True,
              density='compact',
              type="date"):
            with vuetify.Template(v_slot_append=True,
                properties=[("v_slot_append", "v-slot:append")],):
                with vuetify.VSlider(
                    min=0,
                    max=("max_timestep",),
                    step=1,
                    v_model=('activeStep',),
                    label="Timestep",
                    hide_details=True,
                    style='width: 50vw'
                    ):
                    with vuetify.Template(v_slot_append=True,
                        properties=[("v_slot_append", "v-slot:append")],):
                        vuetify.VNumberInput(
                            v_model="activeStep",
                            density="compact",
                            style="width: 100px",
                            control_variant="stacked",
                            min=0,
                            max=("max_timestep",),
                            variant="outlined",
                            bg_color=('bgColor',),
                            hide_details=True)
                with vuetify.VBtn(icon=True,
                                  flat=True,
                                  click=ctrl.startAnimation):
                    vuetify.VIcon(children=["{{ anim_running ? 'mdi-stop' : 'mdi-play' }}"])
                    vuetify.VTooltip(text='Start animation',
                                     activator="parent",
                                     location="top")
                with vuetify.VBtn(icon=True,
                                  flat=True,
                                  click=ctrl.changeSpeed):
                    vuetify.VIcon(
                        children=["{{anim_speed == 0.5 ? 'mdi-speedometer-medium': anim_speed == 1 ? 'mdi-speedometer-slow' : 'mdi-speedometer'}}"]
                    )
                    vuetify.VTooltip(text='Change animation speed',
                                     activator="parent",
                                     location="top")

    with vuetify.VCard(
        color=('sideBarColor',),
        flat=True,
        style='position: fixed; left: 0; top: calc(50% + 48px); transform: translateY(calc(0px - 50% - 24px));'):
        with vuetify.VContainer(fluid=True,
            style='align-items: start; justify-content: left;',
            classes='pa-0 ma-0'):
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;"):
                        vuetify.VTooltip(
                            text='Select field to show',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-database-export-outline")
                        with vuetify.VMenu(activator="parent",
                            location="right",
                            close_on_content_click=False):
                            with vuetify.VCard(classes="overflow-auto", max_height="50vh"):
                                with vuetify.VList():
                                    with vuetify.VListItem(
                                        v_for="item, index in field_attrs",
                                        active=("item === activeField",),
                                        click="activeField = item"):
                                        vuetify.VListItemTitle("{{item}}")
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;"):
                        vuetify.VTooltip(
                            text='Change colormap',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-format-color-fill")
                        with vuetify.VMenu(activator="parent",
                            location="right",
                            close_on_content_click=False):
                            with vuetify.VCard(classes="overflow-auto", max_height="50vh"):
                                with vuetify.VList():
                                    with vuetify.VListItem(
                                        v_for="(item, index) in colormaps",
                                        click="colormap = item",
                                        active=("item === colormap",)
                                        ):
                                        vuetify.VListItemTitle("{{item}}")
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;"):
                        vuetify.VTooltip(
                            text='Set opacity',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-circle-opacity")
                        with vuetify.VMenu(activator="parent",
                            location="right",
                            close_on_content_click=False):
                            with html.Div(style='width: 15vw'):
                                vuetify.VSlider(
                                    min=0,
                                    max=1,
                                    step=0.1,
                                    v_model=('opacity', 1),
                                    thumb_label='true',
                                    hide_details=True)
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;"):
                        vuetify.VTooltip(
                            text='Filter cells',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-filter")
                        with vuetify.VMenu(activator="parent",
                            location="right center",
                            close_on_content_click=False):
                            with vuetify.VContainer(style='width: 25vw'):
                                with vuetify.VRow():
                                    with vuetify.VCard(style='width: 7vw; white-space: nowrap', variant='flat'):
                                        vuetify.VCardText('Field')
                                    vuetify.VRangeSlider(
                                        min=("field_slice_min",),
                                        max=("field_slice_max",),
                                        step=("field_slice_step",),
                                        v_model=("field_slice",),
                                        thumb_label='true',
                                        hide_details=True)
                                with vuetify.VRow():
                                    with vuetify.VCard(style='width: 7vw; white-space: nowrap', variant='flat'):
                                        vuetify.VCardText('I slice')
                                    vuetify.VRangeSlider(
                                        min=1,
                                        max=("dimens[0]",),
                                        step=1,
                                        v_model=("i_slice",),
                                        thumb_label='true',
                                        hide_details=True)
                                with vuetify.VRow():
                                    with vuetify.VCard(style='width: 7vw; white-space: nowrap', variant='flat'):
                                        vuetify.VCardText('J slice')
                                    vuetify.VRangeSlider(
                                        min=1,
                                        max=("dimens[1]",),
                                        step=1,
                                        v_model=("j_slice",),
                                        thumb_label='true',
                                        hide_details=True)
                                with vuetify.VRow():
                                    with vuetify.VCard(style='width: 7vw; white-space: nowrap', variant='flat'):
                                        vuetify.VCardText('K slice')
                                    vuetify.VRangeSlider(
                                        min=1,
                                        max=("dimens[2]",),
                                        step=1,
                                        v_model=("k_slice",),
                                        thumb_label='hide',
                                        hide_details=True)
                                vuetify.VCheckbox(label='Show only well blokcs',
                                    v_model=('show_well_blocks', False),
                                    hide_details=True,
                                    density='compact')
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;"):
                        vuetify.VTooltip(
                            text='Change visibility of the objects',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-layers-outline")
                        with vuetify.VMenu(activator="parent",
                            location="right",
                            close_on_content_click=False):
                            with vuetify.VCard(classes="pr-2"):
                                vuetify.VCheckbox(label='Scalars',
                                    v_model=('showScalars', True),
                                    hide_details=True,
                                    density='compact')
                                vuetify.VCheckbox(label='Wireframe',
                                    v_model=('showWireframe', True),
                                    hide_details=True,
                                    density='compact')
                                vuetify.VCheckbox(label='Wells',
                                    v_model=('showWells', True),
                                    hide_details=True,
                                    density='compact')
                                vuetify.VCheckbox(label='Faults',
                                    v_model=('showFaults', True),
                                    hide_details=True,
                                    density='compact')
            with vuetify.VRow(classes='pa-0 ma-0'):
                with vuetify.VCol(classes='pa-0 ma-0'):
                    with vuetify.VBtn(icon=True,flat=True,
                        style="background-color:transparent;\
                               backface-visibility:visible;",
                        click=ctrl.default_view):
                        vuetify.VTooltip(
                            text='Reset view settings to default values',
                            activator="parent",
                            location="end")
                        vuetify.VIcon("mdi-fit-to-page-outline")
