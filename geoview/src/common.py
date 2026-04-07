"Common utils."
import numpy as np
from vtk.util.numpy_support import numpy_to_vtk # pylint: disable=no-name-in-module, import-error

from .config import state, renderer, FIELD


state.need_time_slider = False
state.activeStep = 0


def reset_camera():
	"Reset camera."
	renderer.ResetCamera()
	camera = renderer.GetActiveCamera()
	x, y, z = camera.GetPosition()
	fx, fy, fz = camera.GetFocalPoint()
	dist = np.linalg.norm(np.array([x, y, z]) - np.array([fx, fy, fz]))
	camera.SetPosition(fx-dist/np.sqrt(3), fy-dist/np.sqrt(3), fz-dist/np.sqrt(3))
	camera.SetViewUp(0, 0, -1)
	renderer.ResetCamera()

def update_field_slices_params(fmin, fmax):
    "Init filter limits."
    state.field_slice_min = fmin
    state.field_slice_max = fmax
    state.field_slice_0 = state.field_slice_min
    state.field_slice_1 = state.field_slice_max
    state.field_slice = [state.field_slice_min, state.field_slice_max]
    state.field_slice_step = (state.field_slice_max - state.field_slice_min) / state.n_field_steps

def set_active_scalars(update_range):
	"Set active scalars."
	comp, attr = state.activeField.lower().split('_')
	field = FIELD['model']
	data = getattr(getattr(field, comp), attr)
	actnum = field.grid.actnum_ids

	if comp == 'states':
		activeStep = int(state.activeStep) if state.activeStep else 0
		if activeStep >= len(data):
			activeStep = len(data) - 1
		if update_range:
			data = data.reshape(len(data), -1)[:, actnum]
			fmin, fmax = data.min(), data.max()
			update_field_slices_params(fmin, fmax)
			data = data[activeStep]
		else:
			data = data[activeStep].ravel()[actnum]
	else:
		data = data.ravel()[actnum]
		if update_range:
			fmin, fmax = data.min(), data.max()
			update_field_slices_params(fmin, fmax)

	vtk_array = numpy_to_vtk(data)
	vtk_array.SetName('ActiveScalars')

	vtk_grid = FIELD['grid']
	vtk_grid.GetCellData().AddArray(vtk_array)
	vtk_grid.GetCellData().SetActiveScalars('ActiveScalars')
