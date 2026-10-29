"""Read the image in the system clipboard, for ``sugo clip``.

Pillow's ImageGrab reads the clipboard natively on Windows and macOS; on
Linux it runs ``wl-paste`` (Wayland) or ``xclip`` (X11) with an argument
list, never a shell. The image is re-encoded as PNG so the conversion takes
the same path, and the same limits, as an image file.
"""

from io import BytesIO

from PIL import Image, ImageGrab

from sugo.core.constants import MAX_IMAGE_PIXELS
from sugo.extractors.image.loader import ImageTooLargeError
from sugo.ports.cli.errors import CliError, ExitCode

_PNG_MODES = frozenset({"1", "L", "LA", "P", "RGB", "RGBA", "I;16"})


def read_clipboard_image() -> bytes:
    """Return the clipboard image as PNG bytes.

    Raises:
        CliError: If the clipboard cannot be read or holds no image.
        ImageTooLargeError: If the image has more pixels than Sugo accepts.
    """
    try:
        content = ImageGrab.grabclipboard()
    except Image.DecompressionBombError as error:
        # Pillow decodes the clipboard itself, so its own bomb guard can fire first.
        raise ImageTooLargeError(f"image exceeds {MAX_IMAGE_PIXELS} pixels") from error
    except (OSError, NotImplementedError) as error:
        raise CliError(
            code="CLIPBOARD_UNAVAILABLE",
            message="The clipboard cannot be read.",
            exit_code=ExitCode.ERROR,
            hint="On Linux, install wl-clipboard (Wayland) or xclip (X11).",
        ) from error
    if not isinstance(content, Image.Image):
        # None, or a list of copied files: neither is an image to convert.
        raise CliError(
            code="CLIPBOARD_NO_IMAGE",
            message="The clipboard holds no image.",
            exit_code=ExitCode.ERROR,
            hint="Copy an image or take a screenshot; to convert a file, run: sugo FILE",
        )
    with content:
        # Checked before re-encoding, which would need memory for the whole image.
        if content.width * content.height > MAX_IMAGE_PIXELS:
            raise ImageTooLargeError(f"image exceeds {MAX_IMAGE_PIXELS} pixels")
        # PNG cannot store every mode a clipboard can hold, e.g. CMYK.
        image = content if content.mode in _PNG_MODES else content.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
    return buffer.getvalue()
