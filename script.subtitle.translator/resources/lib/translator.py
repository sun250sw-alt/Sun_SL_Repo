"""
Google Translate — chunked pipeline for large subtitle files.

Pipeline:
  1. Split all lines into SECTIONS (e.g. 200 lines each)
  2. Within each section, pack lines into BATCHES (~4800 chars each)
  3. Translate sections sequentially, batches within each section in parallel
  4. This means progress updates every ~200 lines — never hangs long

Why sections instead of all-at-once parallel:
  - Firing 40+ parallel requests at once triggers Google rate limiting
  - Sequential sections with parallel batches inside = steady throughput
  - Progress callback fires after every section so bar moves smoothly
"""

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import xbmc

URL       = ("https://translate.googleapis.com/translate_a/single"
             "?client=gtx&sl=auto&tl={tl}&dt=t&q={q}")
SEP       = "\n||||\n"
BATCH_LIMIT  = 4500   # max chars per HTTP request
SECTION_SIZE = 150    # lines per section (controls progress granularity)
WORKERS      = 3      # parallel requests per section (low = avoids throttle)
TIMEOUT      = 25     # seconds per HTTP request
MAX_RETRY    = 2      # retries on failure before using original text


def _request(text, lang):
    url = URL.format(tl=lang, q=urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(p[0] for p in data[0] if p[0])


def _retry(text, lang):
    """Translate with retry. Falls back to original text — never raises."""
    for attempt in range(MAX_RETRY):
        try:
            return _request(text, lang)
        except Exception as e:
            if attempt < MAX_RETRY - 1:
                time.sleep(2 ** attempt)
            else:
                xbmc.log("[SubTranslator] gave up on batch: {}".format(e),
                         xbmc.LOGWARNING)
    return text  # fallback


def _make_batches(lines):
    """Pack lines into char-limited batches. Returns list of (start, lines)."""
    batches, batch, start, size = [], [], 0, 0
    for i, line in enumerate(lines):
        n = len(line) + len(SEP)
        if batch and size + n > BATCH_LIMIT:
            batches.append((start, batch))
            batch, start, size = [], i, 0
        batch.append(line)
        size += n
    if batch:
        batches.append((start, batch))
    return batches


def _translate_section(lines, lang):
    """
    Translate a section (list of lines) using parallel batch requests.
    Returns list of translated lines in original order.
    """
    if not lines:
        return lines

    batches = _make_batches(lines)
    out     = list(lines)  # pre-fill with originals

    def do_batch(args):
        start, batch_lines = args
        result = _retry(SEP.join(batch_lines), lang)
        parts  = [p.strip() for p in result.split("||||")]
        while len(parts) < len(batch_lines):
            parts.append("")
        return start, parts[:len(batch_lines)]

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(do_batch, b): b[0] for b in batches}
        for future in as_completed(futures):
            try:
                start, translated = future.result()
                for i, tx in enumerate(translated):
                    if tx.strip():
                        out[start + i] = tx
            except Exception as e:
                xbmc.log("[SubTranslator] batch error: {}".format(e),
                         xbmc.LOGERROR)
    return out


def translate_lines(lines, lang, progress_cb=None):
    """
    Translate all lines by processing SECTION_SIZE lines at a time.
    progress_cb(done_lines, total_lines) called after each section.
    Returns translated lines in original order.
    """
    if not lines:
        return lines

    total   = len(lines)
    out     = list(lines)
    done    = 0

    xbmc.log("[SubTranslator] Starting: {} lines, section={}, workers={}".format(
        total, SECTION_SIZE, WORKERS))

    i = 0
    while i < total:
        section      = lines[i:i + SECTION_SIZE]
        translated   = _translate_section(section, lang)
        out[i:i + len(section)] = translated
        i    += len(section)
        done += len(section)
        if progress_cb:
            progress_cb(done, total)

    return out
