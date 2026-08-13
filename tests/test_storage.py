"""Where uploaded pictures go, and what is allowed in.

`sniff` is the security boundary: the browser's Content-Type is a claim, and an
.svg served from our own origin is stored XSS against a logged-in shop owner.
"""
from app.services import storage_service as st

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32


def test_real_images_are_recognised():
    assert st.sniff(PNG) == ("image/png", "png")
    assert st.sniff(JPG) == ("image/jpeg", "jpg")
    assert st.sniff(GIF) == ("image/gif", "gif")
    assert st.sniff(WEBP) == ("image/webp", "webp")


def test_an_svg_is_not_an_image_here():
    """SVG carries script. Served from our origin it runs with the owner's session."""
    assert st.sniff(b'<svg onload="alert(1)">') == ("", "")


def test_html_and_empty_input_are_refused():
    assert st.sniff(b"<!DOCTYPE html><h1>hi</h1>") == ("", "")
    assert st.sniff(b"") == ("", "")


def test_a_remote_url_is_not_a_local_file():
    assert st.local_path("https://cdn.example.com/a.png") is None
    assert st.local_path("") is None
    assert st.local_path(None) is None


def test_path_traversal_is_refused():
    """The value comes from a database row, and a row that ever held this must
    not turn into a file we read and hand to Telegram."""
    assert st.local_path("/static/uploads/../../.env") is None
    assert st.local_path("/static/uploads/../../../etc/passwd") is None


def test_a_missing_file_is_not_a_path():
    assert st.local_path("/static/uploads/tenant-x/img_yoq.png") is None
