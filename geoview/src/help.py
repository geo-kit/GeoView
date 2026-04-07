"Help page."
from trame.widgets import vuetify3 as vuetify


def render_help():
    "Help page layout."
    with vuetify.VCard(v_if="activeTab === 'home'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("Home page")
        vuetify.VCardText("Work with the application starts on the HOME page.\
        	The application supports reservoir models in the ECLIPSE file format.\
        	To load the model, input the path to the main reseroir model file with .DATA extension.\
        	You can use the up and down arrow keys and the enter key to autocomplete the path you type.\
        	Click the LOAD button or press the enter key to start reading data. This may take a while.\
        	Note that not all ECLIPSE keywords are supported.\
        	Read more about supported keywords and file formats here: https://github.com/deepfield-team/DeepField.",
        	style="text-wrap: auto",
        	)
        vuetify.VCardText("Once the model is loaded, click on one of the tabs in the top panel\
        	to begin exploring the model. Click on the help icon in the upper right corner\
        	to read a brief description of the page. Hover over buttons and icons to see a tooltip\
        	with textual information about them.",
        	style="text-wrap: auto",
        	classes='pt-1'
        	)
        vuetify.VCardText("Optionally, you can convert the model from .DATA format to .HDF5 format\
        	to speed up the next time you read the data.",
        	style="text-wrap: auto",
        	classes='pt-1'
        	)

    with vuetify.VCard(v_if="activeTab === '3d'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("3D view")
        vuetify.VCardText("This tab shows static and dynamic fields available in the\
        	reservoir model in 3D. Dynamic fields are available if the model is\
        	simulated and contains the RESULTS folder.\
            The color of a well indicates its status. \
            Green indicates an active producing well, \
            blue indicates an active injection well, \
            and red indicates an inactive well.",
        	style="text-wrap: auto",
        	)
        vuetify.VCardText("Use the left toolbar to change the displayed data,\
            filter data, and control the appearance and visibility of objects.\
            Use the timestep slider or calendar to view changes in reservoir dynamics\
            and well status.",
            style="text-wrap: auto",
            classes='pt-1'
            )
        vuetify.VCardText("Press the play icon to start animation of dynamic reservoir\
            fields. Click the speedometer icon to cyclically change the animation speed:\
            0.5s, 0.1s, 1s.",
            style="text-wrap: auto",
            classes='pt-1'
            )
        vuetify.VCardText("Hint: use SHIFT + left mouse button to move the scene on the screen.",
            style="text-wrap: auto",
            classes='pt-1'
            )

    with vuetify.VCard(v_if="activeTab === '2d'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("2D view")
        vuetify.VCardText("This tab shows 2D slices of static and dynamic fields available in the\
        	reservoir model. Dynamic field are available if the model is\
        	simulated and contains the RESULTS folder.\
        	Use the left toolbar to change the displayed data\
        	and control the appearance.",
        	style="text-wrap: auto")

    with vuetify.VCard(v_if="activeTab === 'ts'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("Timeseries")
        vuetify.VCardText("This tab allows you to plot and compare various dynamic (time-dependent)\
        	properties of the simulated reservoir model attributed to grid cells or wells.\
        	Select one of the properties in the first dropdown list.\
        	If the selected property is attributed to grid cells (for example, PRESSURE),\
        	you can specify the range of grid cells over which the property will be averaged.\
        	By default, the property is averaged over the entire reservoir model.\
        	Click ADD LINE button to add the line to the plot.\
        	If the selected property is attributed to wells, you will need to specify well name.\
        	If you want to compare two properties with different scales,\
        	you can add a second axis to the plot using the toggle button.\
        	You can add many lines to the plot and distribute them between axes.\
        	To delete the last added line, click the UNDO button.\
        	Click the button CLEAN to remove all lines from the plot.",
        	style="text-wrap: auto")
        vuetify.VCardText("Click the EXPORT button to save the plot data to a csv file.",
            style="text-wrap: auto",
            classes='pt-1'
            )

    with vuetify.VCard(v_if="activeTab === 'pvt'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'
        ):
        vuetify.VCardTitle("PVT / Relative permeability")
        vuetify.VCardText("This tab shows plots obtained from\
        	interpolation of PVT or relative permeability tables.\
        	Select one of the properties in the first dropdown list.\
        	If the selected property is two-dimensional, select which\
        	value will be shown on the x-axis and set the second value using the slider.",
        	style="text-wrap: auto")

    with vuetify.VCard(v_if="activeTab === 'info'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'
        ):
        vuetify.VCardTitle("Info")
        vuetify.VCardText("This tab summarizes general properties of the reservoir model.",
        	style="text-wrap: auto")

    with vuetify.VCard(v_if="activeTab === 'script'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'
        ):
        vuetify.VCardTitle("Script")
        vuetify.VCardText("This tab allows you to write and execute\
        	custom python scripts for the reservoir model.\
        	The script shoud be contained in a single function named 'f' with a\
        	single agrument 'field'. When executed, the 'field' argument is\
        	substituted with the actual reservoir model.\
        	The script can contain reservoir model transformations or calculations.\
        	See the documentation and examples in the DeepField repository\
        	https://github.com/deepfield-team/DeepField \
        	to prepare the script.\
        	Click EXECUTE button to run the script.",
        	style="text-wrap: auto")
        vuetify.VCardText("The returned value or error message will be displayed in the Output window.\
        	Changes in the reservoir model can be viewed in the corresponding\
        	tabs of the application.",
        	style="text-wrap: auto",
        	classes='pt-1'
        	)
