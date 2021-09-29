# sphinxext-photofinish

Photofinish is a sphinx extension for creating [responsive](https://developer.mozilla.org/en-US/docs/Learn/HTML/Multimedia_and_embedding/Responsive_images) images to your Sphinx site. This has several benefits:

- Lower bandwidth cost for browsers and devices that don't need the higher resolution version
- Higher resolution images for higher resolution devices

Photofinish can dramatically increase the loading time of your Sphinx website.

## Installation

`python -m pip install sphinxext-photofinish`

## Usage
Just add `sphinxext-photofinish` to your extensions list in your `conf.py`

```python
extensions = [
    "sphinxext.photofinish",
]
```

## Configuration

Photofinish adds several `conf.py` options that you can optionally configure:

`max_viewport_width` - This is maximum "viewable" size of images in your documentation. Typically, it's set to the width of your body. Responsive images are generated up to double of this value. Default is 1000.

`width_min` - Minimum width of images to generate. Default is 500.

`width_step` - The resolution to iterate over for generating images. EX: 500, 800, 1100. Default is 300.
