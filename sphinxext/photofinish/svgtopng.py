import gc
import subprocess
import sys
import traceback
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import List, Optional, Union


class NoToolError(RuntimeError):
    pass


class FailedConversionError(RuntimeError):
    pass


# code from https://utcc.utoronto.ca/~cks/space/blog/python/GetAllObjects
# Changes:
# - nest `_getr`
# - Swap dict for set
# - Make function a generator
def _all_python_objects():
    """Return a list of all live Python
    objects, not including the list itself."""

    # Recursively expand slist's objects
    # into olist, using seen to track
    # already processed objects.
    def _getr(slist, seen):
        for e in slist:
            if id(e) in seen:
                continue
            seen.add(id(e))
            yield e
            tl = gc.get_referents(e)
            if tl:
                yield from _getr(tl, seen)

    gcl = gc.get_objects()
    seen = set()
    # Just in case:
    seen.add(id(gcl))
    seen.add(id(seen))
    # _getr does the real work.
    yield from _getr(gcl, seen)


def get_sphinx() -> Optional["Sphinx"]:
    with suppress(Exception):
        if "sphinx" in sys.modules or any("sphinx" in arg for arg in sys.argv):
            # This code is probably in a sphinx build
            from sphinx.application import Sphinx

            for obj in _all_python_objects():
                if isinstance(obj, Sphinx):
                    return obj
    return None


SPHINX_INKSCAPE_CONVERTER_BIN = None
SPHINX_RSVG_CONVERTER_BIN = None
SPHINX_FOUND = False


def svg_to_png(
    svg_path: Union[str, Path],
    out_path: Union[str, Path],
    width: Optional[int] = None,
    height: Optional[int] = None,
    *,
    inkscape_path: Optional[Union[str, Path]] = None,
    rsvg_convert_path: Optional[Union[str, Path]] = None,
    imagemagick_path: Optional[Union[str, Path]] = None,
    svgexport_path: Optional[Union[str, Path]] = None,
):
    """
    Converts an svg to a png.
    This function makes many attempts to convert successfully.
    Order of trials:
    - User specified Inkscape
    - User specified rsvg-convert
    - User specified svgexport
    - User specified imagemagick
    - cairosvg
    - svglib
    - System Inkscape
    - System rsvg-convert
    - System rsvg
    - System svgexport
    - System imagemagick (magick) - v7
    - System imagemagick (convert) - v6
    - Sphinx config specified Inkscape (if in a sphinx build)
    - Sphinx config specified rsvg-convert (if in a sphinx build)
    """

    global SPHINX_INKSCAPE_CONVERTER_BIN
    global SPHINX_RSVG_CONVERTER_BIN
    global SPHINX_FOUND

    svg_path = str(svg_path)
    out_path = str(out_path)

    if inkscape_path is not None:
        inkscape_path = str(inkscape_path)
    if rsvg_convert_path is not None:
        rsvg_convert_path = str(rsvg_convert_path)
    if imagemagick_path is not None:
        imagemagick_path = str(imagemagick_path)
    if svgexport_path is not None:
        svgexport_path = str(svgexport_path)

    if width is None and height is None:
        width = 1000

    inkscape_args = [
        "--export-background-opacity=0",
        "--export-type=png",
        f"--export-filename={out_path}",
        str(svg_path),
    ]
    if width:
        inkscape_args += [f"--export-width={width}"]
    if height:
        inkscape_args += [f"--export-height={height}"]

    rsvg_convert_args = [svg_path, "-o", out_path]
    if width:
        rsvg_convert_args += [f"--width={width}"]
    if height:
        rsvg_convert_args += [f"--height={height}"]

    imagemagick_args = [
        svg_path,
        "-background",
        "none",
        out_path,
    ]  # v7 compatible?
    resize_arg = "-resize "
    if width:
        resize_arg += str(width)
    if height:
        resize_arg += "x"
        resize_arg += str(height)
    imagemagick_args += resize_arg.split()

    svgexport_args = [svg_path, out_path]
    size_arg = ""
    if width:
        size_arg += str(width)
    size_arg += ":"
    if height:
        size_arg += str(height)
    svgexport_args += [size_arg]

    log = []

    @dataclass
    class NotSet(Exception):
        name: str = ""

    @dataclass
    class NotFound(Exception):
        name: str = ""
        path: str = ""

    class manage:
        a_command_exists = False

        def __init__(self, title):
            self.title = title

        def __enter__(self):
            pass

        def __exit__(self, exc, val, trb) -> bool:
            # print(exc, val, traceback)
            if exc == NotSet:
                log.append(f"    - {self.title}: {val.name} not set")
            elif exc == NotFound:
                log.append(f"    - {self.title}: {val.name} not found")
                log.append(f"        for path {val.path}")
            elif isinstance(val, ImportError):
                log.append(f"    - {self.title}: dependency not installed")
                log.append(f"        {val}")
            else:
                manage.a_command_exists = True
                if exc:
                    log.append(f"    - {self.title}: conversion failed")
                    log.append(f"        {val}")
                    # for line in traceback.format_exception(exc, val, trb):
                    # log.append("    " + line)

            return True

    with manage("Inkscape"):
        # User specified inkscape
        if not inkscape_path:
            raise NotSet("inkscape_path")
        if not which(inkscape_path):
            raise NotFound("inkscape_path", inkscape_path)
        subprocess.run([inkscape_path, *inkscape_args], check=True)
        return

    with manage("rsvg-convert"):
        # User specified rsvg-convert
        if not rsvg_convert_path:
            raise NotSet("rsvg_convert_path")
        if not which(rsvg_convert_path):
            raise NotFound("rsvg_convert_path", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("svgexport"):
        # User specified svgexport
        if not svgexport_path:
            raise NotSet("svgexport_path")
        if not which(svgexport_path):
            raise NotFound("svgexport_path", svgexport_path)
        subprocess.run([svgexport_path, *svgexport_args], check=True)
        return

    with manage("imagemagick"):
        # User specified imagemagick
        # This will be to `magick` or to `convert` so will be v7 or v6 behavior, respectively
        if not imagemagick_path:
            raise NotSet("imagemagick_path")
        if not which(imagemagick_path):
            raise NotFound("imagemagick_path", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    with manage("cairosvg"):
        # CairoSVG
        import cairosvg

        with open(svg_path) as f:
            cairosvg.svg2png(
                file_obj=f,
                write_to=out_path,
                output_width=width,
                output_height=height,
            )
            return

    with manage("svglib"):
        # svglib + reportlab
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        rlg = svg2rlg(svg_path)
        renderPM.drawToFile(rlg, out_path, fmt="PNG")
        return

    with manage("Inkscape"):
        # system inkscape
        inkscape_path = "inkscape"
        if not which(inkscape_path):
            raise NotFound("inkscape", inkscape_path)
        subprocess.run([inkscape_path, *inkscape_args], check=True)
        return

    with manage("rsvg-convert"):
        # system rsvg-convert
        rsvg_convert_path = "rsvg-convert"
        if not which(rsvg_convert_path):
            raise NotFound("rsvg-convert", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("rsvg-convert"):
        # system rsvg-convert - older versions?
        rsvg_convert_path = "rsvg"
        if not which(rsvg_convert_path):
            raise NotFound("rsvg-convert", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("svgexport"):
        # system svgexport
        svgexport_path = "svgexport"
        if not which(svgexport_path):
            raise NotFound("svgexport", svgexport_path)
        subprocess.run([svgexport_path, *svgexport_args], check=True)
        return

    with manage("imagemagick"):
        # system imagemagick v7
        imagemagick_path = "magick"
        if not which(imagemagick_path):
            raise NotFound("imagemagick", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    with manage("imagemagick"):
        # system imagemagick v7
        imagemagick_path = "convert"
        if not which(imagemagick_path):
            raise NotFound("imagemagick", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    # Sphinx configuration detection
    if not (SPHINX_FOUND):
        sphinx_app = get_sphinx()
        if sphinx_app:
            SPHINX_INKSCAPE_CONVERTER_BIN = sphinx_app.config.__dict__.get(
                "inkscape_converter_bin", None
            )
            SPHINX_RSVG_CONVERTER_BIN = sphinx_app.config.__dict__.get(
                "rsvg_converter_bin", None
            )
            SPHINX_FOUND = True
    if SPHINX_FOUND:
        with manage("Inkscape"):
            if not SPHINX_INKSCAPE_CONVERTER_BIN:
                raise NotSet("inkscape_converter_bin in Sphinx's conf.py")
            if not which(SPHINX_INKSCAPE_CONVERTER_BIN):
                raise NotFound("inkscape_converter_bin", SPHINX_INKSCAPE_CONVERTER_BIN)
            subprocess.run([SPHINX_INKSCAPE_CONVERTER_BIN, *inkscape_args], check=True)
            return

        with manage("rsvg-convert"):
            if not SPHINX_RSVG_CONVERTER_BIN:
                raise NotSet("rsvg_converter_bin in Sphinx's conf.py")
            if not which(SPHINX_RSVG_CONVERTER_BIN):
                raise NotFound("rsvg_converter_bin", SPHINX_RSVG_CONVERTER_BIN)
            subprocess.run([SPHINX_RSVG_CONVERTER_BIN, *rsvg_convert_args], check=True)
            return

    err_msg = ["\nFailed to convert svg to png."]

    if not manage.a_command_exists:
        err_msg.append(
            "No conversion tool was found. Please install one of: cairosvg, svglib, inkscape, rsvg-convert, svgexport, or imagemagick. If you have one of these installed, they may not be on your path. Pass your installed tool's path into this function."
        )
        raise NoToolError("\n".join(err_msg))

    raise FailedConversionError("\n".join(err_msg + log))


import gc
import subprocess
import sys
import traceback
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import List, Optional, Union


class NoToolError(RuntimeError):
    pass


class FailedConversionError(RuntimeError):
    pass


# code from https://utcc.utoronto.ca/~cks/space/blog/python/GetAllObjects
# Changes:
# - nest `_getr`
# - Swap dict for set
# - Make function a generator
def _all_python_objects():
    """Return a list of all live Python
    objects, not including the list itself."""

    # Recursively expand slist's objects
    # into olist, using seen to track
    # already processed objects.
    def _getr(slist, seen):
        for e in slist:
            if id(e) in seen:
                continue
            seen.add(id(e))
            yield e
            tl = gc.get_referents(e)
            if tl:
                yield from _getr(tl, seen)

    gcl = gc.get_objects()
    seen = set()
    # Just in case:
    seen.add(id(gcl))
    seen.add(id(seen))
    # _getr does the real work.
    yield from _getr(gcl, seen)


def get_sphinx() -> Optional["Sphinx"]:
    with suppress(Exception):
        if "sphinx" in sys.modules or any("sphinx" in arg for arg in sys.argv):
            # This code is probably in a sphinx build
            from sphinx.application import Sphinx

            for obj in _all_python_objects():
                if isinstance(obj, Sphinx):
                    return obj
    return None


SPHINX_INKSCAPE_CONVERTER_BIN = None
SPHINX_RSVG_CONVERTER_BIN = None
SPHINX_FOUND = False


def svg_to_png(
    svg_path: Union[str, Path],
    out_path: Union[str, Path],
    width: Optional[int] = None,
    height: Optional[int] = None,
    *,
    inkscape_path: Optional[Union[str, Path]] = None,
    rsvg_convert_path: Optional[Union[str, Path]] = None,
    imagemagick_path: Optional[Union[str, Path]] = None,
    svgexport_path: Optional[Union[str, Path]] = None,
):
    """
    Converts an svg to a png.
    This function makes many attempts to convert successfully.
    Order of trials:
    - User specified Inkscape
    - User specified rsvg-convert
    - User specified svgexport
    - User specified imagemagick
    - cairosvg
    - svglib
    - System Inkscape
    - System rsvg-convert
    - System rsvg
    - System svgexport
    - System imagemagick (magick) - v7
    - System imagemagick (convert) - v6
    - Sphinx config specified Inkscape (if in a sphinx build)
    - Sphinx config specified rsvg-convert (if in a sphinx build)
    """

    global SPHINX_INKSCAPE_CONVERTER_BIN
    global SPHINX_RSVG_CONVERTER_BIN
    global SPHINX_FOUND

    svg_path = str(svg_path)
    out_path = str(out_path)

    if inkscape_path is not None:
        inkscape_path = str(inkscape_path)
    if rsvg_convert_path is not None:
        rsvg_convert_path = str(rsvg_convert_path)
    if imagemagick_path is not None:
        imagemagick_path = str(imagemagick_path)
    if svgexport_path is not None:
        svgexport_path = str(svgexport_path)

    if width is None and height is None:
        width = 1000

    inkscape_args = [
        "--export-background-opacity=0",
        "--export-type=png",
        f"--export-filename={out_path}",
        str(svg_path),
    ]
    if width:
        inkscape_args += [f"--export-width={width}"]
    if height:
        inkscape_args += [f"--export-height={height}"]

    rsvg_convert_args = [svg_path, "-o", out_path]
    if width:
        rsvg_convert_args += [f"--width={width}"]
    if height:
        rsvg_convert_args += [f"--height={height}"]

    imagemagick_args = [
        svg_path,
        "-background",
        "none",
        out_path,
    ]  # v7 compatible?
    resize_arg = "-resize "
    if width:
        resize_arg += str(width)
    if height:
        resize_arg += "x"
        resize_arg += str(height)
    imagemagick_args += resize_arg.split()

    svgexport_args = [svg_path, out_path]
    size_arg = ""
    if width:
        size_arg += str(width)
    size_arg += ":"
    if height:
        size_arg += str(height)
    svgexport_args += [size_arg]

    log = []

    @dataclass
    class NotSet(Exception):
        name: str = ""

    @dataclass
    class NotFound(Exception):
        name: str = ""
        path: str = ""

    class manage:
        a_command_exists = False

        def __init__(self, title):
            self.title = title

        def __enter__(self):
            pass

        def __exit__(self, exc, val, trb) -> bool:
            # print(exc, val, traceback)
            if exc == NotSet:
                log.append(f"    - {self.title}: {val.name} not set")
            elif exc == NotFound:
                log.append(f"    - {self.title}: {val.name} not found")
                log.append(f"        for path {val.path}")
            elif isinstance(val, ImportError):
                log.append(f"    - {self.title}: dependency not installed")
                log.append(f"        {val}")
            else:
                manage.a_command_exists = True
                if exc:
                    log.append(f"    - {self.title}: conversion failed")
                    log.append(f"        {val}")
                    # for line in traceback.format_exception(exc, val, trb):
                    # log.append("    " + line)

            return True

    with manage("Inkscape"):
        # User specified inkscape
        if not inkscape_path:
            raise NotSet("inkscape_path")
        if not which(inkscape_path):
            raise NotFound("inkscape_path", inkscape_path)
        subprocess.run([inkscape_path, *inkscape_args], check=True)
        return

    with manage("rsvg-convert"):
        # User specified rsvg-convert
        if not rsvg_convert_path:
            raise NotSet("rsvg_convert_path")
        if not which(rsvg_convert_path):
            raise NotFound("rsvg_convert_path", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("svgexport"):
        # User specified svgexport
        if not svgexport_path:
            raise NotSet("svgexport_path")
        if not which(svgexport_path):
            raise NotFound("svgexport_path", svgexport_path)
        subprocess.run([svgexport_path, *svgexport_args], check=True)
        return

    with manage("imagemagick"):
        # User specified imagemagick
        # This will be to `magick` or to `convert` so will be v7 or v6 behavior, respectively
        if not imagemagick_path:
            raise NotSet("imagemagick_path")
        if not which(imagemagick_path):
            raise NotFound("imagemagick_path", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    with manage("cairosvg"):
        # CairoSVG
        import cairosvg

        with open(svg_path) as f:
            cairosvg.svg2png(
                file_obj=f,
                write_to=out_path,
                output_width=width,
                output_height=height,
            )
            return

    with manage("svglib"):
        # svglib + reportlab
        from reportlab.graphics import renderPM
        from svglib.svglib import svg2rlg

        rlg = svg2rlg(svg_path)
        renderPM.drawToFile(rlg, out_path, fmt="PNG")
        return

    with manage("Inkscape"):
        # system inkscape
        inkscape_path = "inkscape"
        if not which(inkscape_path):
            raise NotFound("inkscape", inkscape_path)
        subprocess.run([inkscape_path, *inkscape_args], check=True)
        return

    with manage("rsvg-convert"):
        # system rsvg-convert
        rsvg_convert_path = "rsvg-convert"
        if not which(rsvg_convert_path):
            raise NotFound("rsvg-convert", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("rsvg-convert"):
        # system rsvg-convert - older versions?
        rsvg_convert_path = "rsvg"
        if not which(rsvg_convert_path):
            raise NotFound("rsvg-convert", rsvg_convert_path)
        subprocess.run([rsvg_convert_path, *rsvg_convert_args], check=True)
        return

    with manage("svgexport"):
        # system svgexport
        svgexport_path = "svgexport"
        if not which(svgexport_path):
            raise NotFound("svgexport", svgexport_path)
        subprocess.run([svgexport_path, *svgexport_args], check=True)
        return

    with manage("imagemagick"):
        # system imagemagick v7
        imagemagick_path = "magick"
        if not which(imagemagick_path):
            raise NotFound("imagemagick", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    with manage("imagemagick"):
        # system imagemagick v7
        imagemagick_path = "convert"
        if not which(imagemagick_path):
            raise NotFound("imagemagick", imagemagick_path)
        subprocess.run([imagemagick_path, *imagemagick_args], check=True)
        return

    # Sphinx configuration detection
    if not (SPHINX_FOUND):
        sphinx_app = get_sphinx()
        if sphinx_app:
            SPHINX_INKSCAPE_CONVERTER_BIN = sphinx_app.config.__dict__.get(
                "inkscape_converter_bin", None
            )
            SPHINX_RSVG_CONVERTER_BIN = sphinx_app.config.__dict__.get(
                "rsvg_converter_bin", None
            )
            SPHINX_FOUND = True
    if SPHINX_FOUND:
        with manage("Inkscape"):
            if not SPHINX_INKSCAPE_CONVERTER_BIN:
                raise NotSet("inkscape_converter_bin in Sphinx's conf.py")
            if not which(SPHINX_INKSCAPE_CONVERTER_BIN):
                raise NotFound("inkscape_converter_bin", SPHINX_INKSCAPE_CONVERTER_BIN)
            subprocess.run([SPHINX_INKSCAPE_CONVERTER_BIN, *inkscape_args], check=True)
            return

        with manage("rsvg-convert"):
            if not SPHINX_RSVG_CONVERTER_BIN:
                raise NotSet("rsvg_converter_bin in Sphinx's conf.py")
            if not which(SPHINX_RSVG_CONVERTER_BIN):
                raise NotFound("rsvg_converter_bin", SPHINX_RSVG_CONVERTER_BIN)
            subprocess.run([SPHINX_RSVG_CONVERTER_BIN, *rsvg_convert_args], check=True)
            return

    err_msg = ["\nFailed to convert svg to png."]

    if not manage.a_command_exists:
        err_msg.append(
            "No conversion tool was found. Please install one of: cairosvg, svglib, inkscape, rsvg-convert, svgexport, or imagemagick. If you have one of these installed, they may not be on your path. Pass your installed tool's path into this function."
        )
        raise NoToolError("\n".join(err_msg))

    raise FailedConversionError("\n".join(err_msg + log))
