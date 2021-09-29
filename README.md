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
