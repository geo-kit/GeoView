from setuptools import setup, find_packages

VERSION = "0.0.1"

setup(
    name='GeoView',
    packages=find_packages(),
    version=VERSION,
    url='https://github.com/geo-kit/GeoView',
    license='GNU General Public License v3.0',
    author='geo-kit',
    author_email='',
    description='GeoView web application.',
    zip_safe=False,
    platforms='any',
    install_requires=[
        "GeoCode @ git+https://github.com/github.com/geo-kit/GeoCode",
        "trame",
        "trame-vuetify",
        "trame-vtk",
        "trame-components",
        "trame-matplotlib",
        "trame-plotly",
        "plotly"
    ],
    entry_points={
    'console_scripts': [
        'geoview = geoview.app:server_start',
    ],
    },
    extras_require={
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Science/Research',
        'License :: GNU General Public License v3.0',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Topic :: Scientific/Engineering'
    ],
)
