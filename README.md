# GeoView

Web application for simulation and visualization of reservoir models.

Lightweight. Modern. Open source.

## Features

Use the application to
* read reservoir models given in ECLIPSE file format;
* simulate models using JutulDarcy simulator;
* view and explore static and dynamic data in 3D, 2D, and 1D;
* export simulated data in ECLIPSE and CSV formats;
* write and execute custom python scripts for reservoir transformations and calculations;
* work locally or on a remote server.

Main page of the application:

<img src="static/scene0.PNG" width="50%"/>

Simulated reservoir dynamics in 3D:

<img src="static/soil_deepfield.gif" width="50%"/>

Filtering of grid cells and indication of well status (producing, injecting, inactive):

<img src="static/scene1.PNG" width="50%"/>

Selection of cells along well trajectories:

<img src="static/scene_wells.PNG" width="50%"/>

2D slice view:

<img src="static/scene2.PNG" width="50%"/>

Construction of a multiline 1D plot to compare dynamic properties:

<img src="static/scene3.PNG" width="50%"/>

Visualization of PVT and relative permeability tables:

<img src="static/scene4.PNG" width="50%"/>

Description of the reservoir model:

<img src="static/scene5.PNG" width="50%"/>

Script writing:

<img src="static/scene6.PNG" width="50%"/>

...and the results of its execution:

<img src="static/scene7.PNG" width="50%"/>

## Performance

Loading time and memory usage for benchmark models in the [benchmarks](https://github.com/deepfield-team/DeepField-app/benchmarks) directory measured on a PC with Intel Core Ultra 7, 3.9GHz, 64Gb CPU:

| Number of cells | Loading time | Memory usage |
|-------|---------|---------|
| 1M | 23s | 0.5Gb |
| 10M | 3m 49s | 2.6Gb |
| 50M | 19m 26s | 10.3Gb |

## Installation as a package

We recommend creating a new virtual environment with python 3.11 to install the project dependencies:

	conda create -n app python=3.11

Activate the new environment:

	conda activate app

To install the project dependencies, run in the terminal:

    pip install "git+https://github.com/deepfield-team/DeepField-app.git"

After installation, run in the terminal:

	deepfield-app

This should open a new tab in your default browser to http://localhost:8080/ with the application's home page.

You can add a few optional parameters to the application start command:
* --server - use to prevent a new tab from opening in the browser
* --app - use to launch the application in a separate window rather than in the browser
* --port 1234 - to change the default port 8080 to, e.g., 1234

When the application is running, you can click on the help icon in
the upper right corner to read a brief description of the page. 
Hover over buttons and icons to see a tooltip with textual information
about them.

 > [!NOTE]
 > The installation of JutulDarcy simulator will be done automatically at the very first launch of the application. It may take some time.

## Installation from source code

Another option to run the application is to clone the entire repository:

	git clone https://github.com/deepfield-team/DeepField-app.git

Addionally, you will need to clone the repository `DeepField` into the same directory as the `DeepField-app`:

	git clone https://github.com/deepfield-team/DeepField.git

Install dependencties in both repositories using

	pip install -r requirements.txt

Then navigate to the directory DeepField-app and run in the terminal

	python -m deepfield_app.app

to start the application.

 > [!NOTE]
 > The installation of JutulDarcy simulator will be done automatically at the very first launch of the application. It may take some time.


## Rendering options

By default, rendering is performed locally in the user's browser using vtk webassembly functionality.
To enable vtk remote rendering, use the `-vr` or `--vtk_remote` option when starting the application. 
Note that the functionality of the application is slightly different between local and remote rendering.

## Open-source reservoir models

An example reservoir model with dynamics simulation can be found in the `open_data` directory in the `DeepField` repository [https://github.com/deepfield-team/DeepField](https://github.com/deepfield-team/DeepField),
as well as links to a number of other open source models.

## Script writing

The application allows you to write and execute python scripts for
reservoir model transformations and calculations. The script should 
be based on the `DeepField` framework 
[https://github.com/deepfield-team/DeepField](https://github.com/deepfield-team/DeepField).
Read the [documentation](https://deepfield-team.github.io/DeepField/)
and see
[examples](https://github.com/deepfield-team/DeepField/blob/main/tutorials) 
in the `DeepField` repository to prepare a script.

## Next releases

The project is developing. We are preparing new releases with new features.
Your suggestions and issues reports will help to make the application even better.

## What's inside

We use
* [trame](https://github.com/Kitware/trame) to build the web application
* [DeepField](https://github.com/deepfield-team/DeepField) to read and process reservoir models
* [JutulDarcy](https://github.com/sintefmath/JutulDarcy.jl) for reservoir simulation

## Citing

We hope that this project will help you in your research and you will decide to cite it as
```
DeepField web application (2024). GitHub repository, https://github.com/deepfield-team/DeepField-app.
```
