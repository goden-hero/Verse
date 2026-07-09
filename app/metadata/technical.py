"""Technical metadata extractor using ffprobe to parse audio properties."""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("music_rec.metadata.technical")


@dataclass
class TechnicalMetadataInfo:
    """Dataclass representing extracted audio technical properties from ffprobe."""

    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    bit_depth: int | None = None
    format: str | None = None


def extract_technical_metadata(file: Path) -> TechnicalMetadataInfo:
    """Extracts technical metadata from an audio file using ffprobe.

    Calls ffprobe in a subprocess to retrieve the codec, bitrate, sample rate,
    channels, bit depth, and format.

    Args:
        file: Path to the audio file.

    Returns:
        TechnicalMetadataInfo dataclass containing the parsed attributes.
    """
    info = TechnicalMetadataInfo()
    resolved_path = Path(file).resolve()

    if not resolved_path.exists() or not resolved_path.is_file():
        logger.warning("File does not exist or is not a file: %s", file)
        return info

    # Command to run ffprobe, selecting only the first audio stream
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,sample_rate,channels,bits_per_raw_sample,bits_per_sample",
        "-show_entries",
        "format=bit_rate,format_name",
        "-of",
        "json",
        str(resolved_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,  # 5-second timeout to handle corrupt files
            check=True,
        )
        data = json.loads(result.stdout)

        # Parse stream-specific information
        streams = data.get("streams", [])
        if streams:
            stream = streams[0]
            info.codec = stream.get("codec_name")

            # Sample Rate
            sr = stream.get("sample_rate")
            if sr is not None:
                try:
                    info.sample_rate = int(sr)
                except ValueError:
                    pass

            # Channels
            ch = stream.get("channels")
            if ch is not None:
                try:
                    info.channels = int(ch)
                except ValueError:
                    pass

            # Bit depth (only valid for lossless files, skip if 0)
            bd = stream.get("bits_per_raw_sample") or stream.get("bits_per_sample")
            if bd is not None:
                try:
                    val = int(bd)
                    if val > 0:
                        info.bit_depth = val
                except ValueError:
                    pass

        # Parse format-specific information
        fmt_info = data.get("format", {})
        if fmt_info:
            info.format = fmt_info.get("format_name")

            # Bitrate
            br = fmt_info.get("bit_rate")
            if br is not None:
                try:
                    info.bitrate = int(br)
                except ValueError:
                    pass

    except subprocess.TimeoutExpired:
        logger.error("ffprobe timed out while analyzing file: %s", resolved_path)
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        logger.warning("ffprobe analysis failed for %s: %s", resolved_path, e)

    return info
