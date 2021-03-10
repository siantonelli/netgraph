#!/usr/bin/env python
"""
Classes for artists used to display
- nodes / vertices
- edges
"""

import numpy as np
import matplotlib.pyplot as plt

from matplotlib.path import Path
from matplotlib.patches import PathPatch, transforms, Circle


class PathPatchDataUnits(PathPatch):
    # adapted from https://stackoverflow.com/a/42972469/2912349
    def __init__(self, *args, **kwargs):
        _lw_data = kwargs.pop("linewidth", 1)
        super().__init__(*args, **kwargs)
        self._lw_data = _lw_data

    def _get_lw(self):
        if self.axes is not None:
            ppd = 72./self.axes.figure.dpi
            trans = self.axes.transData.transform
            return ((trans((self._lw_data, self._lw_data))-trans((0, 0)))*ppd)[0]
            # return ((trans((self._lw_data, self._lw_data))-trans((0, 0)))*ppd)[1]
        else:
            return 1

    def _set_lw(self, lw):
        self._lw_data = lw

    _linewidth = property(_get_lw, _set_lw)


# ------------------------------------------------------------------------------------------
# node artist

class CircleDataUnits(Circle):
    # TODO
    pass


# TODO: potentially apply transform before passing it to PathPatchDataUnits
class RegularPolygonDataUnits(PathPatchDataUnits):
    """A regular polygon patch."""

    def __str__(self):
        s = "RegularPolygon((%g, %g), %d, radius=%g, orientation=%g)"
        return s % (self.xy[0], self.xy[1], self.numvertices, self.radius,
                    self.orientation)

    def __init__(self, xy, numVertices, radius=5, orientation=0,
                 **kwargs):
        """
        Parameters
        ----------
        xy : (float, float)
            The center position.
        numVertices : int
            The number of vertices.
        radius : float
            The distance from the center to each of the vertices.
        orientation : float
            The polygon rotation angle (in radians).
        **kwargs
            `Patch` properties:
            %(Patch_kwdoc)s
        """
        self.xy = xy
        self.numvertices = numVertices
        self.orientation = orientation
        self.radius = radius
        self._path = Path.unit_regular_polygon(numVertices)
        self._patch_transform = transforms.Affine2D()
        super().__init__(path=self._path, **kwargs)

    def get_path(self):
        return self._path

    def get_patch_transform(self):
        return self._patch_transform.clear() \
            .scale(self.radius) \
            .rotate(self.orientation) \
            .translate(*self.xy)