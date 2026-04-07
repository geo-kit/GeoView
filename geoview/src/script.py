"Script page."
from trame.widgets import vuetify3 as vuetify

from .config import state, FIELD
from .home import process_field


state.scriptInput = """
def f(field): #do not change this line
    return
"""
state.scriptOutput = ''
state.scriptRunning = False


@state.change("scriptRunning")
def run_script(scriptRunning, **kwargs):
    "Run script."
    _ = kwargs

    if not scriptRunning:
        return

    local_vars = {}
    exec(state.scriptInput, None, local_vars)
    success = False
    res = ''

    if 'f' in local_vars:
        try:
            res = local_vars['f'](FIELD['model'])
            success = True
        except Exception as err:
            res = 'Script failed: ' + str(err)
            success = False
    if success and FIELD['model'] is not None:
        try:
            process_field(FIELD['model'])
            state.modelID += 1
        except Exception as err:
            res = 'Field update failed: ' + str(err)
    state.scriptOutput = str(res)
    state.scriptRunning = False


def render_script():
    "Script page layout."
    vuetify.VTextarea(
    	v_model=('scriptInput',),
    	label="Type function to be executed")
    with vuetify.VBtn('Execute',
        click='scriptRunning = true',
        color='#51b03c',
        loading=('scriptRunning',)):
        vuetify.VTooltip(
            text='Run the script',
            activator="parent",
            location="end")

    with vuetify.VCard(style="margin-top: 10px", variant='flat'):
        vuetify.VCardTitle("Ouptput:")
        vuetify.VCardText('{{scriptOutput}}')
