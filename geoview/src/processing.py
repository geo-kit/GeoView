"""Field processing utils."""
import numpy as np
import pandas as pd
from anytree import PreOrderIter
import vtk
from vtk.util.numpy_support import numpy_to_vtk # pylint: disable=no-name-in-module, import-error

from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkDataSetMapper,
)

from .config import state, renderer, FIELD, dataset_names, actor_names
from .common import set_active_scalars

def process_grid(field):
    "Prepare field grid data for visualization."
    vtk_grid = field.grid.vtk_grid

    dimens = field.grid.dimens.values.ravel()
    ind_i, ind_j, ind_k = np.unravel_index(field.grid.actnum_ids, dimens)
    for name, val in zip(('I', 'J', 'K'), (ind_i, ind_j, ind_k)):
        array = numpy_to_vtk(val)
        array.SetName(name)
        vtk_grid.GetCellData().AddArray(array)

    well_dist = get_well_blocks(field)
    array = numpy_to_vtk(well_dist.ravel()[field.grid.actnum_ids])
    array.SetName('WELL_BLOCKS')
    vtk_grid.GetCellData().AddArray(array)

    FIELD['grid'] = vtk_grid

    state.dimens = [int(x) for x in dimens]
    state.total_cells = int(np.prod(dimens))
    state.active_cells = len(field.grid.actnum_ids)

    bbox = field.grid.bounding_box
    ds = abs(bbox[3:] - bbox[:3])
    ds_max = ds.max()
    scales = ds_max / ds
    FIELD['scales'] = scales


def get_field_attributes(field):
    "Collect attributes in field components."
    state.components_attrs = {}
    for name, comp in field.items():
        state.components_attrs[name] = list(comp.attributes)

    rock_attrs = ['ROCK_'+attr.upper() for attr in field.rock.attributes]
    state_attrs = ['STATES_'+attr.upper() for attr in field.states.attributes]

    state.field_attrs = rock_attrs + state_attrs
    state.activeField = ('ROCK_PERMZ' if 'ROCK_PERMZ' in state.field_attrs
        else state.field_attrs[0])

    attrs = []
    if 'RESULTS' in field.wells.attributes:
        attrs = sorted([k for k in field.wells.RESULTS.columns if k not in ['DATE', 'WELL']])
    state.wellsAttrs = attrs
    state.num_wells = len(field.wells.names)

    attrs = list(field.states.attributes)
    state.statesAttrs = attrs

    attrs = field.tables.attributes
    state.tables = [t for t in attrs if getattr(field.tables, t)[0].domain]

    state.data1d = state.statesAttrs + state.wellsAttrs

def get_field_meta(field):
    "Get meta info from field."
    state.fluids = []
    for fluid in ['WATER', 'OIL', 'GAS', 'DISGAS', 'VAPOIL', 'SOLID']:
        if (fluid, None) in field._data['RUNSPEC']:
            state.fluids.append(fluid)

def compute_initial_content(field):
    "Compute initial phase volumes."
    actnum = field.grid.actnum

    soil = field.states.SOIL[0][actnum] if 'SOIL' in field.states else 0
    swat = field.states.SWAT[0][actnum] if 'SWAT' in field.states else 0
    sgas = field.states.SGAS[0][actnum] if 'SGAS' in field.states else 0

    c_vols = field.grid.cell_volumes

    p_vols = field.rock.poro[actnum] * c_vols

    state.pore_vol = np.round(p_vols.sum(), 2)
    state.oil_vol = np.round((p_vols * soil).sum(), 2)
    state.wat_vol = np.round((p_vols * swat).sum(), 2)
    state.gas_vol = np.round((p_vols * sgas).sum(), 2)

def compute_total_rates(field):
    "Compute total production rates."
    if 'RESULTS' not in field.wells:
        return

    results = field.wells.RESULTS
    state.total_oil_production = np.round(results['WOPR'].sum(), 2) if 'WOPR' in results else 0
    state.total_wat_production = np.round(results['WWPR'].sum(), 2) if 'WWPR' in results else 0
    state.total_gas_production = np.round(results['WGPR'].sum(), 2) if 'WGPR' in results else 0

def get_simulation_dates(field):
    "Get simulation dates."
    if 'RESULTS' not in field.wells.attributes:
        FIELD['dates'] = np.array([x[1] for x in field._data['RUNSPEC'] if x[0] == 'START'])
    else:
        FIELD['dates'] = np.array(sorted(field.wells.RESULTS.DATE.unique()))

    state.stateDate = FIELD['dates'][0].strftime('%Y-%m-%d')
    state.lastDate = FIELD['dates'][-1].strftime('%Y-%m-%d')

    state.max_timestep = len(FIELD['dates']) - 1

def prepare_slices():
    "Get slice data and slice ranges."
    state.i_slice_0, state.i_slice_1 = 1, state.dimens[0]
    state.i_slice = [state.i_slice_0, state.i_slice_1]

    state.j_slice_0, state.j_slice_1 = 1, state.dimens[1]
    state.j_slice = [state.j_slice_0, state.j_slice_1]

    state.k_slice_0, state.k_slice_1 = 1, state.dimens[2]
    state.k_slice = [state.k_slice_0, state.k_slice_1]

    state.i_cells = ['Average'] + list(range(1, state.dimens[0]+1))
    state.j_cells = ['Average'] + list(range(1, state.dimens[1]+1))
    state.k_cells = ['Average'] + list(range(1, state.dimens[2]+1))

    state.xslice = 1
    state.yslice = 1
    state.zslice = 1

    state.i_cells = ['Average'] + list(range(1, state.dimens[0]+1))
    state.j_cells = ['Average'] + list(range(1, state.dimens[1]+1))
    state.k_cells = ['Average'] + list(range(1, state.dimens[2]+1))

def add_scalars():
    "Add actor for scalars."
    actor = vtkActor()
    actor.SetScale(*FIELD['scales'])

    set_active_scalars(update_range=True)

    vtk_grid = FIELD['grid']

    gf = vtk.vtkGeometryFilter()
    gf.SetInputData(vtk_grid)
    gf.Update()
    outer = gf.GetOutput()

    mapper = vtkDataSetMapper()
    mapper.SetInputData(outer)
    mapper.SetScalarRange(vtk_grid.GetScalarRange())
    actor.SetMapper(mapper)

    renderer.AddActor(actor)
    FIELD[actor_names.main] = actor

def get_well_blocks(field):
    "Get mask for well blocks."
    mask = np.full(field.grid.dimens.values.ravel(), 0)
    field.wells.get_blocks()
    for well in field.wells:
        mask[*well.blocks.T] = 1
    return mask

def add_wells(field):
    "Add actor for wells."
    namedColors = vtk.vtkNamedColors()
    points = vtk.vtkPoints()
    cells = vtk.vtkCellArray()

    points_links = vtk.vtkPoints()
    cells_links = vtk.vtkCellArray()

    grid = field.grid
    z_min = grid.bounding_box[2]
    dz = grid.bounding_box[-1] - z_min
    z_min = z_min - 0.1*dz

    n_wells = len(field.wells.names)
    labeled_points = vtk.vtkPoints()
    labels = vtk.vtkStringArray()
    labels.SetNumberOfValues(n_wells)
    labels.SetName("labels")

    well_colors = vtk.vtkUnsignedCharArray()
    well_colors.SetNumberOfComponents(3)

    colors = vtk.vtkNamedColors()

    for i, well in enumerate(field.wells):
        labels.SetValue(i, well.name)

        welltrack = well.welltrack[['X', 'Y', 'Z']].values

        first_point = welltrack[0, :3].copy()
        first_point[-1] = z_min

        labeled_points.InsertNextPoint(first_point*FIELD['scales'])

        point_ids = []
        for row in welltrack:
            point_ids.append(points.InsertNextPoint(row[:3]))

        polyLine = vtk.vtkPolyLine()
        polyLine.GetPointIds().SetNumberOfIds(len(point_ids))
        for j, id in enumerate(point_ids):
            polyLine.GetPointIds().SetId(j, id)
        cells.InsertNextCell(polyLine)
        well_colors.InsertNextTypedTuple(namedColors.GetColor3ub("Red"))

        point_ids = []
        for row in [first_point, welltrack[0, :3]]:
            point_ids.append(points_links.InsertNextPoint(row))

        polyLine = vtk.vtkPolyLine()
        polyLine.GetPointIds().SetNumberOfIds(len(point_ids))
        for j, id in enumerate(point_ids):
            polyLine.GetPointIds().SetId(j, id)
        cells_links.InsertNextCell(polyLine)

    label_polyData = vtk.vtkPolyData()
    label_polyData.SetPoints(labeled_points)
    label_polyData.GetPointData().AddArray(labels)
    label_mapper = vtk.vtkLabeledDataMapper()
    label_mapper.SetInputData(label_polyData)
    label_mapper.SetFieldDataName('labels')
    label_mapper.SetLabelModeToLabelFieldData()
    label_actor = vtk.vtkActor2D()
    label_actor.SetMapper(label_mapper)

    renderer.AddActor(label_actor)
    FIELD[actor_names.well_labels] = label_actor

    FIELD[dataset_names.wells] = vtk.vtkPolyData()
    FIELD[dataset_names.wells].SetPoints(points)
    FIELD[dataset_names.wells].SetLines(cells)
    FIELD[dataset_names.wells].GetCellData().SetScalars(well_colors)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(FIELD[dataset_names.wells])
    wells_actor = vtk.vtkActor()
    wells_actor.SetScale(*FIELD['scales'])
    wells_actor.SetMapper(mapper)
    wells_actor.GetProperty().SetLineWidth(3)

    renderer.AddActor(wells_actor)
    FIELD[actor_names.wells] = wells_actor

    well_links_poly = vtk.vtkPolyData()
    well_links_poly.SetPoints(points_links)
    well_links_poly.SetLines(cells_links)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(well_links_poly)
    well_links_actor = vtk.vtkActor()
    well_links_actor.SetScale(*FIELD['scales'])
    well_links_actor.SetMapper(mapper)
    well_links_actor.GetProperty().SetLineWidth(2)
    well_links_actor.GetProperty().SetColor(colors.GetColor3d('Green'))

    renderer.AddActor(well_links_actor)
    FIELD[actor_names.well_links] = well_links_actor


def add_faults(field):
    "Add actor for faults."
    field.faults.get_blocks()
    n_segments = len(field.faults.names)

    labels = vtk.vtkStringArray()
    labels.SetNumberOfValues(n_segments)
    labels.SetName("labels")

    grid = field.grid
    z_min = grid.bounding_box[2]
    dz = grid.bounding_box[-1] - z_min
    z_min = z_min - 0.05*dz

    points = vtk.vtkPoints()
    polygons = vtk.vtkCellArray()

    labeled_points = vtk.vtkPoints()
    links_points = vtk.vtkPoints()
    links_points_ids = []
    link_cells = vtk.vtkCellArray()

    size = 0
    for _, fault in enumerate(field.faults):
        blocks = fault.blocks
        xyz = fault.faces_verts
        active = field.grid.actnum[blocks[:, 0], blocks[:, 1], blocks[:, 2]]
        xyz = xyz[active].reshape(-1, 3)
        if len(xyz) == 0:
            continue

        for p in xyz:
            points.InsertNextPoint(*p)

        labeled_points_id = labeled_points.InsertNextPoint(np.array([*xyz[0, :2], z_min])*FIELD['scales'])
        labels.SetValue(labeled_points_id, fault.name)
        links_points_ids.append(links_points.InsertNextPoint(np.array([*xyz[0, :2], z_min])))
        links_points_ids.append(links_points.InsertNextPoint(*xyz[0]))

        ids = np.arange(size, size+len(xyz))
        faces1 = np.stack([ids[::4], ids[1::4], ids[3::4]]).T
        faces2 = np.stack([ids[::4], ids[2::4], ids[3::4]]).T
        faces = np.vstack([faces1, faces2])

        for f in faces:
            polygon = vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(3)
            for j, id in enumerate(f):
                polygon.GetPointIds().SetId(j, id)
            polygons.InsertNextCell(polygon)

        size += len(xyz)

        polyLine = vtk.vtkPolyLine()
        polyLine.GetPointIds().SetNumberOfIds(2)
        for j, id in enumerate(links_points_ids[-2:]):
            polyLine.GetPointIds().SetId(j, id)
        link_cells.InsertNextCell(polyLine)

    colors = vtk.vtkNamedColors()

    link_polyData = vtk.vtkPolyData()
    link_polyData.SetPoints(links_points)
    link_polyData.SetLines(link_cells)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(link_polyData)
    fault_links_actor = vtk.vtkActor()
    fault_links_actor.SetScale(*FIELD['scales'])
    fault_links_actor.SetMapper(mapper)
    (fault_links_actor.GetProperty().SetColor(colors.GetColor3d('Purple')))

    FIELD[actor_names.fault_links] = fault_links_actor
    renderer.AddActor(fault_links_actor)

    label_polyData = vtk.vtkPolyData()
    label_polyData.SetPoints(labeled_points)
    label_polyData.GetPointData().AddArray(labels)
    label_mapper = vtk.vtkLabeledDataMapper()
    label_mapper.SetInputData(label_polyData)
    label_mapper.SetFieldDataName('labels')
    label_mapper.SetLabelModeToLabelFieldData()
    label_actor = vtk.vtkActor2D()
    label_actor.SetMapper(label_mapper)
    label_actor.GetProperty().SetColor(colors.GetColor3d('Purple'))

    FIELD[actor_names.fault_labels] = label_actor
    renderer.AddActor(label_actor)

    polygon_polyData = vtk.vtkPolyData()
    polygon_polyData.SetPoints(points)
    polygon_polyData.SetPolys(polygons)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(polygon_polyData)

    actor_faults = vtk.vtkActor()
    actor_faults.SetScale(*FIELD['scales'])
    actor_faults.SetMapper(mapper)
    actor_faults.GetProperty().SetColor(colors.GetColor3d('Purple'))

    renderer.AddActor(actor_faults)
    FIELD[actor_names.faults] = actor_faults
