# galileo-plugin-mlclouddetect

A `SafetyMonitorPort` plugin for Galileo that determines cloud cover from all-sky
camera imagery using an ML image classifier, in the style of
[mlCloudDetect](https://github.com/gordtulloch/mlCloudDetect) (GPL-3.0).

This is the **reference implementation of Galileo's plugin architecture**
(`PLUG-010`, SDD Section 4.20) — see
[docs/PSD.md](../../docs/PSD.md) Section 6.7 and
[docs/SDD.md](../../docs/SDD.md) Section 4.20/4.16 for how it fits the overall
design. It is a real, standalone, testable package; the `galileo` host
application it plugs into does not exist yet (the project is at the SRS/SDD
stage), so `galileo_plugin_api.py` is a small local stub of the interfaces the
real host will provide — see that file's docstring for what to do once
`galileo.core.devices`/`galileo.plugins` exist as code.

This is a clean-room reimplementation informed by mlCloudDetect's and
[MCP](https://github.com/gordtulloch/MCP)'s publicly documented architecture,
not a copy of their source.

## What it does

1. Locates the latest all-sky camera frame, in one of two configurable modes:
   - **`file`** — a fixed path that's continuously overwritten with the latest image.
   - **`indi_allsky_db`** — queries the most recent frame for a given camera from an
     [indi-allsky](https://github.com/aaronwmorris/indi-allsky) SQLite database
     (`image` joined to `camera` on `camera_id`, ordered by `createDate DESC`).
2. Runs a Keras image classifier (224×224 RGB, normalized to `[-1, 1]` — the common
   Teachable-Machine export convention) against the frame.
3. Debounces the result: the reported safety state only changes after
   `pending_count` consecutive consistent classifications, so a single borderline
   frame can't flip roof/safety state.
4. Reports through `SafetyMonitorPort.is_safe` / `.status`, exactly like a real
   connected weather/safety device — this plugin is a **local sensor reading**
   (a real camera pointed at the real sky), so per the design principle in SDD
   Section 4.16 it is trusted as an input to automated abort decisions, unlike an
   internet weather forecast.

## Configuration

Copy `config.example.toml` to `config.toml` and edit. See that file for both modes'
full option lists. You will need your own trained Keras model (`model_path`) and,
optionally, a `labels.txt` (one label per line, Teachable-Machine format);
`Clear`/`Cloudy` are used if no labels file is found.

## Install

```bash
pip install -e ".[inference,dev]"
```

`tensorflow` is an optional dependency (`[inference]` extra) — the plugin imports
it lazily, so the package can be installed, imported, and unit-tested without it.
Actually classifying an image requires it.

## Run the demo

```bash
python examples/demo.py path/to/frame.jpg --model keras_model.h5 --labels labels.txt
```

## Run the tests

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests cover the image-source resolution logic (file mode and a real temporary
SQLite database in `indi_allsky_db` mode) and the debounce/hysteresis logic in
`plugin.py`, using a stubbed classifier so they don't require TensorFlow or a
trained model.

## License

GPL-3.0-or-later, matching Galileo and mlCloudDetect.
