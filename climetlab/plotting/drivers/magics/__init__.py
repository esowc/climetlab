# (C) Copyright 2020 ECMWF.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.
#

# Keep linters happy
# N801 = classes should start with uppercase
# N806 = variables should be lower case

import os
import logging
import yaml
from collections import defaultdict

# This is needed when running Sphinx on ReadTheDoc

try:
    from Magics import macro
except Exception:
    macro = None


from climetlab.core.caching import temp_file
from climetlab.core.ipython import SVG, Image
from climetlab.core.data import get_data_entry
from climetlab.core.metadata import annotation
from climetlab.core.bbox import BoundingBox

LOG = logging.getLogger(__name__)


# Examples of Magics macros:
# https://github.com/ecmwf/notebook-examples/tree/master/visualisation


class Action:

    default_style = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __repr__(self):
        x = ["macro.%s(" % (self.action,)]
        for k, v in sorted(self.kwargs.items()):
            x.append("\n   %s=%r," % (k, v))
        x.append("\n    )")
        return "".join(x)

    @property
    def action(self):
        return self.__class__.__name__

    def execute(self):
        return getattr(macro, self.action)(**self.kwargs).execute()

    def update(self, action, values):
        if isinstance(self, action):
            for k, v in values.items():
                if k[0] in ("+",):
                    self.kwargs[k[1:]] = v
                if k[0] in ("-",):
                    self.kwargs.pop(k[1:], None)
                if k[0] in ("=",):
                    if k[1:] not in self.kwargs:
                        self.kwargs[k[1:]] = v
            return self
        return None


class mcont(Action):  # noqa: N801
    pass


class mcoast(Action):  # noqa: N801
    pass


class mmap(Action):  # noqa: N801
    def page_ratio(self):
        south = self.kwargs.get("subpage_lower_left_latitude", -90.0)
        west = self.kwargs.get("subpage_lower_left_longitude", -180)
        north = self.kwargs.get("subpage_upper_right_latitude", 90.0)
        east = self.kwargs.get("subpage_upper_right_longitude", 180.0)
        return (north - south) / (east - west)


class FieldAction(Action):
    default_style = mcont(contour_automatic_setting="ecmwf", legend=False)


class mgrib(FieldAction):  # noqa: N801
    pass


class mnetcdf(FieldAction):  # noqa: N801
    pass


class minput(FieldAction):  # noqa: N801
    pass


class mtable(Action):  # noqa: N801
    pass


class mtext(Action):  # noqa: N801
    pass


class msymb(Action):  # noqa: N801
    pass


class output(Action):  # noqa: N801
    pass


class Layer:
    def __init__(self, data):
        self._data = data
        self._style = data.default_style

    def add_action(self, actions):
        if self._data:
            actions.append(self._data)
        if self._style:
            actions.append(self._style)

    def style(self, style):
        self._style = style

    def update(self, action, value):
        return self._style.update(action, value)


MAGICS_KEYS = None


def _apply(*, value, collection=None, action=None, default=True, target=None):

    if value is None:
        return None

    if value is False:
        return None

    if value is True:
        assert default is not True
        return _apply(
            value=default,
            collection=collection,
            action=action,
            default=None,
            target=target,
        )

    if isinstance(value, dict):

        if "set" in value or "clear" in value:
            newvalue = {}
            for k, v in value.get("set", {}).items():
                newvalue["+{}".format(k)] = v

            for k in value.get("clear", []):
                newvalue["-{}".format(k)] = None

            return _apply(
                value=newvalue,
                collection=collection,
                action=action,
                default=default,
                target=target,
            )

        if "+" in value or "-" in value:
            newvalue = {}
            for k, v in value.get("+", {}).items():
                newvalue["+{}".format(k)] = v

            for k in value.get("-", []):
                newvalue["-{}".format(k)] = None

            return _apply(
                value=newvalue,
                collection=collection,
                action=action,
                default=default,
                target=target,
            )

        global MAGICS_KEYS

        if MAGICS_KEYS is None:
            MAGICS_KEYS = defaultdict(set)
            with open(os.path.join(os.path.dirname(__file__), "magics.yaml")) as f:
                magics = yaml.load(f, Loader=yaml.SafeLoader)
                for name, params in magics.items():
                    for param in params:
                        MAGICS_KEYS[param].add(name)

        # Guess the best action from the keys
        scores = defaultdict(int)
        special = 0
        for param in value.keys():

            if not param[0].isalpha():
                special += 1
                param = param[1:]

            acts = MAGICS_KEYS.get(param, [])
            if len(acts) == 1:
                # Only consider unambiguous parameters
                scores[list(acts)[0]] += 1

        best = sorted((v, k) for k, v in scores.items())

        if len(best) == 0:
            LOG.warning("Cannot establish Magics action from [%r]", list(value.keys()))

        if len(best) >= 2:
            if best[0][0] == best[1][0]:
                LOG.warning(
                    "Cannot establish Magics action from [%r], it could be %s or %s",
                    list(value.keys()),
                    best[0][1],
                    best[1][1],
                )

        if len(best) > 0:
            action = globals()[best[0][1]]

        if special:
            if special != len(value):
                raise Exception(
                    "Cannot set some attributes and override others %r"
                    % list(value.keys())
                )

            result = target.update(action, value)
            if result is not None:
                return result

            raise Exception(
                "Cannot override attributes %r (no matching style)" % list(value.keys())
            )

        return action(**value)

    if isinstance(value, str):

        # TODO: Consider `value` being a URL (yaml or json)

        data = get_data_entry(collection, value).data

        magics = data["magics"]
        actions = list(magics.keys())
        assert len(actions) == 1, actions

        action = globals()[actions[0]]
        return action(**magics[actions[0]])

    assert False, (collection, value)


class Driver:
    """TODO: Docscting
    """

    def __init__(self, options):

        self._options = options

        self._projection = None
        self._background = None
        self._foreground = None

        self._layers = []
        self._width_cm = 10.0
        self._height_cm = 10.0

        self._page_ratio = 1.0

        self.background(True)
        self.foreground(True)

        self._grid = None
        self._rivers = None
        self._cities = None
        self._borders = None

        self._legend = None
        self._title = None

        self._bounding_box = None
        self._tmp = []

    def temporary_file(self, extension: str = ".tmp") -> str:
        """Return a temporary file name that will be deleted once the plot is produced.

        :param extension: File name extension, defaults to ".tmp"
        :type extension: str, optional
        :return: Temporary file name.
        :rtype: str
        """
        self._tmp.append(temp_file(extension))
        return self._tmp[-1].path

    def bounding_box(self, north: float, west: float, south: float, east: float):

        bbox = BoundingBox(north=north, west=west, south=south, east=east)
        if self._bounding_box is None:
            self._bounding_box = bbox
        else:
            self._bounding_box = self._bounding_box.merge(bbox)

    def _push_layer(self, data):
        self._layers.append(Layer(data))

    def plot_grib(self, path: str, offset: int):

        self._push_layer(
            mgrib(
                grib_input_file_name=path,
                grib_file_address_mode="byte_offset",
                grib_field_position=int(offset),
            )
        )

    def plot_netcdf(self, path: str, variable: str, dimensions: dict = None):

        if dimensions is None:
            dimensions = {}

        dimension_setting = ["%s:%s" % (k, v) for k, v in dimensions.items()]

        if dimension_setting:
            params = dict(
                netcdf_filename=path,
                netcdf_value_variable=variable,
                netcdf_dimension_setting=dimension_setting,
                netcdf_dimension_setting_method="index",
            )
        else:
            params = dict(netcdf_filename=path, netcdf_value_variable=variable)

        self._push_layer(mnetcdf(**params))

    def plot_numpy(
        self,
        data,
        north: float,
        west: float,
        south_north_increment: float,
        west_east_increment: float,
        metadata: dict = None,
    ):
        if metadata is None:
            metadata = {}

        self._push_layer(
            minput(
                input_field=data,
                input_field_initial_latitude=float(north),
                input_field_latitude_step=-float(south_north_increment),
                input_field_initial_longitude=float(west),
                input_field_longitude_step=float(west_east_increment),
                input_metadata=metadata,
            )
        )

    def plot_xarray(self, ds, variable: str, dimensions: dict = None):
        tmp = self.temporary_file(".nc")
        ds.to_netcdf(tmp)
        self.plot_netcdf(tmp, variable, {} if dimensions is None else dimensions)

    def plot_csv(self, path: str, variable: str):
        self._push_layer(
            mtable(
                table_filename=path,
                table_latitude_variable="1",
                table_longitude_variable="2",
                table_value_variable="3",
                table_header_row=0,
                table_variable_identifier_type="index",
            )
        )
        self.style("default-style-observations")

    def plot_pandas(self, frame, latitude: str, longitude: str, variable: str):
        tmp = self.temporary_file(".csv")
        frame[[latitude, longitude, variable]].to_csv(tmp, header=False, index=False)
        self.plot_csv(tmp, variable)

        style = annotation(frame).get("style")
        if style is not None:
            self.style(style)

    def background(self, background):
        self._background = _apply(
            value=background,
            collection="layers",
            target=self._background,
            default="default-background",
        )

    def foreground(self, foreground):
        self._foreground = _apply(
            value=foreground,
            collection="layers",
            target=self._foreground,
            default="default-foreground",
        )

    def projection(self, projection):
        self._projection = _apply(
            value=projection, collection="projections", target=self._projection
        )

    def style(self, style):
        if len(self._layers) > 0:
            last_layer = self._layers[-1]
            last_layer.style(
                _apply(value=style, target=last_layer, collection="styles")
            )
        else:
            raise Exception("No current data layer: cannot set style '%r'" % (style,))

    def apply_options(self, options):
        if options.provided("style"):
            self.style(options["style"])

        if options.provided("bounding_box"):
            bbox = options["bounding_box"]
            if isinstance(bbox, (list, tuple)):
                self.bounding_box(
                    north=bbox[0], west=bbox[1], south=bbox[2], east=bbox[3]
                )
            else:
                self.bounding_box(
                    north=bbox.north, west=bbox.west, south=bbox.south, east=bbox.east
                )

    def option(self, name, default=None):
        return self._options(name, default)

    def show(self):

        self.apply_options(self._options)

        if self._options.provided("background"):
            self.background(self._options["background"])

        if self._options.provided("foreground"):
            self.foreground(self._options["foreground"])

        if self._options.provided("projection"):
            self.projection(self._options["projection"])

        if self._options("grid", False):
            self._grid = mcoast(map_grid=True, map_coastline=False)

        if self._options("borders", False):
            self._borders = mcoast(
                map_boundaries=True,
                map_grid=False,
                map_coastline=False,
                map_label=False,
            )

        if self._options("rivers", False):
            self._rivers = mcoast(
                map_rivers=True, map_grid=False, map_coastline=False, map_label=False
            )

        if self._options("cities", False):
            self._cities = mcoast(
                map_cities=True, map_label=False, map_grid=False, map_coastline=False
            )
        title = self._options("title", None)
        width = self._options("width", 680)
        frame = self._options("frame", False)

        path = self._options(
            "path", self.temporary_file("." + self._options("format", "png"))
        )

        if self._projection is None:
            # TODO: select best projection based on bbox
            self._projection = mmap(subpage_map_projection="cylindrical")

        if self._bounding_box is not None:
            bbox = self._bounding_box.add_margins(self._options("margins", 0))
            self._projection = _apply(
                value={
                    "=subpage_upper_right_longitude": bbox.east,
                    "=subpage_upper_right_latitude": bbox.north,
                    "=subpage_lower_left_latitude": bbox.south,
                    "=subpage_lower_left_longitude": bbox.west,
                },
                target=self._projection,
                action=mmap,
            )

        self._page_ratio = self._projection.page_ratio()

        _title_height_cm = 0
        if title:
            _title_height_cm = 0.7
            if title is True:
                # Automatic title
                self._title = macro.mtext()
            else:
                self._title = macro.mtext(
                    text_lines=[str(title)],
                    # text_justification='center',
                    # text_font_size=0.6,
                    # text_mode="positional",
                    # text_box_x_position=5.00,
                    # text_box_y_position=18.50,
                    # text_colour='charcoal'
                )

        base, fmt = os.path.splitext(path)
        page = output(
            output_formats=[fmt[1:]],
            output_name_first_page_number=False,
            page_x_length=self._width_cm,
            page_y_length=self._height_cm * self._page_ratio,
            super_page_x_length=self._width_cm,
            super_page_y_length=self._height_cm * self._page_ratio + _title_height_cm,
            subpage_x_length=self._width_cm,
            subpage_y_length=self._height_cm * self._page_ratio,
            subpage_x_position=0.0,
            subpage_y_position=0.0,
            output_width=width,
            page_frame=frame,
            page_id_line=False,
            output_name=base,
        )

        # TODO
        self._options("update", False)
        self._options("update_foreground", False)

        self._options.check_unused()

        args = [page] + self.macro()

        try:
            macro.plot(*args)
        except Exception:
            LOG.error("Error executing: %r", args, exc_info=True)
            raise

        if fmt == ".svg":
            Display = SVG  # noqa: N806
        else:
            Display = Image  # noqa: N806

        return Display(path, metadata=dict(width=width))

    def macro(self):
        """[summary]

        :return: A list of plotting directives
        :rtype: list
        """
        m = [self._projection, self._background]
        for r in self._layers:
            r.add_action(m)
        m += [
            self._rivers,
            self._borders,
            self._cities,
            self._foreground,
            self._grid,
            self._legend,
            self._title,
        ]
        return [x for x in m if x is not None]
