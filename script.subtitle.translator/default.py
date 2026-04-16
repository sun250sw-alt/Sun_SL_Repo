import os
import sys
import threading
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs

# ── Path setup ───────────────────────────────────────────────────────────────
_addon    = xbmcaddon.Addon()
_addondir = xbmcvfs.translatePath(_addon.getAddonInfo("path"))
_libdir   = os.path.join(_addondir, "resources", "lib")

xbmc.log("[SubTranslator] addondir: {}".format(_addondir), xbmc.LOGINFO)
xbmc.log("[SubTranslator] libdir exists: {}".format(os.path.isdir(_libdir)), xbmc.LOGINFO)

if _libdir not in sys.path:
    sys.path.insert(0, _libdir)

try:
    from languages   import LANG_CODES, LANG_LABELS
    xbmc.log("[SubTranslator] languages OK", xbmc.LOGINFO)
except Exception as e:
    xbmc.log("[SubTranslator] languages FAIL: {}".format(e), xbmc.LOGERROR)

try:
    from translator  import translate_lines
    xbmc.log("[SubTranslator] translator OK", xbmc.LOGINFO)
except Exception as e:
    xbmc.log("[SubTranslator] translator FAIL: {}".format(e), xbmc.LOGERROR)

try:
    from srt_handler import parse_srt, write_srt, translated_path
    xbmc.log("[SubTranslator] srt_handler OK", xbmc.LOGINFO)
except Exception as e:
    xbmc.log("[SubTranslator] srt_handler FAIL: {}".format(e), xbmc.LOGERROR)


def _log(msg, level=xbmc.LOGINFO):
    xbmc.log("[SubTranslator] {}".format(msg), level)


# ── Language picker ───────────────────────────────────────────────────────────

def _pick_language():
    saved = _addon.getSetting("target_language") or "en"
    try:    pre = LANG_CODES.index(saved)
    except: pre = LANG_CODES.index("en")
    idx = xbmcgui.Dialog().select("Select target language",
                                  LANG_LABELS, preselect=pre)
    if idx < 0:
        return None, None
    code, label = LANG_CODES[idx], LANG_LABELS[idx]
    _addon.setSetting("target_language", code)
    return code, label


# ── Save location picker ──────────────────────────────────────────────────────

def _pick_save_location(default_path):
    dialog = xbmcgui.Dialog()
    choice = dialog.select(
        "Save translated subtitle to...",
        [
            "Same folder as original  [{}]".format(os.path.dirname(default_path)),
            "Choose a different folder...",
        ]
    )
    if choice < 0:
        return None
    if choice == 0:
        return default_path
    folder = dialog.browse(3, "Choose save folder", "files", "",
                           False, False, os.path.dirname(default_path))
    if not folder:
        return default_path
    return os.path.join(folder, os.path.basename(default_path))


# ── Browse for subtitle ───────────────────────────────────────────────────────

def _browse_subtitle(start_dir=""):
    """
    Standard Kodi file browser for subtitles.
    Kodi natively supports browsing INTO zip files — no special handling needed.
    Mask includes .srt so user sees only relevant files.
    """
    path = xbmcgui.Dialog().browse(
        1,              # type 1 = file browser
        "Select subtitle file",
        "files",
        ".srt|.SRT",    # Kodi also lets user navigate into ZIPs natively
        False,
        False,
        start_dir
    )
    if not path or not path.lower().endswith(".srt"):
        return None
    # Handle zip:// paths Kodi returns when browsing inside a ZIP
    if path.startswith("zip://"):
        return _extract_from_zip_path(path)
    return path


def _extract_from_zip_path(zip_path):
    """
    When Kodi browses inside a ZIP it returns a zip:// URI.
    Extract the SRT to a temp folder and return the local path.
    """
    import zipfile
    import tempfile
    import urllib.parse

    try:
        # zip:// URI format: zip://path%2Fto%2Ffile.zip/inner/file.srt
        # Strip the zip:// prefix and split on the zip boundary
        without_scheme = zip_path[len("zip://"):]
        # Decode URL encoding
        decoded = urllib.parse.unquote(without_scheme)
        # Find where .zip ends
        zip_end = decoded.lower().find(".zip") + 4
        zip_file_path = decoded[:zip_end]
        inner_path    = decoded[zip_end:].lstrip("/")

        _log("ZIP path: {}  inner: {}".format(zip_file_path, inner_path))

        tmp_dir = tempfile.mkdtemp(prefix="subtrans_")
        with zipfile.ZipFile(zip_file_path, "r") as zf:
            zf.extract(inner_path, tmp_dir)

        extracted = os.path.join(tmp_dir, inner_path)
        _log("Extracted: {}".format(extracted))
        return extracted

    except Exception as e:
        _log("ZIP extract error: {}".format(e), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Subtitle Translator",
                            "Could not extract from ZIP:\n{}".format(str(e)))
        return None


# ── Subtitle detection ────────────────────────────────────────────────────────

def _find_current_sub():
    """
    Try every available method to find the currently active subtitle file.
    Works for local files. For pure network streams without external subs,
    returns None — nothing can be done without the file.
    """
    player = xbmc.Player()
    if not player.isPlayingVideo():
        return None

    # ── Method 1: getSubtitles() — returns language name, not path
    # But some Kodi builds return the path here
    for method_name in ("getSubtitlePath", "getSubtitles", "getCurrentSubtitlePath"):
        try:
            val = getattr(player, method_name)()
            _log("{}: [{}]".format(method_name, val))
            if val and val.strip() and not val.startswith("http"):
                p = xbmcvfs.translatePath(val.strip())
                if os.path.isfile(p):
                    _log("Found via {}: {}".format(method_name, p))
                    return p
        except AttributeError:
            _log("{} not available on this Kodi build".format(method_name))
        except Exception as e:
            _log("{} error: {}".format(method_name, e))

    # ── Method 2: all InfoLabels that might contain a file path
    for label in (
        "Player.SubtitlePath",
        "VideoPlayer.SubtitlePath",
        "Player.Subtitle",
        "VideoPlayer.Subtitles",
        "Player.CurrentSubtitle",
        "Subtitles.Path",
        "ListItem.SubtitleLanguage",
    ):
        try:
            val = xbmc.getInfoLabel(label).strip()
            # Skip if Kodi returns the label name itself (not evaluated)
            if val and val != label and not val.startswith("["):
                p = xbmcvfs.translatePath(val)
                if os.path.isfile(p):
                    _log("Found via InfoLabel {}: {}".format(label, p))
                    return p
                _log("InfoLabel {} returned non-path: [{}]".format(label, val))
        except Exception as e:
            _log("InfoLabel {} error: {}".format(label, e))

    # ── Method 3: getAvailableSubtitleStreams
    try:
        streams = player.getAvailableSubtitleStreams()
        active  = player.getSubtitleStream()
        _log("Streams: {}  active idx: {}".format(streams, active))
        if streams and 0 <= active < len(streams):
            val = streams[active]
            if val:
                p = xbmcvfs.translatePath(val)
                if os.path.isfile(p):
                    _log("Found via stream list: {}".format(p))
                    return p
    except Exception as e:
        _log("Stream list error: {}".format(e))

    # ── Method 4: JSON-RPC — most complete API, often works when others don't
    try:
        import json
        req = json.dumps({
            "jsonrpc": "2.0",
            "method":  "Player.GetItem",
            "params":  {
                "playerid": 1,
                "properties": ["subtitles", "currentsubtitle", "file"]
            },
            "id": 1
        })
        resp = json.loads(xbmc.executeJSONRPC(req))
        _log("JSONRPC response: {}".format(resp))
        item = resp.get("result", {}).get("item", {})

        # currentsubtitle may have an index we can map
        current = item.get("currentsubtitle", {})
        subs    = item.get("subtitles", [])
        _log("currentsubtitle: {}  all subs: {}".format(current, subs))

        # Some builds put the path in the subtitle object
        for sub in subs:
            for key in ("file", "path", "name"):
                val = sub.get(key, "")
                if val and os.path.isfile(xbmcvfs.translatePath(val)):
                    p = xbmcvfs.translatePath(val)
                    _log("Found via JSONRPC sub.{}: {}".format(key, p))
                    return p

        # Try the video file path itself
        vfile = item.get("file", "")
        _log("JSONRPC video file: {}".format(vfile))

    except Exception as e:
        _log("JSONRPC error: {}".format(e))

    # ── Method 5: scan folder next to local video
    try:
        playing_file = player.getPlayingFile()
        if not playing_file.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            vpath = xbmcvfs.translatePath(playing_file)
            vdir  = os.path.dirname(vpath)
            vbase = os.path.splitext(os.path.basename(vpath))[0]
            _log("Scanning folder: {}  base: {}".format(vdir, vbase))
            matches = []
            others  = []
            for f in sorted(os.listdir(vdir)):
                low = f.lower()
                if not low.endswith(".srt") or "_translated_" in f:
                    continue
                full = os.path.join(vdir, f)
                if f.startswith(vbase):
                    matches.append(full)
                else:
                    others.append(full)
            if matches:
                _log("Found via folder match: {}".format(matches[0]))
                return matches[0]
            if others:
                _log("Found via folder scan: {}".format(others[0]))
                return others[0]
    except Exception as e:
        _log("Folder scan error: {}".format(e))

    _log("No subtitle detected by any method")
    return None


# ── Debug info ────────────────────────────────────────────────────────────────

def _debug_subtitle_info():
    import json
    player = xbmc.Player()
    lines  = []
    lines.append("Playing: {}".format(player.isPlayingVideo()))
    if player.isPlayingVideo():
        try:
            lines.append("File: {}".format(player.getPlayingFile()))
        except Exception as e:
            lines.append("File ERROR: {}".format(e))
        for method_name in ("getSubtitlePath", "getSubtitles",
                            "getCurrentSubtitlePath"):
            try:
                val = getattr(player, method_name)()
                lines.append("{}: [{}]".format(method_name, val))
            except AttributeError:
                lines.append("{}: NOT AVAILABLE".format(method_name))
            except Exception as e:
                lines.append("{} ERROR: {}".format(method_name, e))
        try:
            streams = player.getAvailableSubtitleStreams()
            active  = player.getSubtitleStream()
            lines.append("Active stream: {}".format(active))
            for i, s in enumerate(streams):
                lines.append("  [{}]: {}".format(i, s))
        except Exception as e:
            lines.append("Streams ERROR: {}".format(e))
        for label in ("Player.SubtitlePath", "VideoPlayer.SubtitlePath",
                      "Player.Subtitle", "VideoPlayer.Subtitles",
                      "Player.CurrentSubtitle", "Subtitles.Path",
                      "Player.HasSubtitles", "Player.SubtitlesEnabled"):
            try:
                lines.append("{}: [{}]".format(label, xbmc.getInfoLabel(label)))
            except Exception as e:
                lines.append("{} ERROR: {}".format(label, e))
        try:
            req = json.dumps({
                "jsonrpc": "2.0", "method": "Player.GetItem",
                "params": {"playerid": 1,
                           "properties": ["subtitles", "currentsubtitle", "file"]},
                "id": 1
            })
            resp = json.loads(xbmc.executeJSONRPC(req))
            item = resp.get("result", {}).get("item", {})
            lines.append("JSONRPC currentsubtitle: {}".format(
                item.get("currentsubtitle", "n/a")))
            lines.append("JSONRPC subtitles: {}".format(
                item.get("subtitles", [])))
        except Exception as e:
            lines.append("JSONRPC ERROR: {}".format(e))
    xbmcgui.Dialog().textviewer("Subtitle Debug Info", "\n".join(lines))


# ── Core translation ──────────────────────────────────────────────────────────

def _translate(sub_path, lang_code, lang_label, save_path):
    import time
    _log("_translate: {} -> {} -> {}".format(sub_path, lang_code, save_path))

    state = {
        "pct": 0, "msg": "Starting...",
        "done": False, "result": None, "error": None,
        "last_move": time.time(),
    }

    STUCK_TIMEOUT = 90
    FORCE_AFTER   = 15

    try:
        prog = xbmcgui.DialogProgress()
        prog.create("Subtitle Translator", "Starting...")
        prog.update(0, "Starting...")
        xbmc.sleep(100)
    except Exception as e:
        _log("Dialog create failed: {}".format(e), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Subtitle Translator",
                            "Could not open progress dialog:\n{}".format(e))
        return None

    def worker():
        try:
            _log("Worker started")
            state["pct"] = 3
            state["msg"] = "Reading subtitle file..."
            blocks = parse_srt(sub_path)
            _log("Parsed {} blocks".format(len(blocks) if blocks else 0))
            if not blocks:
                state["error"] = "Could not read subtitle file."
                return

            total       = len(blocks)
            clean_lines = [b["clean_text"] for b in blocks]
            state["pct"]       = 8
            state["msg"]       = "Loaded {} lines. Translating...".format(total)
            state["last_move"] = time.time()

            def on_progress(done, total_lines):
                state["pct"]       = 10 + int(80 * done / total_lines)
                state["msg"]       = "Translating {}/{} lines ({:.0f}%)".format(
                    done, total_lines, 100 * done / total_lines)
                state["last_move"] = time.time()

            translated = translate_lines(clean_lines, lang_code,
                                         progress_cb=on_progress)
            _log("Translation done: {} results".format(len(translated)))

            state["pct"]       = 92
            state["msg"]       = "Merging..."
            state["last_move"] = time.time()
            for b, tx in zip(blocks, translated):
                b["raw_text"] = tx.strip() or b["clean_text"]

            state["pct"]       = 96
            state["msg"]       = "Saving..."
            state["last_move"] = time.time()
            dest_dir = os.path.dirname(save_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            write_srt(blocks, save_path)
            _log("Saved: {}".format(save_path))

            state["pct"]    = 100
            state["msg"]    = "Done!"
            state["result"] = save_path

        except Exception as e:
            import traceback
            _log("Worker error: {}\n{}".format(e, traceback.format_exc()),
                 xbmc.LOGERROR)
            state["error"] = "{}\n\nSee Kodi log for details.".format(str(e))
        finally:
            state["done"] = True
            _log("Worker finished")

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    DOTS      = ["   ", ".  ", ".. ", "..."]
    dot_i     = 0
    start_t   = time.time()
    cancelled    = False
    force_closed = False

    while not state["done"]:
        elapsed = int(time.time() - start_t)
        no_move = time.time() - state["last_move"]
        dot_i   = (dot_i + 1) % len(DOTS)
        msg     = "{} | {}s{}".format(state["msg"], elapsed, DOTS[dot_i])
        if no_move > 30:
            msg += " [retrying...]"
        if no_move > STUCK_TIMEOUT:
            _log("Stuck timeout")
            force_closed = True
            break
        try:
            prog.update(state["pct"], msg)
        except Exception:
            pass
        if prog.iscanceled():
            if int(time.time() - start_t) > FORCE_AFTER:
                force_closed = True
            else:
                cancelled = True
            break
        xbmc.sleep(400)

    try:
        prog.close()
    except Exception:
        pass

    if force_closed:
        t.join(timeout=2)
        xbmcgui.Dialog().notification(
            "Subtitle Translator", "Force closed.",
            xbmcgui.NOTIFICATION_WARNING, 3000)
        return None
    if cancelled:
        t.join(timeout=2)
        return None

    t.join(timeout=15)

    if state["error"]:
        _log("Error: {}".format(state["error"]), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Subtitle Translator",
                            "Error:\n{}".format(state["error"]))
        return None

    return state["result"]


# ── Load subtitle into player ─────────────────────────────────────────────────

def _load_sub(path):
    """
    Load subtitle into the player using the same method Kodi's own browser uses.

    The key difference vs a simple setSubtitles() call:
    - Use xbmc.Player().setSubtitleURL() which is the internal method Kodi's
      subtitle browser uses — it registers the file properly with the renderer
    - If that's not available fall back to setSubtitles() BUT also send the
      SubtitleDelay reset and enable command via executebuiltin so Kodi
      activates display the same way its own browser does
    - Small sleep before and after to let the player state settle
    """
    player = xbmc.Player()
    if not player.isPlayingVideo():
        xbmcgui.Dialog().notification(
            "Subtitle Translator", "No video playing.",
            xbmcgui.NOTIFICATION_INFO, 3000)
        return False
    try:
        _log("Loading subtitle: {}".format(path))

        # Small pause — player must be in stable state before subtitle switch
        xbmc.sleep(200)

        # Method 1: setSubtitleURL — used internally by Kodi's subtitle browser
        # This registers the file with the render pipeline properly
        loaded = False
        try:
            player.setSubtitleURL(path)
            loaded = True
            _log("Loaded via setSubtitleURL")
        except AttributeError:
            _log("setSubtitleURL not available, trying setSubtitles")
        except Exception as e:
            _log("setSubtitleURL error: {}".format(e))

        # Method 2: setSubtitles fallback
        if not loaded:
            player.setSubtitles(path)
            _log("Loaded via setSubtitles")

        # Wait for Kodi to register the new subtitle stream
        xbmc.sleep(300)

        # Enable subtitle display — same sequence Kodi's browser uses internally
        player.showSubtitles(True)

        # Also trigger via executebuiltin to force renderer activation
        # This is what makes it actually visible on screen
        xbmc.executebuiltin("Action(ShowSubtitles)")
        xbmc.sleep(100)
        xbmc.executebuiltin("Action(ShowSubtitles)")

        _log("Subtitle display activated: {}".format(path))
        return True

    except Exception as e:
        _log("Load failed: {}".format(e), xbmc.LOGERROR)
        return False


# ── Translate workflow ────────────────────────────────────────────────────────

def _run_translate_workflow(sub_path):
    _log("Translate workflow: {}".format(sub_path))
    dialog = xbmcgui.Dialog()

    code, label = _pick_language()
    if not code:
        return

    suffix      = _addon.getSetting("output_suffix") or "_translated"
    default_out = translated_path(sub_path, suffix, code)
    save_path   = _pick_save_location(default_out)
    if save_path is None:
        return

    out = _translate(sub_path, code, label, save_path)
    if not out:
        return

    player = xbmc.Player()
    auto   = _addon.getSetting("auto_load").lower() in ("true", "1", "yes")

    if player.isPlayingVideo():
        if auto:
            _load_sub(out)
            dialog.notification(
                "Translation done!",
                "{} loaded".format(os.path.basename(out)),
                xbmcgui.NOTIFICATION_INFO, 4000)
        else:
            if dialog.yesno(
                "Translation Complete",
                "Saved: [B]{}[/B]\nLanguage: {}\n\n"
                "Load subtitle into the currently playing video now?".format(
                    os.path.basename(out), label),
                nolabel="Not Now",
                yeslabel="Load into Video"
            ):
                _load_sub(out)
    else:
        dialog.ok(
            "Translation Complete",
            "Saved: [B]{}[/B]\nLanguage: {}".format(
                os.path.basename(out), label))


# ── Main menu ─────────────────────────────────────────────────────────────────

def main():
    _log("main() called")
    dialog  = xbmcgui.Dialog()
    player  = xbmc.Player()
    playing = player.isPlayingVideo()

    options = []
    menu    = []

    if playing:
        active = _find_current_sub()
        if active:
            options.append("Grab & translate loaded subtitle  [{}]".format(
                os.path.basename(active)))
            menu.append(("grab", active))
        else:
            # Could not auto-detect — show disabled-style label, no option
            options.append("Subtitle not detected — browse below")
            menu.append(("no_sub", None))

    # Always available — standard Kodi browser (supports ZIP natively)
    options.append("Translate a subtitle file...")
    menu.append(("browse", None))

    options.append("Settings")
    menu.append(("settings", None))

    options.append("Debug: subtitle detection info")
    menu.append(("debug", None))

    idx = dialog.select("Subtitle Translator", options)
    if idx < 0:
        return

    action, payload = menu[idx]
    _log("Action: {}  payload: {}".format(action, payload))

    if action == "grab":
        _run_translate_workflow(payload)

    elif action == "no_sub":
        # Tapped the informational "not detected" row — jump straight to browse
        path = _browse_subtitle()
        if path:
            _run_translate_workflow(path)

    elif action == "browse":
        path = _browse_subtitle()
        if path:
            _run_translate_workflow(path)

    elif action == "settings":
        _addon.openSettings()

    elif action == "debug":
        _debug_subtitle_info()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        xbmc.log("[SubTranslator] UNHANDLED: {}\n{}".format(
            e, traceback.format_exc()), xbmc.LOGERROR)
        xbmcgui.Dialog().ok("Subtitle Translator",
                            "Unexpected error:\n{}".format(e))

# Also handle being called as a plugin:// URL (from context menu)
elif len(sys.argv) > 0 and sys.argv[0].startswith("plugin://"):
    try:
        main()
    except Exception as e:
        import traceback
        xbmc.log("[SubTranslator] PLUGIN UNHANDLED: {}\n{}".format(
            e, traceback.format_exc()), xbmc.LOGERROR)


# ── Subtitle file browser ─────────────────────────────────────────────────────
# NOTE: appended after main() so it's defined before being called at runtime

def _browse_subtitle(start_dir=""):
    """
    Kodi native file browser.
    Kodi already supports navigating INTO zip files — user just browses
    into the zip and picks the .srt inside. No special handling needed.
    The zip:// path Kodi returns is handled by _extract_from_zip_path.
    """
    import zipfile, tempfile, urllib.parse

    path = xbmcgui.Dialog().browse(
        1,           # file browser
        "Select subtitle file",
        "files",
        ".srt|.SRT", # filter — Kodi still shows folders and ZIPs for navigation
        False,
        False,
        start_dir
    )
    if not path:
        return None

    # Kodi returns zip:// URI when user browses inside a ZIP
    if path.startswith("zip://"):
        try:
            without_scheme = path[len("zip://"):]
            decoded        = urllib.parse.unquote(without_scheme)
            zip_end        = decoded.lower().find(".zip") + 4
            zip_file_path  = decoded[:zip_end]
            inner_path     = decoded[zip_end:].lstrip("/")
            _log("ZIP: {} inner: {}".format(zip_file_path, inner_path))
            tmp_dir = tempfile.mkdtemp(prefix="subtrans_")
            with zipfile.ZipFile(zip_file_path, "r") as zf:
                zf.extract(inner_path, tmp_dir)
            extracted = os.path.join(tmp_dir, inner_path)
            _log("Extracted: {}".format(extracted))
            return extracted
        except Exception as e:
            _log("ZIP extract error: {}".format(e), xbmc.LOGERROR)
            xbmcgui.Dialog().ok("Subtitle Translator",
                                "Could not extract from ZIP:\n{}".format(str(e)))
            return None

    if not path.lower().endswith(".srt"):
        return None

    return path
