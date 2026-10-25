import pytest

from nohead.images import image_url

BASE = (
    "https://images.nohead.io/plain/0199f5c2-7b1e-7c3a-9d4f-2a6b8c0e1f3d"
    "/0199f5c2-8a2d-7e4b-b1c3-5d7e9f1a2b4c"
)


def at(options: str) -> str:
    return BASE.replace("/plain/", f"/{options}/plain/")


class Asset:
    def __init__(self, url: str | None) -> None:
        self.image_url = url


def test_writes_the_options_before_the_source_and_the_format_after_it() -> None:
    url = image_url(
        BASE,
        width=800,
        height=600,
        fit="cover",
        gravity="sm",
        dpr=2,
        quality=80,
        format="webp",
        options=["bl:2"],
    )
    assert url == at("rs:fill:800:600/g:sm/dpr:2/q:80/bl:2") + "@webp"
    assert image_url(Asset(BASE), width=320) == at("rs:fit:320:0")
    assert image_url(BASE) == BASE
    assert image_url(BASE + "@png", format="avif") == BASE + "@avif"


def test_writes_numbers_as_the_other_sdks_do() -> None:
    url = image_url(BASE, width=800.0, height=600.0, dpr=2.0, quality=80.0)
    assert url == at("rs:fit:800:600/dpr:2/q:80")
    assert image_url(BASE, width=400, dpr=1.5) == at("rs:fit:400:0/dpr:1.5")
    assert image_url(BASE, width=400, dpr=1.2345678) == at("rs:fit:400:0/dpr:1.2345678")
    assert image_url(BASE, width=400, dpr=0, quality=0) == at("rs:fit:400:0")
    assert image_url(BASE, width=0.0, height=300, dpr=0.0, quality=0.0) == at("rs:fit:0:300")


def test_refuses_options_that_would_break_the_path() -> None:
    with pytest.raises(ValueError, match="Not an imgproxy option"):
        image_url(BASE, gravity="fp:0.5/0.3")
    with pytest.raises(ValueError, match="Not an imgproxy option"):
        image_url(BASE, options=["bl:2@x"])
    with pytest.raises(ValueError, match="fit must be one of"):
        image_url(BASE, width=300, fit="crop")  # pyright: ignore[reportArgumentType]


def test_refuses_what_is_not_a_ready_images_url() -> None:
    with pytest.raises(ValueError, match="no image_url"):
        image_url(Asset(None))
    with pytest.raises(ValueError, match="Not a Nohead image URL"):
        image_url("https://example.com/cat.png")
