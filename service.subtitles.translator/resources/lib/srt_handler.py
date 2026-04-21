import os
import re

TAG_RE  = re.compile(r"<[^>]+>")
TIME_RE = re.compile(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})")


def _encoding(path):
    """Detect encoding by reading only the first 4 bytes (BOM check) then 512 bytes."""
    try:
        with open(path, "rb") as f:
            bom = f.read(4)
        if bom[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        if bom[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return "utf-16"
        # Try utf-8 on first 512 bytes
        with open(path, "rb") as f:
            sample = f.read(512)
        sample.decode("utf-8")
        return "utf-8"
    except Exception:
        return "latin-1"


def parse_srt(path):
    """
    Line-by-line SRT parser — never loads the whole file into memory at once.
    Works on files of any size without regex on the full text.
    """
    enc    = _encoding(path)
    blocks = []

    idx   = None
    start = None
    end   = None
    text_lines = []

    def _flush():
        if idx is not None and start is not None:
            raw = " ".join(text_lines).strip()
            if raw:
                blocks.append({
                    "index":      idx,
                    "start":      start,
                    "end":        end,
                    "raw_text":   raw,
                    "clean_text": TAG_RE.sub("", raw).strip(),
                })

    with open(path, encoding=enc, errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")

            # Skip BOM if present at start
            if line.startswith("\ufeff"):
                line = line[1:]

            # Blank line = end of block
            if line.strip() == "":
                _flush()
                idx, start, end, text_lines = None, None, None, []
                continue

            # Timecode line
            m = TIME_RE.search(line)
            if m and idx is not None and start is None:
                start = m.group(1).replace(".", ",")
                end   = m.group(2).replace(".", ",")
                continue

            # Index line (pure integer)
            if line.strip().isdigit() and start is None:
                # flush previous block if any
                _flush()
                idx, start, end, text_lines = int(line.strip()), None, None, []
                continue

            # Text line
            if idx is not None and start is not None:
                text_lines.append(line)

    # Flush last block
    _flush()
    return blocks


def write_srt(blocks, path):
    """Write blocks to UTF-8 with BOM — maximally compatible with media players."""
    with open(path, "w", encoding="utf-8-sig") as f:
        for b in blocks:
            f.write("{}\n".format(b["index"]))
            f.write("{} --> {}\n".format(b["start"], b["end"]))
            f.write("{}\n".format(b["raw_text"]))
            f.write("\n")


def translated_path(src, suffix, lang):
    base, ext = os.path.splitext(src)
    return "{}{}_{}{}" .format(base, suffix, lang, ext)


def time_to_ms(t):
    """Convert SRT timecode HH:MM:SS,mmm to milliseconds."""
    t = t.replace(".", ",")
    h, m, rest = t.split(":")
    s, ms = rest.split(",")
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


def ms_to_time(ms):
    """Convert milliseconds to SRT timecode HH:MM:SS,mmm. Clamps to 0."""
    ms = max(0, int(ms))
    h   = ms // 3600000
    ms -= h * 3600000
    m   = ms // 60000
    ms -= m * 60000
    s   = ms // 1000
    ms -= s * 1000
    return "{:02d}:{:02d}:{:02d},{:03d}".format(h, m, s, ms)


def shift_blocks(blocks, offset_ms):
    """
    Return new list of blocks with all timecodes shifted by offset_ms.
    Blocks that would start before 0:00:00 are clamped — never dropped.
    offset_ms can be negative (shift earlier) or positive (shift later).
    """
    shifted = []
    for b in blocks:
        new_start = time_to_ms(b["start"]) + offset_ms
        new_end   = time_to_ms(b["end"])   + offset_ms
        shifted.append({
            **b,
            "start": ms_to_time(new_start),
            "end":   ms_to_time(new_end),
        })
    return shifted
