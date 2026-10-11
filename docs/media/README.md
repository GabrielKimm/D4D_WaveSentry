# Interface previews

All animations use actual application renderers with synthetic inputs. They contain no model weights, measured IQ, replay samples, or device identifiers.

| Asset | Renderer | Size | Duration |
| :--- | :--- | :--- | :--- |
| `tracking.gif` | Windows Qt demo widgets | 1120 × 720 | 13 seconds |
| `workspace.gif` | Windows Qt demo widgets | 1120 × 720 | 11 seconds |
| `halo-signal.gif` | Halo LVGL firmware UI | 1120 × 600 | 15 seconds |
| `halo-map.gif` | Halo LVGL firmware UI | 1120 × 600 | 20 seconds |

The Windows capture script is `tools/capture_readme.py`.

## Halo capture

Captured from the Halo firmware source snapshot on October 11, 2026, using its browser simulator adapter and the current `d4d_ui`, `d4d_map`, `d4d_model`, and asset sources. The firmware was compiled to WebAssembly and run with WASI. Its native 466 × 466 RGB565 framebuffer was converted to RGB and placed beside English stage captions. The UI itself was not redrawn. Both GIFs use 100 ms frames and loop continuously.

The signal capture injects valid WSL1 clear/detected packets through the firmware link parser, plus synthetic RSSI and packet-age values. A 22-second warm-up fills the rolling chart before recording. Detection begins at 3.5 seconds, acknowledgment occurs at 9.2 seconds, and clear input returns at 11.5 seconds. RSSI is Wi-Fi link strength, not a drone detection score.

The map capture runs the firmware's built-in contact scenario. Actual LVGL touch events pan in two directions, select the zoom control, return home, and acknowledge the selected contact. Contacts and displayed range/bearing continue updating during capture. This is a demonstration of UI behavior, not live target geolocation. The physical firmware enables Wi-Fi reception only on its main screen.

Halo firmware and its build dependencies are maintained separately and are not required to run the Windows app. The WebAssembly binary, intermediate frames, local build files, and capture logs are excluded from this source distribution.
