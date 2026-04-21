import os
import sys
import urllib.parse
import zipfile
import tempfile
import threading
import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import xbmcvfs

ADDON      = xbmcaddon.Addon()
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
ADDON_DATA = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
LIB_PATH   = os.path.join(ADDON_PATH, "resources", "lib")
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

from languages   import LANG_CODES, LANG_LABELS
from translator  import translate_lines
from srt_handler import parse_srt, write_srt, shift_blocks

try:
    HANDLE = int(sys.argv[1])
except (IndexError, ValueError):
    HANDLE = -1

PARAMS = {}
if len(sys.argv) > 2 and sys.argv[2]:
    PARAMS = dict(urllib.parse.parse_qsl(sys.argv[2].lstrip("?")))

os.makedirs(ADDON_DATA, exist_ok=True)

KODI_TEMP = xbmcvfs.translatePath("special://temp/")

LANG_FILE    = os.path.join(ADDON_DATA, "last_lang.txt")
API_KEY_FILE = os.path.join(ADDON_DATA, "gemini_key.txt")
MODEL_FILE   = os.path.join(ADDON_DATA, "gemini_model.txt")

MODELS = [
    ("gemini-2.5-flash",      "Gemini 2.5 Flash      — Best quality | 250 req/day"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — Good quality | 1000 req/day"),
    ("gemini-2.5-pro",        "Gemini 2.5 Pro        — Highest quality | 100 req/day"),
]
MODEL_IDS    = [m[0] for m in MODELS]
MODEL_LABELS = [m[1] for m in MODELS]

# None = custom input marker
SYNC_OPTIONS = [
    ("-60 sec  (60 seconds earlier)",  -60000),
    ("-30 sec  (30 seconds earlier)",  -30000),
    ("-10 sec  (10 seconds earlier)",  -10000),
    ("-5 sec   (5 seconds earlier)",   -5000),
    ("Custom time shift...",           None),
    ("No timing change",               0),
    ("+5 sec   (5 seconds later)",     5000),
    ("+10 sec  (10 seconds later)",    10000),
    ("+30 sec  (30 seconds later)",    30000),
    ("+60 sec  (60 seconds later)",    60000),
]
SYNC_LABELS  = [s[0] for s in SYNC_OPTIONS]
SYNC_OFFSETS = [s[1] for s in SYNC_OPTIONS]
SYNC_DEFAULT = 5   # index of "No timing change"
SYNC_CUSTOM  = 4   # index of "Custom time shift..."

CUSTOM_FORMAT_HELP = (
    "Enter time shift in seconds.\n"
    "Use negative to shift earlier, positive to shift later.\n\n"
    "Examples:\n"
    "  -45    = 45 seconds earlier\n"
    "  30     = 30 seconds later\n"
    "  -90    = 90 seconds (1.5 min) earlier\n"
    "  120    = 120 seconds (2 min) later\n\n"
    "Enter value (seconds):"
)


def _log(msg):
    xbmc.log("[SubtitleTranslator] {}".format(msg), xbmc.LOGINFO)


def _read(path, default=""):
    try:
        if os.path.isfile(path):
            return open(path, "r").read().strip()
    except Exception:
        pass
    return default


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(value)
    except Exception as e:
        _log("write error {}: {}".format(path, e))


def _load_lang():
    code = _read(LANG_FILE, "en")
    return code if code in LANG_CODES else "en"


def _save_lang(code):
    _write(LANG_FILE, code)


def _load_api_key():
    return _read(API_KEY_FILE, "")


def _save_api_key(key):
    _write(API_KEY_FILE, key)


def _load_model():
    m = _read(MODEL_FILE, "gemini-2.5-flash")
    return m if m in MODEL_IDS else "gemini-2.5-flash"


def _save_model(model):
    _write(MODEL_FILE, model)


def _label_for(code):
    try:
        return LANG_LABELS[LANG_CODES.index(code)]
    except ValueError:
        return code


def _model_label(model_id):
    for mid, lbl in MODELS:
        if mid == model_id:
            return lbl
    return model_id


def _url(**kw):
    return "plugin://service.subtitles.translator/?" + urllib.parse.urlencode(kw)


# ── Shared workflow: file → language → sync → translate ───────────────────────

def _run_workflow(sub_path):
    """
    Common flow used by both browse actions:
    1. Pick target language
    2. Pick timing sync offset
    3. Translate (+ apply shift)
    4. Return result path or None
    """
    dialog = xbmcgui.Dialog()

    # 1. Language picker
    saved = _load_lang()
    try:    pre = LANG_CODES.index(saved)
    except: pre = LANG_CODES.index("en")

    idx_lang = dialog.select(
        "Select target language", LANG_LABELS, preselect=pre)
    if idx_lang < 0:
        return None

    lang_code  = LANG_CODES[idx_lang]
    lang_label = LANG_LABELS[idx_lang]
    _save_lang(lang_code)

    # 2. Sync picker — always shown after language
    idx_sync = dialog.select(
        "Adjust subtitle timing (sync)",
        SYNC_LABELS,
        preselect=SYNC_DEFAULT)
    if idx_sync < 0:
        return None

    if idx_sync == SYNC_CUSTOM:
        # Show format help then keyboard input
        dialog.ok("Custom Time Shift", CUSTOM_FORMAT_HELP)
        kb = xbmc.Keyboard("", "Enter seconds (e.g. -45 or 30)")
        kb.doModal()
        if not kb.isConfirmed():
            return None
        raw = kb.getText().strip()
        try:
            offset_ms = int(float(raw) * 1000)
        except ValueError:
            dialog.ok("Subtitle Translator",
                      "Invalid value: [B]{}[/B]\nPlease enter a number like -45 or 30.".format(raw))
            return None
        offset_label = "Custom {}s".format(raw)
    else:
        offset_ms    = SYNC_OFFSETS[idx_sync]
        offset_label = SYNC_LABELS[idx_sync]

    # 3. Translate
    out_path = os.path.join(ADDON_DATA, "translated_{}.srt".format(lang_code))
    return _translate(sub_path, lang_code, lang_label,
                      out_path, offset_ms, offset_label)


# ── action=search — main menu ─────────────────────────────────────────────────

def do_search():
    last_lang = _label_for(_load_lang())
    api_key   = _load_api_key()
    model     = _load_model()

    if api_key:
        engine = "Gemini: {}".format(_model_label(model).split("—")[0].strip())
    else:
        engine = "Google Translate (free)"

    subtitle = "{}  |  Last: {}".format(engine, last_lang)

    # 1. Browse any location
    item1 = xbmcgui.ListItem(
        label="Browse for subtitle file...",
        label2=subtitle)
    item1.setArt({"thumb": "DefaultSubtitles.png"})
    item1.setProperty("sync",        "false")
    item1.setProperty("hearing_imp", "false")
    xbmcplugin.addDirectoryItem(
        HANDLE, _url(action="browse", start_dir=""), item1, isFolder=False)

    # 2. Kodi temp folder
    item2 = xbmcgui.ListItem(
        label="Browse Kodi temp folder  [{}]".format(KODI_TEMP),
        label2=subtitle)
    item2.setArt({"thumb": "DefaultFolder.png"})
    item2.setProperty("sync",        "false")
    item2.setProperty("hearing_imp", "false")
    xbmcplugin.addDirectoryItem(
        HANDLE,
        _url(action="browse", start_dir=urllib.parse.quote(KODI_TEMP)),
        item2, isFolder=False)

    # 3. Gemini API key
    key_display = "Set" if api_key else "Not set"
    item3 = xbmcgui.ListItem(
        label="Gemini API Key  [{}]".format(key_display),
        label2="Tap to enter your free key from aistudio.google.com")
    item3.setArt({"thumb": "DefaultAddonProgram.png"})
    item3.setProperty("sync",        "false")
    item3.setProperty("hearing_imp", "false")
    xbmcplugin.addDirectoryItem(
        HANDLE, _url(action="set_api_key"), item3, isFolder=False)

    # 4. Model selector (only if key set)
    if api_key:
        item4 = xbmcgui.ListItem(
            label="Gemini Model  [{}]".format(
                _model_label(model).split("—")[0].strip()),
            label2=_model_label(model).split("—")[1].strip()
                   if "—" in _model_label(model) else "")
        item4.setArt({"thumb": "DefaultAddonProgram.png"})
        item4.setProperty("sync",        "false")
        item4.setProperty("hearing_imp", "false")
        xbmcplugin.addDirectoryItem(
            HANDLE, _url(action="set_model"), item4, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)


# ── action=browse ─────────────────────────────────────────────────────────────

def do_browse():
    start_dir = urllib.parse.unquote(PARAMS.get("start_dir", ""))

    # File browser
    path = xbmcgui.Dialog().browse(
        1, "Select subtitle file",
        "files", ".srt|.SRT",
        False, False, start_dir)

    if not path:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    sub_path = _resolve(path)
    if not sub_path:
        xbmcplugin.endOfDirectory(HANDLE)
        return

    # Language + sync + translate
    result = _run_workflow(sub_path)

    if result and os.path.isfile(result):
        item = xbmcgui.ListItem(label=os.path.basename(result))
        item.setProperty("sync",        "true")
        item.setProperty("hearing_imp", "false")
        xbmcplugin.addDirectoryItem(HANDLE, result, item, isFolder=False)
    else:
        xbmcgui.Dialog().notification(
            "Subtitle Translator", "Translation failed.",
            xbmcgui.NOTIFICATION_ERROR, 3000)

    xbmcplugin.endOfDirectory(HANDLE)


# ── action=set_api_key ────────────────────────────────────────────────────────

def do_set_api_key():
    current = _load_api_key()
    dialog  = xbmcgui.Dialog()

    kb = xbmc.Keyboard(current, "Enter Gemini API Key")
    kb.setHiddenInput(False)
    kb.doModal()

    if not kb.isConfirmed():
        xbmcplugin.endOfDirectory(HANDLE)
        return

    new_key = kb.getText().strip()

    if new_key == "":
        if current and not dialog.yesno(
            "Gemini API Key",
            "Remove Gemini API key?\nAddon will use Google Translate instead.",
            nolabel="Cancel", yeslabel="Remove"
        ):
            xbmcplugin.endOfDirectory(HANDLE)
            return
        _save_api_key("")
        dialog.notification("Subtitle Translator",
                            "Gemini key removed. Using Google Translate.",
                            xbmcgui.NOTIFICATION_INFO, 3000)
    else:
        _save_api_key(new_key)
        dialog.notification("Subtitle Translator",
                            "Gemini API key saved!",
                            xbmcgui.NOTIFICATION_INFO, 3000)

    xbmcplugin.endOfDirectory(HANDLE)


# ── action=set_model ──────────────────────────────────────────────────────────

def do_set_model():
    current = _load_model()
    try:    pre = MODEL_IDS.index(current)
    except: pre = 0

    idx = xbmcgui.Dialog().select(
        "Select Gemini Model", MODEL_LABELS, preselect=pre)

    if idx >= 0:
        _save_model(MODEL_IDS[idx])
        xbmcgui.Dialog().notification(
            "Subtitle Translator",
            "Model: {}".format(MODEL_LABELS[idx].split("—")[0].strip()),
            xbmcgui.NOTIFICATION_INFO, 3000)

    xbmcplugin.endOfDirectory(HANDLE)


# ── Translation core ──────────────────────────────────────────────────────────

def _translate(sub_path, lang_code, lang_label, out_path,
               offset_ms=0, offset_label=None):
    import time

    state = {
        "pct": 0, "msg": "Starting...",
        "done": False, "result": None, "error": None,
        "last_move": time.time(),
        "engine": "...",
    }

    try:
        prog = xbmcgui.DialogProgress()
        prog.create("Subtitle Translator", "Starting...")
        prog.update(0, "Starting...")
        xbmc.sleep(100)
    except Exception as e:
        _log("Dialog failed: {}".format(e))
        return None

    def worker():
        try:
            state["pct"] = 3
            state["msg"] = "Reading subtitle..."
            blocks = parse_srt(sub_path)
            if not blocks:
                state["error"] = "No subtitle blocks found."
                return

            total = len(blocks)
            clean = [b["clean_text"] for b in blocks]
            state["pct"]       = 8
            state["msg"]       = "Loaded {} lines...".format(total)
            state["last_move"] = time.time()

            api_key = _load_api_key()
            model   = _load_model()

            if api_key:
                short           = model.replace("gemini-", "").replace("-", " ").title()
                engine          = "Gemini {}".format(short)
            else:
                engine          = "Google Translate"
            state["engine"] = engine

            _log("Using: {} -> {}".format(engine, lang_label))

            def on_progress(done, total_lines):
                state["pct"]       = 10 + int(80 * done / total_lines)
                state["msg"]       = "Translating {}/{} lines ({:.0f}%)".format(
                    done, total_lines, 100 * done / total_lines)
                state["last_move"] = time.time()

            translated = translate_lines(clean, lang_code,
                                         api_key=api_key or None,
                                         model=model,
                                         progress_cb=on_progress)

            state["pct"]       = 92
            state["msg"]       = "Merging..."
            state["last_move"] = time.time()
            for b, tx in zip(blocks, translated):
                b["raw_text"] = tx.strip() or b["clean_text"]

            # Apply timing shift after translation
            if offset_ms != 0:
                state["msg"]       = "Syncing timing ({})...".format(
                    offset_label or "")
                state["last_move"] = time.time()
                blocks = shift_blocks(blocks, offset_ms)

            state["pct"]       = 96
            state["msg"]       = "Saving..."
            state["last_move"] = time.time()
            write_srt(blocks, out_path)

            state["pct"]    = 100
            state["msg"]    = "Done!"
            state["result"] = out_path

        except Exception as e:
            import traceback
            _log("Worker error: {}".format(traceback.format_exc()))
            state["error"] = str(e)
        finally:
            state["done"] = True

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    DOTS    = ["   ", ".  ", ".. ", "..."]
    dot_i   = 0
    start_t = time.time()
    cancelled = False

    while not state["done"]:
        elapsed = int(time.time() - start_t)
        no_move = time.time() - state["last_move"]
        dot_i   = (dot_i + 1) % len(DOTS)
        msg     = "[{}]  {}  |  {}s{}".format(
            state["engine"], state["msg"], elapsed, DOTS[dot_i])
        if no_move > 30:
            msg += "  [retrying...]"
        if no_move > 90:
            break
        try:
            prog.update(state["pct"], msg)
        except Exception:
            pass
        if prog.iscanceled():
            cancelled = True
            break
        xbmc.sleep(400)

    try:
        prog.close()
    except Exception:
        pass

    t.join(timeout=10)
    if cancelled or state["error"]:
        return None
    return state["result"]


def _resolve(path):
    if path.startswith("zip://"):
        try:
            decoded  = urllib.parse.unquote(path[len("zip://"):])
            zip_end  = decoded.lower().find(".zip") + 4
            zip_file = decoded[:zip_end]
            inner    = decoded[zip_end:].lstrip("/")
            tmp = tempfile.mkdtemp(prefix="subtrans_")
            with zipfile.ZipFile(zip_file, "r") as zf:
                zf.extract(inner, tmp)
            return os.path.join(tmp, inner)
        except Exception as e:
            _log("ZIP error: {}".format(e))
            return None
    return path if path.lower().endswith(".srt") else None


# ── Router ────────────────────────────────────────────────────────────────────

def main():
    action = PARAMS.get("action", "search")
    _log("action={}".format(action))
    if action == "search":
        do_search()
    elif action in ("download", "browse"):
        do_browse()
    elif action == "set_api_key":
        do_set_api_key()
    elif action == "set_model":
        do_set_model()
    else:
        do_search()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        xbmc.log("[SubtitleTranslator] UNHANDLED: {}\n{}".format(
            e, traceback.format_exc()), xbmc.LOGERROR)
        try:
            xbmcplugin.endOfDirectory(HANDLE)
        except Exception:
            pass
