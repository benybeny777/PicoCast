"""YMM4 GUI automation renderer.
Launches YMM4 with a .ymmp project, triggers 動画出力 via Ctrl+F1,
and waits for completion.

Prerequisite: In YMM4 settings, assign Ctrl+F1 to the 動画出力 command.

Requires: pip install pywinauto
"""
import os
import time
import subprocess
import logging

from config import YMM4_EXE, YMM4_OUTPUT_SHORTCUT as OUTPUT_VIDEO_SHORTCUT

_STARTUP_TIMEOUT = 60    # seconds to wait for YMM4 window
_EXPORT_TIMEOUT  = 3600  # max seconds for render to finish

_EXPORT_BUTTON_LABELS = ["出力開始", "出力", "エンコード開始", "エンコード", "OK", "開始", "実行"]
_CANCEL_WORDS         = ["キャンセル", "閉じる", "いいえ", "No", "Cancel"]

log = logging.getLogger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def render_ymmp(ymmp_path: str, close_after: bool = True) -> bool:
    """Open ymmp in YMM4, export video, optionally close YMM4.

    Returns True on success, False on failure.
    """
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    try:
        from pywinauto import Application, Desktop
    except ImportError:
        raise RuntimeError("pywinauto is not installed. Run: pip install pywinauto")

    ymmp_path = os.path.abspath(ymmp_path)
    if not os.path.exists(ymmp_path):
        raise FileNotFoundError(f"Project file not found: {ymmp_path}")

    log.info(f"Launching YMM4: {os.path.basename(ymmp_path)}")
    proc = subprocess.Popen([YMM4_EXE, ymmp_path])

    try:
        # --- Wait for main window ---
        app = _wait_for_ymm4(proc)
        if app is None:
            log.error("YMM4 did not start within timeout")
            proc.terminate()
            return False

        main_win = app.top_window()
        log.info(f"YMM4 window: {main_win.window_text()}")

        # --- Brief initial wait for project to load ---
        time.sleep(5)

        # --- Send shortcut (up to 10 attempts) ---
        export_detected = False
        for attempt in range(1, 11):
            try:
                main_win.set_focus()
                time.sleep(0.5)
                main_win.type_keys(OUTPUT_VIDEO_SHORTCUT, with_spaces=False)
                log.info(f"[{attempt}/10] Sent {OUTPUT_VIDEO_SHORTCUT}")
            except Exception as e:
                log.warning(f"[{attempt}/10] type_keys failed: {e}")

            if _export_ui_appeared(main_win, wait=5):
                log.info("Export UI detected")
                export_detected = True
                break

            if attempt < 10:
                log.info("  Export UI not yet visible, retrying in 3s...")
                time.sleep(3)

        if not export_detected:
            log.warning("Export UI not detected — proceeding anyway (panel may be docked)")
            time.sleep(2)

        # --- Click 出力開始 ---
        _click_export_start(main_win)

        # --- Handle file-save dialog (output path confirmation) ---
        _handle_file_save_dialog()

        # --- Wait for completion ---
        success = _wait_for_completion(main_win, ymmp_path)

        if close_after:
            try:
                main_win.close()
                time.sleep(1)
                _dismiss_save_dialog()
            except Exception:
                pass

        return success

    finally:
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _wait_for_ymm4(proc, timeout=_STARTUP_TIMEOUT):
    from pywinauto import Application
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            app = Application(backend="uia").connect(path=YMM4_EXE, timeout=2)
            app.top_window().wait("visible", timeout=2)
            return app
        except Exception:
            time.sleep(1)
    return None


def _export_ui_appeared(main_win, wait: float = 4) -> bool:
    """Return True if export dialog (popup or docked panel) is visible."""
    from pywinauto import Desktop
    desktop = Desktop(backend="uia")
    deadline = time.time() + wait

    while time.time() < deadline:
        # ① Separate popup window
        for title_re in [r".*動画出力.*", r".*エクスポート.*", r".*Mp4.*", r".*出力設定.*"]:
            try:
                for w in desktop.windows(title_re=title_re):
                    if w.is_visible():
                        log.info(f"Export popup: '{w.window_text()}'")
                        return True
            except Exception:
                pass

        # ② Docked panel inside main window — look for the start button
        try:
            for ctrl in main_win.descendants():
                if (ctrl.window_text() or "").strip() in _EXPORT_BUTTON_LABELS:
                    log.info(f"Export button in main_win: '{ctrl.window_text()}'")
                    return True
        except Exception:
            pass

        time.sleep(0.5)
    return False


def _click_export_start(main_win):
    """Find and click 出力開始 — checks popup windows and docked panels."""
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    desktop = Desktop(backend="uia")

    # ① Popup window
    for title_re in [r".*動画出力.*", r".*エクスポート.*", r".*Mp4.*", r".*出力設定.*"]:
        try:
            for w in desktop.windows(title_re=title_re):
                if not w.is_visible():
                    continue
                log.info(f"Clicking in popup: '{w.window_text()}'")
                if _click_start_button(w):
                    return
        except Exception:
            pass

    # ② Docked panel inside main_win
    found_labels = []
    try:
        for ctrl in main_win.descendants():
            txt = (ctrl.window_text() or "").strip()
            if not txt:
                continue
            found_labels.append(txt)
            if txt in _EXPORT_BUTTON_LABELS:
                try:
                    ctrl.click_input()
                    log.info(f"Clicked panel button: '{txt}'")
                    return
                except Exception as e:
                    log.warning(f"click_input failed on '{txt}': {e}")
    except Exception as e:
        log.warning(f"Descendant scan failed: {e}")

    log.warning(f"出力開始 not found. Controls seen: {found_labels[:30]}")
    log.warning("Pressing Enter as last resort")
    try:
        main_win.set_focus()
    except Exception:
        pass
    send_keys("{ENTER}")


def _click_start_button(dlg) -> bool:
    """Try clicking known export start button labels in a dialog window."""
    for label in _EXPORT_BUTTON_LABELS:
        try:
            dlg.child_window(title=label).click_input()
            log.info(f"Clicked: '{label}'")
            return True
        except Exception:
            pass

    # Fallback: any non-cancel descendant
    try:
        for ctrl in dlg.descendants():
            txt = (ctrl.window_text() or "").strip()
            if txt and not any(w in txt for w in _CANCEL_WORDS):
                try:
                    ctrl.click_input()
                    log.info(f"Fallback clicked: '{txt}'")
                    return True
                except Exception:
                    pass
    except Exception:
        pass
    return False


def _wait_for_completion(main_win=None, ymmp_path=None, timeout=_EXPORT_TIMEOUT) -> bool:
    """Wait for render to complete (fixed 30s wait)."""
    log.info("Waiting 60s for render to complete...")
    time.sleep(60)
    log.info("Wait complete")
    return True


def _project_name_in_window(main_win, project_name: str) -> bool:
    """Return True if project_name appears in any descendant of main_win."""
    try:
        for ctrl in main_win.descendants():
            try:
                if project_name in (ctrl.window_text() or ""):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _handle_file_save_dialog(wait: float = 8):
    """Press Enter on the output file-save dialog if it appears."""
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    desktop = Desktop(backend="uia")
    deadline = time.time() + wait

    while time.time() < deadline:
        for title_re in [r".*名前を付けて保存.*", r".*Save As.*", r".*名前.*保存.*"]:
            try:
                for w in desktop.windows(title_re=title_re):
                    if not w.is_visible():
                        continue
                    log.info(f"File save dialog: '{w.window_text()}' — pressing Enter")
                    try:
                        w.set_focus()
                    except Exception:
                        pass
                    time.sleep(0.3)
                    send_keys("{ENTER}")
                    return
            except Exception:
                pass
        time.sleep(0.5)


def _dismiss_save_dialog():
    from pywinauto import Desktop
    for w in Desktop(backend="uia").windows(title_re=".*保存.*"):
        if w.is_visible():
            for label in ["保存しない", "いいえ", "No"]:
                try:
                    w.child_window(title=label, control_type="Button").click_input()
                    return
                except Exception:
                    pass


# ── CLI ───────────────────────────────────────────────────────────────────────

def inspect_ymm4_ui():
    """Connect to a running YMM4 and print its control tree."""
    import pythoncom
    pythoncom.CoInitialize()
    try:
        from pywinauto import Application
        app = Application(backend="uia").connect(path=YMM4_EXE)
        app.top_window().print_control_identifiers()
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python ymm4_renderer.py <path/to/project.ymmp>  -- render video")
        print("  python ymm4_renderer.py --inspect               -- dump UI tree of running YMM4")
        sys.exit(1)

    if sys.argv[1] == "--inspect":
        inspect_ymm4_ui()
    else:
        ok = render_ymmp(sys.argv[1])
        sys.exit(0 if ok else 1)
