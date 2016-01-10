from scipy.interpolate import RectBivariateSpline
from cachetools import cachedmethod, LRUCache
from py import path
import numpy as np
from xray import DataArray, Dataset
import operator


__all__ = ['Field']


class Field(object):
    """Class that encapsulates access to field data.

    :param name: Name of the field
    :param data: 2D array of field data
    :param lon: Longitude coordinates of the field
    :param lat: Latitude coordinates of the field
    """

    def __init__(self, name, data, lon, lat, depth=None, time=None):
        self.name = name
        self.data = data
        self.lon = lon
        self.lat = lat
        self.depth = np.zeros(1, dtype=np.float32) if depth is None else depth
        self.time = np.zeros(1, dtype=np.float64) if time is None else time

        # Hack around the fact that NaN values
        # propagate in SciPy's interpolators
        self.data[np.isnan(self.data)] = 0.

        # Variable names in JIT code
        self.ccode_data = self.name
        self.ccode_lon = self.name + "_lon"
        self.ccode_lat = self.name + "_lat"

        self.interpolator_cache = LRUCache(maxsize=1)
        self.time_index_cache = LRUCache(maxsize=1)

    def __getitem__(self, key):
        return self.eval(*key)

    @cachedmethod(operator.attrgetter('interpolator_cache'))
    def interpolator(self, t_idx):
        return RectBivariateSpline(self.lat, self.lon,
                                   self.data[t_idx, :])

    @cachedmethod(operator.attrgetter('time_index_cache'))
    def time_index(self, time):
        return np.argmax(self.time >= time)

    def eval(self, time, x, y):
        interpolator = self.interpolator(self.time_index(time))
        return interpolator.ev(y, x)

    def ccode_subscript(self, x, y):
        ccode = "interpolate_bilinear(%s, %s, %s, %s, %s, %s, %s)" \
                % (y, x, "particle->yi", "particle->xi",
                   self.ccode_lat, self.ccode_lon, self.ccode_data)
        return ccode

    def write(self, filename, varname=None):
        filepath = str(path.local('%s_%s.nc' % (filename, self.name)))
        if varname is None:
            varname = self.name
        # Derive name of 'depth' variable for NEMO convention
        vname_depth = 'depth%s' % self.name.lower()

        # Create DataArray objects for file I/O
        t, d, x, y = (self.time.size, self.depth.size,
                      self.lon.size, self.lat.size)
        nav_lon = DataArray(self.lon + np.zeros((y, x), dtype=np.float32),
                            coords=[('y', self.lat), ('x', self.lon)])
        nav_lat = DataArray(self.lat.reshape(y, 1) + np.zeros(x, dtype=np.float32),
                            coords=[('y', self.lat), ('x', self.lon)])
        vardata = DataArray(self.data.reshape((t, d, y, x)),
                            coords=[('time_counter', self.time),
                                    (vname_depth, self.depth),
                                    ('y', self.lat), ('x', self.lon)])
        # Create xray Dataset and output to netCDF format
        dset = Dataset({varname: vardata}, coords={'nav_lon': nav_lon,
                                                   'nav_lat': nav_lat})
        dset.to_netcdf(filepath)
