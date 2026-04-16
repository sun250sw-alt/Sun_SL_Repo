"""
Translator — Gemini AI (primary) with Google Translate fallback.

If a Gemini API key is provided:
  - Uses Gemini 2.0 Flash with a subtitle-aware system prompt
  - Context-aware, natural dialogue, story flow preserved
  - Falls back to Google Translate on any error or rate limit

If no Gemini key:
  - Uses Google Translate directly (free, no key)
"""

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import xbmc

# ── Google Translate constants ─────────────────────────────────────────────────
GOOGLE_URL   = ("https://translate.googleapis.com/translate_a/single"
                "?client=gtx&sl=auto&tl={tl}&dt=t&q={q}")
SEP          = "\n||||\n"
BATCH_LIMIT  = 4500
SECTION_SIZE = 150
WORKERS      = 3
TIMEOUT      = 25
MAX_RETRY    = 2

# ── Gemini constants ───────────────────────────────────────────────────────────
GEMINI_URL   = ("https://generativelanguage.googleapis.com/v1beta/models/"
                "{model}:generateContent?key={key}")
GEMINI_BATCH = 80   # lines per Gemini request (context window friendly)


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log("[SubTranslator] {}".format(msg), level)


# ── Gemini translation ─────────────────────────────────────────────────────────

def _gemini_translate_batch(lines, lang, api_key, model="gemini-2.5-flash"):
    """
    Send a batch of subtitle lines to Gemini with a subtitle-aware prompt.
    Returns list of translated lines, or raises on error.
    """
    numbered = "\n".join("{}. {}".format(i + 1, line)
                         for i, line in enumerate(lines))

    prompt = (
        "You are translating movie/TV subtitle lines to {lang}.\n"
        "Rules:\n"
        "- Preserve the natural spoken tone and emotion of each line\n"
        "- Keep dialogue flowing naturally as a native speaker would say it\n"
        "- Maintain character voice — sarcasm, humor, formality, urgency\n"
        "- Translate meaning and feeling, not word-for-word\n"
        "- Keep each line SHORT — subtitles must be readable quickly\n"
        "- Return ONLY the translated lines, numbered the same way\n"
        "- Do NOT add explanations, notes, or extra text\n\n"
        "Translate these subtitle lines to {lang}:\n\n{lines}"
    ).format(lang=lang, lines=numbered)

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        GEMINI_URL.format(model=model, key=api_key),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))

    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()

    # Parse numbered lines back out
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if ". " in line:
            dot = line.index(". ")
            num_str = line[:dot].strip()
            if num_str.isdigit():
                result[int(num_str)] = line[dot + 2:].strip()

    # Return in order, fall back to original if any missing
    out = []
    for i, original in enumerate(lines):
        out.append(result.get(i + 1, original))
    return out


def _gemini_translate_section(lines, lang, api_key, model="gemini-2.5-flash"):
    """Translate a section using Gemini with retry, fallback to Google on error."""
    out = list(lines)
    batches = [lines[i:i + GEMINI_BATCH]
               for i in range(0, len(lines), GEMINI_BATCH)]
    pos = 0
    for batch in batches:
        translated = None
        for attempt in range(2):
            try:
                translated = _gemini_translate_batch(batch, lang, api_key, model)
                break
            except Exception as e:
                err = str(e)
                _log("Gemini batch error (attempt {}): {}".format(
                    attempt + 1, err), xbmc.LOGWARNING)
                # Rate limit / quota — fall back to Google immediately
                if "429" in err or "quota" in err.lower() or "limit" in err.lower():
                    _log("FALLBACK: Gemini quota/limit hit — using Google Translate",
                         xbmc.LOGWARNING)
                    translated = _google_translate_section(batch, lang)
                    break
                if attempt == 0:
                    time.sleep(2)
                else:
                    _log("Gemini failed — using Google Translate for batch",
                         xbmc.LOGWARNING)
                    translated = _google_translate_section(batch, lang)

        if translated:
            out[pos:pos + len(batch)] = translated
        pos += len(batch)
    return out


# ── Google Translate ───────────────────────────────────────────────────────────

def _google_request(text, lang):
    url = GOOGLE_URL.format(tl=lang, q=urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read().decode("utf-8"))
    return "".join(p[0] for p in data[0] if p[0])


def _google_retry(text, lang):
    for attempt in range(MAX_RETRY):
        try:
            return _google_request(text, lang)
        except Exception as e:
            if attempt < MAX_RETRY - 1:
                time.sleep(2 ** attempt)
            else:
                _log("Google gave up on batch: {}".format(e), xbmc.LOGWARNING)
    return text


def _make_batches(lines):
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


def _google_translate_section(lines, lang):
    if not lines:
        return lines
    batches = _make_batches(lines)
    out     = list(lines)

    def do_batch(args):
        start, batch_lines = args
        result = _google_retry(SEP.join(batch_lines), lang)
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
                _log("Google batch error: {}".format(e), xbmc.LOGERROR)
    return out


# ── Public API ─────────────────────────────────────────────────────────────────

def translate_lines(lines, lang, api_key=None, model="gemini-2.5-flash",
                    progress_cb=None, engine_cb=None):
    """
    Translate all lines.
    Uses Gemini if api_key provided, otherwise Google Translate.
    progress_cb(done, total) called after each section.
    engine_cb(engine_name) called when engine changes (e.g. fallback to Google).
    """
    if not lines:
        return lines

    total = len(lines)
    out   = list(lines)
    done  = 0

    use_gemini = bool(api_key and api_key.strip())
    engine     = "Gemini ({})".format(model) if use_gemini else "Google Translate"
    _log("Starting: {} lines via {} to {}".format(total, engine, lang))

    i = 0
    while i < total:
        section = lines[i:i + SECTION_SIZE]

        if use_gemini:
            translated = _gemini_translate_section(section, lang, api_key.strip(), model)
        else:
            translated = _google_translate_section(section, lang)

        out[i:i + len(section)] = translated
        i    += len(section)
        done += len(section)
        if progress_cb:
            progress_cb(done, total)

    return out
