# Sources and third-party components

This source distribution preserves the project's existing preprocessing and brand assets. It does not assign a new license to third-party code, supplied model weights, or datasets. Model weights, recorded IQ, replay images, native DLLs, and installed dependency trees are excluded.

| Component | Source and retained information |
|---|---|
| IQ preprocessing | `vendor/iq_to_image.py`, supplied training-compatible reference. SHA-256: `7ae2801f7443de313374691e6ead19c25224e48dfe449aaf1d0944453bb4f85f`. File bytes are preserved. |
| WaveSentry brand | Project SVG symbol and outlined wordmark. The wordmark uses Manrope SemiBold outlines. [Manrope](https://github.com/googlefonts/manrope); SIL OFL notice in `assets/branding/Manrope-OFL.txt`. |
| Selected model, supplied separately | `model_02a_picked.pt`, SHA-256: `06b998be1d8dd85389803ba5f1704c673ba38f3fcac15044e6bf54e5ea0b088f`. Converted OpenVINO files retain source and artifact hashes locally. |
| HackRF interface | [libhackrf 2026.01.3](https://github.com/greatscottgadgets/hackrf/tree/v2026.01.3/host/libhackrf), including the sweep API and wire format. The application's receiver, PSD processing, and scheduling use these interfaces. |
| Windows native dependencies | conda-forge packages for libhackrf/libusb/libwinpthread and associated dependencies. Version, download URL and SHA-256 records are in `tools/hackrf-packages.json`; DLLs are installed separately. |
| Qt for Python | [PySide6](https://www.qt.io/qt-for-python); dependency package notices are retained in the installed environment. |
| Inference libraries | [Ultralytics](https://github.com/ultralytics/ultralytics), [PyTorch](https://github.com/pytorch/pytorch), [OpenVINO](https://github.com/openvinotoolkit/openvino). Installed optionally. |
| Numerical/image libraries | [NumPy](https://numpy.org/), [SciPy](https://scipy.org/), [Pillow](https://python-pillow.github.io/). |
| Serial transport | [pySerial](https://github.com/pyserial/pyserial). |
| CesiumJS | [Official npm distribution](https://www.npmjs.com/package/cesium), version 1.146.0. `tools/vendor_cesium.py` verifies SHA-512 and installs Build/Cesium assets, Apache-2.0 `LICENSE.md`, `ThirdParty.json` and package provenance. Downloaded files are excluded from Git. |
| Satellite imagery | [Esri World Imagery](https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer), fetched at runtime. Sources include Esri, Vantor, Earthstar Geographics and the GIS User Community. Imagery is not bundled. |

Exact Python package versions are recorded in `requirements-lock.txt`. The dependency distributions retain their upstream notices. The repository's source-only packaging does not include or relicense proprietary models or measurements.
