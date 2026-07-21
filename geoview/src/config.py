"App configs."
from enum import Enum
from types import SimpleNamespace
from trame.app import get_server

from vtkmodules.vtkIOXML import vtkXMLUnstructuredGridReader
from vtkmodules.numpy_interface import dataset_adapter as dsa
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkDataSetMapper,
    vtkRenderer
)
import vtkmodules.vtkRenderingOpenGL2  # noqa


server = get_server(client_type="vue3")
state, ctrl = server.state, server.controller

jserver = dict(queue=None, results=None)

state.trame__title = "GeoView"

server.cli.add_argument("-vr", "--vtk_remote", action="store_true", help="choosing vtk remote rendering")
server.cli.add_argument(
    "--agent",
    action="store_true",
    help="start GeoAgent alongside the GeoView server",
)
server.cli.add_argument(
    "--agent-provider",
    choices=("lmstudio", "ollama", "gemini", "openai"),
    help="model provider for GeoAgent (prompted when omitted interactively)",
)
server.cli.add_argument(
    "--agent-model",
    metavar="MODEL_ID",
    help="provider model ID for GeoAgent",
)
server.cli.add_argument(
    "--agent-base-url",
    metavar="URL",
    help="local or OpenAI-compatible endpoint override for GeoAgent",
)
args = server.cli.parse_args()

state.vtk_remote = True if args.vtk_remote else False
agent_enabled = bool(args.agent)

renderer = vtkRenderer()
renderer.SetBackground(1, 1, 1)

actor_names = SimpleNamespace(
    wells='wells_actor',
    well_links='well_links_actor',
    well_labels='well_labels_actor',
    main='main_actor',
    faults='faults_actor',
    fault_labels='fault_labels_actor',
    fault_links='fault_links_actor'
)

dataset_names = SimpleNamespace(
    wells='wells_dataset'
)

FIELD = {"actor": None,
         "grid": None,
         "data1d": {'states': [], 'wells': [], 'tables': []},
         "model": None,
         "model_copy": None}
