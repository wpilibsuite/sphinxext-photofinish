import re
import tempfile

# There's a few ways to support avif:
# 1. imagemagick
# 2. pillow with `avif`
# 3. pillow with `pillow_avif`
# 4. pillow with `rav1e`
## Re 1. I haven't tried imagemagick but it has recently added support for avif. It
# supports avif via libheif not libavif. It has to be compiled with a newer
# libheif and a newer libaom so idk how well supported it is yet. I've seen a
# github issue with some users reporting that they were seeing silent failures
# while encoding avif files so I didn't try imagemagick. If desired, we can
# test it out and switch all image conversion from pillow to imagemagick.
# Later: Imagemagick does work.
## Re 2. `avif` requires users to compile their own libavif + libaom and have it
# available on their system so meh.
## Re 3. `pillow_avif` conveniently packages its own libavif and seems to have
# full wheels for a few OSes so I went for this as my first (and only) try.
## Re 4. `rav1e` is not prepackaged and can't be installed on RTD
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

from bs4 import BeautifulSoup, Tag
from docutils.nodes import Node
from docutils.writers.html5_polyglot import HTMLTranslator
from PIL import Image
from PIL.PngImagePlugin import PngImageFile, PngInfo
from sphinx.application import Sphinx
from sphinx.builders.dirhtml import DirectoryHTMLBuilder
from sphinx.builders.html import StandaloneHTMLBuilder
from sphinx.transforms.post_transforms.images import CRITICAL_PATH_CHAR_RE
from sphinx.util import logging, status_iterator
from sphinx.util.osutil import ensuredir

from .svg2png import svg_to_png

READTHEDOCS_BUILDERS = ["readthedocs", "readthedocsdirhtml"]


logger = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True)
class ImgData:
    src_path: Path
    dest_path: Path
    width: int
    height: int


import mimetypes

mimetypes.add_type("image/webp", ".webp")  # not in the mimetypes module by default


def visit_image(
    translator: HTMLTranslator,
    node: Node,
    old_visit_image: Callable[[HTMLTranslator, Node], None],
    app: Sphinx,
    img_datas: Set[ImgData],
):
    """
    Wrap the existing `visit_image`.
    Let the old one generate an img tag using all of its own logic first.
    Then, we yoink that from the body and replace it with one wrapped in
    a picture tag.
    Example:
        Before (existing docutils translator):
            <img src="...", alt="..." />
        After (monkeypatch - this func):
            <picture>
                <source type="...", srcset="...", sizes="..." />
                <source type="...", srcset="...", sizes="..." />
                <img src="...", alt="..." srcset="...", sizes="...", loading="lazy", decoding="async"/>
            </picture>
    We also add support for lazy loading images and asynchronously them.
    """
    old_visit_image(translator, node)

    img_tag_str = translator.body[-1]
    img_uri = node["uri"]
    if "://" in img_uri:
        # Check if image is remote. We could take the check from
        # sphinx-contrib/images - it's more robust
        return
    img_uri_path = Path(img_uri)
    img_ext = img_uri_path.suffix
    if img_ext not in {".png", ".jpg", ".jpeg", ".svg"}:
        return
    img_src_path: Path = Path(app.srcdir) / node["candidates"]["*"]
    imagedir = Path(app.builder.outdir) / app.builder.imagedir
    img_dest_path = imagedir / (
        re.sub(CRITICAL_PATH_CHAR_RE, "_", img_src_path.stem) + img_src_path.suffix
    )
    ensuredir(imagedir)

    soup_img: Tag = BeautifulSoup(img_tag_str, features="html.parser").img
    soup_picture: Tag = BeautifulSoup().new_tag("picture")

    # Move height / width from <img/> to <picture/>. The img tag will hold the actual
    # resolution of the image file and its parent, picture, will hold
    # the desired size constraints.
    if "height" in soup_img.attrs:
        soup_picture.attrs["height"] = soup_img.attrs["height"]
        del soup_img.attrs["height"]

    if "width" in soup_img.attrs:
        soup_picture.attrs["width"] = soup_img.attrs["width"]
        del soup_img.attrs["width"]

    # Lazy + async load by default
    # There is an open docutils feature request
    # (https://sourceforge.net/p/docutils/feature-requests/78/)
    # adding support for lazy loading that will probably target
    # docutils 0.18. lazy loading can probably be removed from
    # here at that point unless we'd like to continue
    # default-enabling it.
    if "loading" not in soup_img.attrs:
        soup_img.attrs["loading"] = "lazy"

    if "decoding" not in soup_img.attrs:
        soup_img.attrs["decoding"] = "async"

    # SVG handling
    # For svgs, we don't care about generating various codecs / resolutions.
    # But, we do care about having accurate lazyloading placeholders to prevent browser layout shift.
    # PIL can't open SVGs. For svgs, we'll do our best to detect the aspect ratio.
    # If that fails, svgs just won't have proper placeholders.
    # svgs skip most of the logic that raster types go through.
    if img_ext == ".svg":
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_img_path = Path(temp_dir) / "temp.png"
            try:
                svg_to_png(img_src_path, temp_img_path)
                with Image.open(temp_img_path) as im:
                    im_width, im_height = im.size
                soup_img.attrs["height"] = im_height
                soup_img.attrs["width"] = im_width
            except Exception as e:
                print(
                    img_src_path,
                    "'s aspect ratio could not be determined. Loading in this image may cause layout shift on page load.",
                )
                print(e)
                # for line in repr(e).split():
                #     print("    " + line)

        soup_picture.append(soup_img)
        translator.body.pop()
        translator.body.append(str(soup_picture))
        return

    with Image.open(img_src_path) as im:
        im_width, im_height = im.size

    # Set image ratio. Browsers need the aspect ratio of the image for
    # non-janky lazyloading. We can either give it the aspect ratio
    # or the height and width. Height and width is better
    # for better legacy support
    soup_img.attrs["height"] = im_height
    soup_img.attrs["width"] = im_width

    # in order of preference. For us, that is order of performance
    dest_exts = [
        # ".avif", excluded due to it only being supported by chrome
        ".webp",
        img_ext,  # png or jpg/jpeg
    ]

    for dest_ext in dest_exts:
        srcset_srcs = []
        width_min = app.config.width_min
        width_max = 2 * app.config.max_viewport_width
        width_step = app.config.width_step
        widths = list(range(width_min, min(width_max, im_width) + 1, width_step))

        if not widths:
            widths = [im_width]

        if im_width - widths[-1] <= width_step / 2:
            widths[-1] = im_width
        else:
            widths.append(im_width)

        for w in widths:
            h = w * im_height // im_width
            # We have to use the basename of the img tag's uri to
            # account for sphinx's handling/mangling of duplicate image
            # filenames.

            if w == im_width:
                # Special case the full size filename to look like the src filename
                new_img_name = f"{img_uri_path.stem}{dest_ext}"
            else:
                new_img_name = f"{img_uri_path.stem}-{w}{dest_ext}"

            # img_dest_path is absolute
            new_dest = img_dest_path.with_name(new_img_name)

            # soup_img.attrs["src"] is relative to the html file being built
            new_uri = Path(soup_img.attrs["src"]).with_name(new_img_name)

            img_datas.add(
                ImgData(src_path=img_src_path, dest_path=new_dest, width=w, height=h)
            )

            srcset_srcs.append(f"{new_uri} {w}w")

        srcset = ", ".join(srcset_srcs)

        # `sizes` should account for `.wy-nav-content`'s padding but it's very
        # theme and frc-docs customization specifc and is different for
        # the desktop and mobile themes. If this is going to be kept
        # frc-docs specific, then we can hardcode it or (preferably)
        # auto-populate from `frc-rtd.css`. Otherwise, using the
        # max viewport width is a good enough (TM) (overestimate) approach.
        # However, we can make this accurate and fully automated for "all"
        # scenarios with some work:
        # 1. Finish the standard html build as is without any monkeypatching
        # 2. Open every webpage in a headless browser instance
        # 3. Iterate over browser width 1-2000 and note the width of each image
        # 4. Use that mapping to generate the sizes attribute.
        # This would be a pretty robust solution since most documentation
        # changes layout based on viewport width and not on whether the
        # browser is reporting as mobile or desktop.
        if "width" in soup_picture.attrs:
            sizes = f"min({soup_picture.attrs['width']}px, 100vw)"
        elif "height" in soup_picture.attrs:
            sizes = f"{soup_picture.attrs['height'] * im_width // im_height}px"
        else:
            sizes = f"min(min({im_width}px, 100vw), {app.config.max_viewport_width}px)"

        if dest_ext == img_ext:
            # don't create a source; just append to the existing img
            soup_img.attrs["srcset"] = srcset
            soup_img.attrs["sizes"] = sizes

            # should be the last child
            soup_picture.append(soup_img)
        else:
            # non default filetypes need a source tag
            soup_source = BeautifulSoup().new_tag("source")
            soup_source.attrs["type"] = mimetypes.types_map[dest_ext]
            soup_source.attrs["srcset"] = srcset
            soup_source.attrs["sizes"] = sizes

            soup_picture.append(soup_source)

    translator.body.pop()
    translator.body.append(str(soup_picture))


# This isn't parallelized. Sphinx has the ability to run all finish tasks in
# parallel. That funcationality is currently commented out. If it's enabled,
# this function should be serial.
def process_images(img_datas: Set[ImgData]):
    for img_data in status_iterator(
        img_datas,
        "generating responsive images... ",
        "blue",
        len(img_datas),
        stringify_func=lambda i: str(i.dest_path.name),
    ):
        process_image(img_data)


# NI stores LABView VI Snippets in a private chunk of type "niVI" within PNG files.
VI_CHUNK_TYPE = bytes("niVI", "utf-8")


def get_vi_snippet_data(image: Image.Image) -> Optional[bytes]:
    # only PNGs officially support NI snippets.
    if not isinstance(image, PngImageFile):
        return None
    image.load()
    for chunk_type, chunk_data, *_ in image.private_chunks:
        if chunk_type == VI_CHUNK_TYPE:
            return chunk_data
    return None


def process_image(img_data: ImgData):
    with Image.open(img_data.src_path) as im:
        params: Dict[str, Any] = {}
        params["optimize"] = True

        src_ext = img_data.src_path.suffix
        dest_ext = img_data.dest_path.suffix

        if dest_ext in {".png", ".jpg", ".jpeg"}:
            params["quality"] = 80
        elif dest_ext == ".webp":
            params["quality"] = 82
        elif dest_ext == ".avif":
            # We can set qmin and qmax separately for better performance.
            # Squoosh defaults to ~48 so so will we
            params["quality"] = 50
            # 0 is slowest and 10 is fastest. Also effects quality
            # pillow_avif defaults to 8. Google recommends 6 as a good balanced default.
            # We use 5 because we're cool like that.
            params["speed"] = 5

        if src_ext == ".png":
            # Upon saving, PIL strips all nonstandard metadata by default.
            # To preserve VI Snippets, we get and reinject them when saving.
            vi_snippet_data = get_vi_snippet_data(im)
            if vi_snippet_data:
                if dest_ext != ".png":
                    return
                pnginfo = PngInfo()
                pnginfo.add(VI_CHUNK_TYPE, vi_snippet_data, after_idat=True)
                params["pnginfo"] = pnginfo

        im.resize((img_data.width, img_data.height), Image.LANCZOS).save(
            str(img_data.dest_path), **params
        )


def builder_init(app: Sphinx):
    if not (
        isinstance(app.builder, (StandaloneHTMLBuilder, DirectoryHTMLBuilder))
        or app.builder.name in READTHEDOCS_BUILDERS
    ):
        return

    # We'll store all the metadata needed to convert images and
    # defer all the work to the build's finish-tasks and let the
    # write phase run faster
    img_datas: Set[ImgData] = set()

    # app.builder.finish_tasks.add_task(process_images, img_datas)

    # Monkey patch wrap whatever the existing `visit_image`
    translator_cls: HTMLTranslator = app.builder.get_translator_class()
    old_visit_image = translator_cls.visit_image

    def new_visit_image(translator: HTMLTranslator, node: Node):
        visit_image(translator, node, old_visit_image, app, img_datas)

    translator_cls.visit_image = new_visit_image

    # Wrap the existing `copy_image_files`. Let the old one copy all the images then generate all the responsive images.
    old_copy_image_files = app.builder.copy_image_files

    def new_copy_image_files(*args):
        old_copy_image_files(*args)
        process_images(img_datas)

    app.builder.copy_image_files = new_copy_image_files


def setup(app: Sphinx) -> Dict[str, Any]:
    app.add_config_value("max_viewport_width", 1000, "html")
    app.add_config_value("width_min", 500, "html")
    app.add_config_value("width_step", 300, "html")
    app.connect("builder-inited", builder_init, 1e99)

    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


# References:
# https://blog.logrocket.com/jank-free-page-loading-with-media-aspect-ratios/
# https://www.stefanjudis.com/snippets/a-picture-element-to-load-correctly-resized-webp-images-in-html/
# https://ericportis.com/posts/2014/srcset-sizes/
# https://css-tricks.com/sometimes-sizes-is-quite-important/
# https://medium.com/@MRWwebDesign/responsive-images-the-sizes-attribute-and-unexpected-image-sizes-882a2eadb6db
# https://developer.mozilla.org/en-US/docs/Web/HTML/Element/picture
# https://developer.mozilla.org/en-US/docs/Web/Media/Formats/Image_types
# https://www.industrialempathy.com/posts/avif-webp-quality-settings/
