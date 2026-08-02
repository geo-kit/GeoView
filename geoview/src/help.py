"Help page."
from trame.widgets import html, vuetify3 as vuetify


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
        	Click the LOAD button or press the enter key to start reading data. \
            This may take a while to read and process text and binary data files.\
        	Note that not all ECLIPSE keywords are supported.\
        	Learn more about supported keywords at https://github.com/GeoKit/GeoCode.",
        	style="text-wrap: auto",
        	)
        vuetify.VCardText("Once the model is loaded, click on one of the tabs in the top panel\
        	to begin exploring the model or click the SIMULATE button to execute the\
            JutulDarcy porous media simulator \
            (if the model does not include binary files with simulation results).",
        	style="text-wrap: auto",
        	classes='pt-1'
        	)

    with vuetify.VCard(v_if="activeTab === '3d'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("3D view")
        vuetify.VCardText("This tab shows static and dynamic fields available in the\
        	reservoir model in 3D. Dynamic fields are available if the model is\
        	simulated.\
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
        	simulated.\
        	Use the left toolbar to change the displayed data\
        	and control the appearance.",
        	style="text-wrap: auto")

    with vuetify.VCard(v_if="activeTab === 'ts'",
        classes="pa-2 text-truncate",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("Timeseries")
        vuetify.VCardText("This tab dislays simulated dynamic (time-dependent)\
        	reservoir model properties attributed to grid cells or wells.\
        	Select one of the properties in the first dropdown list.\
        	If the selected property is attributed to grid cells (for example, PRESSURE),\
        	the range of grid cells over which the property will be averaged can be specified.\
        	By default, the property is averaged over the entire reservoir model.\
        	Click ADD LINE button to add the line to the plot.\
        	If the selected property is attributed to wells, a well name should be specified.\
        	To compare two properties with different scales,\
        	add a second axis to the plot using the toggle button.\
        	Any number of lines can be added to the plot and distributed between axes.\
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

    with vuetify.VCard(v_if="activeTab === 'opt'",
        classes="pa-2",
        style='max-width: 80vw;'):
        vuetify.VCardTitle("Optimization")
        vuetify.VCardText("This tab optimizes forecast well BHP controls to maximize discounted NPV.\
            The optimized variables are producer and injector BHP values and \
            the objective is the discounted sum of timestep cash flow:.",
            style="text-wrap: auto")
        with html.Div(
            style="font-size: 1.05rem; padding: 8px 12px; margin: 4px 0; "
                  "background: rgba(0,0,0,0.04); border-radius: 4px; "
                  "font-family: Georgia, 'Times New Roman', serif; overflow-wrap: anywhere"):
            html.Span("NPV = ")
            html.Span("Σ", style="font-size: 1.4rem")
            html.Sub("t")
            html.Span(" [ p")
            html.Sub("o")
            html.Span("q")
            html.Sub("o,t")
            html.Span(" + p")
            html.Sub("g")
            html.Span("q")
            html.Sub("g,t")
            html.Span(" − c")
            html.Sub("wp")
            html.Span("q")
            html.Sub("wp,t")
            html.Span(" − c")
            html.Sub("wi")
            html.Span("q")
            html.Sub("wi,t")
            html.Span(" − c")
            html.Sub("gi")
            html.Span("q")
            html.Sub("gi,t")
            html.Span(" ] / (1 + r)")
            html.Sup("Tₜ")
        vuetify.VCardText("Here p is oil/gas price, c is water/gas handling cost, q is rate or volume contribution, r is annual discount rate, and T is time in years.",
            style="text-wrap: auto",
            classes='pt-1')
        vuetify.VCardText("To start optimization, click the SETTINGS button and fill in all required fields. \
            Enter prices and costs as positive $/m3 values.\
            Discount rate is percent per year. Forecast months is the number of monthly\
            control steps to optimize. Max iterations limits the L-BFGS optimizer work;\
            larger values can improve the result but take longer. Once all fields are filled in,\
            click the OPTIMIZE button to start the process.",
            style="text-wrap: auto",
            classes='pt-1')

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
        	See the documentation and examples in the GeoCode repository\
        	https://github.com/GeoKit/GeoCode \
        	to prepare the script.\
        	Click EXECUTE button to run the script.",
        	style="text-wrap: auto")
        vuetify.VCardText("The returned value or error message will be displayed in the Output window.\
        	Changes in the reservoir model can be viewed in the corresponding\
        	tabs of the application.",
        	style="text-wrap: auto",
        	classes='pt-1'
        	)
