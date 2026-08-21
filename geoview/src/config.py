"App configs."
import os
from pathlib import Path
from types import SimpleNamespace
from trame.app import get_server

from vtkmodules.vtkRenderingCore import vtkRenderer
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
    choices=("lmstudio", "ollama", "openai"),
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
server.cli.add_argument(
    "--ru",
    action="store_true",
    help="Russian wording in the GeoAgent chat (English otherwise)",
)
args = server.cli.parse_args()

state.vtk_remote = True if args.vtk_remote else False
agent_enabled = bool(args.agent)

# Language of the GeoAgent chat and of the context block sent with every message.
# English unless --ru is passed; the strings themselves live in src/agent_text.py.
CHAT_LANG = "ru" if args.ru else "en"

# GeoView side of the agent artifact contract. The agent writes requests and results
# here; app.py passes the path to the agent process, agent_chat.py watches it.
AGENT_RESULT_DIR = Path(__file__).resolve().parents[2] / ".agent_runtime"

# Which agent GeoView talks to. One switch, because the two differ in both the
# checkout to launch and the preamble they expect:
#   public (default) — GeoAgent, which computes nothing and drives GeoView instead
#   pro              — GeoAgentPro, which runs JutulDarcy in its own environment
# GEOVIEW_AGENT_DIR overrides the directory alone, for a checkout named differently.
AGENT_PROFILE = os.environ.get("GEOVIEW_AGENT_PROFILE", "public").strip().lower()
AGENT_DIR_NAME = os.environ.get("GEOVIEW_AGENT_DIR", "").strip() or (
    "GeoAgentPro" if AGENT_PROFILE == "pro" else "GeoAgent")

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
