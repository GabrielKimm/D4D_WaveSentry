"""WaveSentry desktop entry point; also provides a reproducible headless check."""
import argparse
import multiprocessing
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--seconds", type=float, default=15)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--survey", action="store_true", help="Adaptive RF observation with selectable antenna profile")
    modes.add_argument('--demo', action='store_true', help='Continuous synthetic drone monitoring; no RF hardware')
    parser.add_argument('--demo-site', choices=['airbase', 'facility', 'stage'], default='airbase')
    parser.add_argument("--survey-range", help="Integer MHz LOW:HIGH, within 1:6000")
    parser.add_argument("--survey-profile", choices=["antenna_24_5", "full", "custom"],
                        help="Default: 2.4/5GHz antenna. Full-band remains selectable.")
    parser.add_argument('--survey-channel-mhz', type=int, choices=[10,20])
    parser.add_argument("--environment-label", default="실측 환경 미확인")
    parser.add_argument("--autostart", action="store_true")
    parser.add_argument("--backend", choices=["AUTO", "GPU", "CPU", "TORCH"])
    parser.add_argument("--screenshot", type=Path, help="Save a rendering of this app's own widget after 8 s")
    parser.add_argument("--screenshot-after", type=float, default=8, help="Seconds after GUI start to save its own rendering")
    parser.add_argument("--quit-after", type=float)
    args = parser.parse_args()
    if args.demo and args.headless:
        parser.error('--demo is a GUI mode; omit --headless')
    from dataclasses import replace
    from d4d.config import read_settings
    settings = read_settings()
    if args.backend:
        settings = replace(settings, backend=args.backend)
    if args.survey_profile:
        settings = replace(settings, survey_profile=args.survey_profile)
    if args.survey_channel_mhz:
        settings = replace(settings, survey_channel_mhz=args.survey_channel_mhz)
    if args.survey_range:
        try:
            low, high = map(int, args.survey_range.split(":"))
            settings = replace(settings, survey_low=low, survey_high=high, survey_profile="custom")
        except (ValueError, TypeError):
            parser.error("--survey-range must be integer MHz LOW:HIGH within 1:6000")
    if args.headless:
        import json
        # Windows redirected consoles can default to cp949; status labels include Unicode.
        if sys.stdout is not None and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        from dataclasses import replace
        from d4d.config import read_settings
        from d4d.engine import Engine
        from d4d.survey_engine import SurveyEngine
        cls = SurveyEngine if args.survey else Engine
        engine = cls(settings, "replay" if args.replay else "live", on_status=lambda s: print(json.dumps(s, ensure_ascii=False), flush=True))
        engine.environment_label = args.environment_label
        engine.request_snapshot()
        if args.seconds <= 0:
            parser.error("--seconds must be positive")
        engine.run(args.seconds)
        print(json.dumps(engine.summary, indent=2), flush=True)
        return 1 if engine.summary.get("error") else 0
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QLockFile
    from d4d.config import ROOT
    from d4d.gui import MainWindow
    from d4d.branding import PRODUCT_NAME, app_icon
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WaveSentry.RFObservatory.Desktop")
    app = QApplication(sys.argv[:1])
    app.setApplicationName(PRODUCT_NAME)
    app.setOrganizationName("D4D")
    app.setWindowIcon(app_icon())
    lock = QLockFile(str(ROOT / "runtime/desktop.lock"))
    (ROOT / "runtime").mkdir(exist_ok=True)
    if not lock.tryLock(50):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, PRODUCT_NAME, f"{PRODUCT_NAME}가 이미 실행 중입니다.")
        return 0
    window = MainWindow()
    window.settings = settings
    window.environment_label = args.environment_label
    if args.replay:
        window.mode.setCurrentIndex(1)
    if args.survey:
        window.mode.setCurrentIndex(2)
    if args.demo:
        window.demo_site.setCurrentIndex(window.demo_site.findData(args.demo_site))
        window.mode.setCurrentIndex(3)
    window.show()
    if args.autostart and not args.demo:
        QTimer.singleShot(200, window.toggle)
    if args.screenshot:
        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
        QTimer.singleShot(max(0,int(args.screenshot_after*1000)), lambda: window.grab().save(str(args.screenshot)))
    if args.quit_after:
        QTimer.singleShot(int(args.quit_after * 1000), window.close)
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    # pythonw has no stderr console; keep startup errors reviewable.
    import traceback
    try:
        raise SystemExit(main())
    except Exception:
        path = Path(__file__).resolve().parent / "runtime/startup-error.log"
        path.parent.mkdir(exist_ok=True)
        path.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.stderr:
            traceback.print_exc()
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"앱 시작 오류입니다.\n{path}", "WaveSentry", 0x10)
        raise SystemExit(1)
