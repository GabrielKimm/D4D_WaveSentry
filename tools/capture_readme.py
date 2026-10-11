"""Capture the actual Qt demo widgets as compact README animations.

Use the native Windows Qt platform for system fonts. The scenario clock is
stepped at 10 fps; no RF, private model, or USB device is used.
"""
import io
import json
import os
from pathlib import Path
import sys

os.environ['WAVESENTRY_DEMO_MAP'] = 'schematic'
os.environ['D4D_NU87_DISABLED'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtWidgets import QApplication
from d4d.gui import MainWindow

WIDTH, HEIGHT, FPS = 1120, 720, 10


def capture(window):
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not window.grab().save(buffer, 'PNG'):
        raise RuntimeError('Qt widget capture failed')
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert('RGB').resize(
        (WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def encode(name, frames):
    # A shared palette keeps stationary UI text stable between frames.
    samples = frames[::max(1, len(frames) // 8)]
    # Build the palette at full resolution: downsampling first loses the bright
    # colors of thin text, selection outlines, and small warning indicators.
    atlas = Image.new('RGB', (WIDTH * 3, HEIGHT * ((len(samples) + 2) // 3)))
    for index, frame in enumerate(samples):
        atlas.paste(frame, ((index % 3) * WIDTH, (index // 3) * HEIGHT))
    palette = atlas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]
    destination = ROOT / 'docs/media' / f'{name}.gif'
    destination.parent.mkdir(parents=True, exist_ok=True)
    indexed[0].save(destination, save_all=True, append_images=indexed[1:],
                    duration=1000 // FPS, loop=0, optimize=True, disposal=1)
    with Image.open(destination) as result:
        duration = 0
        for index in range(result.n_frames):
            result.seek(index)
            duration += result.info['duration']
        assert result.size == (WIDTH, HEIGHT) and result.n_frames > 1
        assert duration == len(frames) * (1000 // FPS)
    if destination.stat().st_size > 8_000_000:
        raise RuntimeError('README animation exceeds the source distribution size limit')
    return dict(file=destination.name, frames=len(frames), duration_ms=duration,
                bytes=destination.stat().st_size)


def main():
    if sys.platform != 'win32' or os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        raise RuntimeError('Use the native Windows Qt platform for readable font capture')
    app = QApplication.instance() or QApplication([])
    window = MainWindow(False)
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.resize(1400, 900)
    window.show()
    window.reset_layout()
    window.mode.setCurrentIndex(3)
    demo = window.demo_panel
    demo.timer.stop()
    window.timer.stop()
    now = [0.0]
    demo.model.clock = lambda: now[0]
    demo.model.rng.seed(17)
    demo.model.reset_scenario()
    app.processEvents()
    output = ROOT / 'output/readme_capture'
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    try:
        frames = []
        for index in range(130):
            now[0] = index / FPS
            demo.refresh()
            window.tick()
            app.processEvents()
            frames.append(capture(window))
        for index in (0, 35, 85, 120):
            frames[index].save(output / f'tracking-{index:03d}.png')
        reports.append(encode('tracking', frames))

        window.demo_site.setCurrentIndex(window.demo_site.findData('facility'))
        demo.model.rng.seed(17)
        demo.model.reset_scenario()
        now[0] += 8.5
        demo.refresh()
        frames = []
        for index in range(110):
            now[0] += 1 / FPS
            if index == 10:
                demo.select('F-02')
            elif index == 25:
                demo.select('H-01')
            elif index == 35:
                demo.rf_toggle.setChecked(True)
            elif index == 55:
                demo.toggle()
            elif index == 75:
                demo.toggle()
            elif index == 90:
                demo.rf_toggle.setChecked(False)
                demo.acknowledge()
            demo.refresh()
            window.tick()
            app.processEvents()
            frames.append(capture(window))
        for index in (15, 45, 65, 95):
            frames[index].save(output / f'workspace-{index:03d}.png')
        reports.append(encode('workspace', frames))
        assert window.engine is None and window.thread is None
        (output / 'capture.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
        print(json.dumps(reports, indent=2))
    finally:
        window.close()


if __name__ == '__main__':
    main()
