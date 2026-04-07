"Custom classes."
import vtk
from vtkmodules.vtkCommonCore import vtkIdTypeArray
from vtkmodules.vtkCommonColor import vtkNamedColors
from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid, vtkSelectionNode, vtkSelection
from vtkmodules.vtkFiltersExtraction import vtkExtractSelection
from vtkmodules.vtkRenderingCore import vtkDataSetMapper
from .config import state, FIELD, actor_names

colors = vtkNamedColors()

class CustomInteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    "CustomInteractorStyle class."
    def __init__(self, renderer, renderWindow):

        self.AddObserver('LeftButtonPressEvent', self.OnLeftButtonDown)
        self.AddObserver('LeftButtonReleaseEvent', self.OnLeftButtonRelease)

        self.renderer = renderer
        self.renderWindow = renderWindow
        self.picker = vtk.vtkCellPicker()
        self.selection = vtkSelection()
        self.selected_actor = None
        self.selected = vtkUnstructuredGrid()
        self.selection_node = vtkSelectionNode()
        self.selection_node.SetFieldType(vtkSelectionNode.CELL)
        self.selection_node.SetContentType(vtkSelectionNode.INDICES)

        self.extract_selection = vtkExtractSelection()
        self.selected_mapper = vtkDataSetMapper()
        self.text_mapper = vtk.vtkTextMapper()

        self.currentId = -1

        tprop = self.text_mapper.GetTextProperty()
        tprop.SetFontFamilyToArial()
        tprop.SetFontSize(16)
        tprop.ShadowOn()

        if state.theme == 'dark':
            tprop.SetColor(1, 1, 1)
        else:
            tprop.SetColor(0, 0, 0)

        tprop.SetVerticalJustificationToBottom()

        self.text_actor = vtk.vtkActor2D()
        self.text_actor.SetDisplayPosition(90, 60)
        self.text_actor.VisibilityOn()
        self.text_actor.SetMapper(self.text_mapper)

    def ChangeTheme(self, theme):
        "Change theme."
        tprop = self.text_mapper.GetTextProperty()
        if theme == 'light':
            tprop.SetColor(0, 0, 0)
        else:
            tprop.SetColor(1, 1, 1)

    def _AnnotatePick(self, cellId, update=False):
        if cellId == -1:
            return

        if (self.currentId == cellId) and not update:
            self.renderer.RemoveActor(self.text_actor)
            return
        
        dataset = FIELD[actor_names.main].GetMapper().GetInput()

        ix = dataset.GetCellData().GetArray('I').GetValue(cellId)
        jx = dataset.GetCellData().GetArray('J').GetValue(cellId)
        kx = dataset.GetCellData().GetArray('K').GetValue(cellId)
        info = ""
        arr = dataset.GetCellData().GetArray('ActiveScalars')
        value = arr.GetValue(cellId)
        info += f"{state.activeField}: {value:.2f}\n\n"
        info += f"(I, J, K) = ({ix+1}, {jx+1}, {kx+1})"
        self.text_mapper.SetInput(info)
        self.text_actor.VisibilityOn()
        self.renderer.AddActor(self.text_actor)

    def _HighlightCell(self, cellId):
        if cellId == -1:
            return

        if self.currentId == cellId:
            self.renderer.RemoveActor(self.selected_actor)
            return

        if self.selected_actor is not None:
            self.renderer.RemoveActor(self.selected_actor)

        self.ids = vtkIdTypeArray()
        self.ids.SetNumberOfComponents(1)
        self.ids.InsertNextValue(cellId)
        self.selection_node.SetSelectionList(self.ids)
        self.selection.AddNode(self.selection_node)
        dataset = FIELD[actor_names.main].GetMapper().GetInput()
        self.extract_selection.SetInputData(0, dataset)
        self.extract_selection.SetInputData(1, self.selection)
        self.extract_selection.Update()
        self.selected.ShallowCopy(self.extract_selection.GetOutput())
        self.selected_mapper.SetInputData(self.selected)
        self.selected_actor = vtk.vtkActor()
        self.selected_actor.SetMapper(self.selected_mapper)
        self.selected_actor.SetScale(*FIELD['scales'])
        self.selected_actor.GetProperty().SetRepresentationToWireframe()
        self.selected_actor.GetMapper().ScalarVisibilityOff()
        self.selected_actor.GetProperty().SetColor(colors.GetColor3d('Red'))
        self.selected_actor.GetProperty().SetLineWidth(4)
        self.renderer.AddActor(self.selected_actor)

    def OnLeftButtonRelease(self, obj, eventType):
        "OnLeftButtonRelease."
        _ = obj, eventType
        vtk.vtkInteractorStyleTrackballCamera.OnLeftButtonUp(self)

    def OnLeftButtonDown(self, obj, eventType):
        "OnLeftButtonDown."
        _ = obj, eventType
        clickPos = self.GetInteractor().GetEventPosition()
        self.picker.Pick(clickPos[0], clickPos[1], 0, self.renderer)
        cellId = self.picker.GetCellId()
        self._HighlightCell(cellId)
        self._AnnotatePick(cellId)

        if self.currentId == cellId:
            self.currentId = -1
        else:
            self.currentId = cellId

        vtk.vtkInteractorStyleTrackballCamera.OnLeftButtonDown(self)

    def RemoveActors(self):
        "RemoveActors."
        if self.selected_actor is not None:
            self.renderer.RemoveActor(self.selected_actor)
        self.renderer.RemoveActor(self.text_actor)
