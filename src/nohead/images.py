"""Image renditions without a request. Image URLs are open: an image asset's
`image_url` serves the whole image, and imgproxy's open-source processing
options written into it transform it (listed at
https://docs.nohead.io/guides/images#supported-options). Any other, such as
imgproxy Pro's `sa`, `mc` or `co`, would answer 404, so `image_url` refuses it.

    image_url(asset, width=800, height=600, fit="cover", format="webp")
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

_FITS = {"contain": "fit", "cover": "fill", "fill": "force"}

# The processing options image URLs take, by short and long name.
_SUPPORTED = frozenset(
    " ".join(
        (
            "rs resize s size rt resizing_type w width h height mw min-width mh min-height",
            "z zoom dpr el enlarge ex extend exar extend_aspect_ratio g gravity c crop",
            "t trim pd padding ar auto_rotate rot rotate fl flip bg background bl blur",
            "sh sharpen pix pixelate q quality fq format_quality f format ext",
            "kcr keep_copyright scp strip_color_profile ph preserve_hdr",
            "eth enforce_thumbnail cb cachebuster exp expires fn filename",
            "att return_attachment pr preset",
        )
    ).split()
)


def _check_supported(option: str) -> None:
    """Refuses an option image URLs don't take, naming it. The only preset is
    preview_url's."""
    name, _, args = option.partition(":")
    preset = name in ("pr", "preset") and args != "preview"
    if name not in _SUPPORTED or preset:
        raise ValueError(
            f"{option if preset else name} isn't an option Nohead image URLs take "
            "(imgproxy Pro's, such as sa, mc or co, aren't available): "
            "https://docs.nohead.io/guides/images#supported-options"
        )


class _Image(Protocol):
    @property
    def image_url(self) -> str | None: ...


def image_url(
    image: str | _Image | Mapping[str, Any],
    *,
    width: float | None = None,
    height: float | None = None,
    fit: Literal["contain", "cover", "fill"] | None = "contain",
    format: Literal["webp", "avif", "jpeg", "png"] | None = None,
    quality: float | None = None,
    dpr: float | None = None,
    gravity: str | None = None,
    options: Sequence[str] = (),
) -> str:
    """A rendition of an image (an asset, as a model or a mapping, or its
    `image_url`). `fit`: `contain` (the default, also for None) fits inside the box,
    `cover` fills it, cropping, `fill` stretches to it.
    `gravity` is what a crop keeps (`sm` for smart, `fp:0.5:0.3` for a focal
    point); `options` are any other processing options, as written in a URL
    (`["bl:2"]`): imgproxy's open-source ones (Pro's are refused)."""
    if isinstance(image, str):
        base: object = image
    elif isinstance(image, Mapping):
        base = image.get("image_url")
    else:
        base = image.image_url
    if not base or not isinstance(base, str):
        raise ValueError("Not a ready image: it has no image_url")
    at = base.find("/plain/")
    if at < 0:
        raise ValueError(f"Not a Nohead image URL: {base}")

    for option in [gravity, *options]:
        if option and re.search(r"[/@?#]", option):
            raise ValueError(f"Not an imgproxy option: {option}")
    for option in options:
        if option:
            _check_supported(option)

    if fit is None:
        fit = "contain"
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
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
