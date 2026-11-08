"""The few VTK classes the viewer uses directly.

Importing them from their own modules (instead of "import vtk", which loads all of VTK)
keeps the packaged app a few hundred megabytes smaller.
"""

from types import SimpleNamespace

from vtkmodules.vtkCommonCore import vtkPoints
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPlane, vtkPolyData, vtkPolyLine
from vtkmodules.vtkFiltersSources import vtkLineSource, vtkRegularPolygonSource, vtkSphereSource
from vtkmodules.vtkInteractionWidgets import vtkLogoRepresentation
from vtkmodules.vtkIOImage import vtkPNGReader
from vtkmodules.vtkRenderingCore import (
    vtkActor,
    vtkActor2D,
    vtkCoordinate,
    vtkPolyDataMapper,
    vtkPolyDataMapper2D,
    vtkRenderer,
    vtkTextActor,
    vtkWorldPointPicker,
)

vtk = SimpleNamespace(**{name: value for name, value in globals().items() if name.startswith("vtk")})
