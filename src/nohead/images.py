"""Image renditions without a request. Image URLs are open: an image asset's
`image_url` serves the whole image, and any of imgproxy's processing options
written into it transform it (https://docs.imgproxy.net/usage/processing).

    image_url(asset, width=800, height=600, fit="cover", format="webp")
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal, Protocol

_FITS = {"contain": "fit", "cover": "fill", "fill": "force"}


class _Image(Protocol):
    @property
    def image_url(self) -> str | None: ...


def image_url(
    image: str | _Image,
    *,
    width: float | None = None,
    height: float | None = None,
    fit: Literal["contain", "cover", "fill"] = "contain",
    format: Literal["webp", "avif", "jpeg", "png"] | None = None,
    quality: float | None = None,
    dpr: float | None = None,
    gravity: str | None = None,
    options: Sequence[str] = (),
) -> str:
    """A rendition of an image (an asset, or its `image_url`). `fit`: `contain`
    fits inside the box, `cover` fills it, cropping, `fill` stretches to it.
    `gravity` is what a crop keeps (`sm` for smart, `fp:0.5:0.3` for a focal
    point); `options` are any other processing options, as written in a URL
    (`["bl:2"]`)."""
    base = image if isinstance(image, str) else image.image_url
    if not base:
        raise ValueError("Not a ready image: it has no image_url")
    at = base.find("/plain/")
    if at < 0:
        raise ValueError(f"Not a Nohead image URL: {base}")

    for option in [gravity, *options]:
        if option and re.search(r"[/@?#]", option):
            raise ValueError(f"Not an imgproxy option: {option}")

    if fit not in _FITS:
        raise ValueError(f"fit must be one of {', '.join(_FITS)}")

    segments: list[str] = []
    if width or height:
        segments.append(f"rs:{_FITS[fit]}:{_number(width or 0)}:{_number(height or 0)}")
    if gravity:
        segments.append(f"g:{gravity}")
    if dpr:
        segments.append(f"dpr:{_number(dpr)}")
    if quality:
        segments.append(f"q:{_number(quality)}")
    segments.extend(options)

    # The source comes last; a format replaces any the URL already names.
    source = base[at:]
    if format:
        source = f"{re.sub(r'@[a-z]+$', '', source)}@{format}"
    return base[:at] + "".join(f"/{segment}" for segment in segments) + source


def _number(value: float) -> str:
    """A number as the other SDKs write it: a whole one without `.0` (2.0 is 2), any
    other in full (1.2345678, not rounded)."""
    return str(int(value)) if isinstance(value, float) and value.is_integer() else repr(value)
