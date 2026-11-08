# Ugopichu

A desktop flipbook animation editor inspired by Ugopiku, built with Python and PySide6.

## Features

- Drawing canvas with pen and eraser
- Frame strip with add, duplicate, and delete
- Onion-skin preview
- Playback with configurable FPS
- Background music timeline (audio clips positioned by time)
- Project save/load in JSON-based `.ugopichu` format
- Hidden image sequence importer: press **Ctrl+M**, then **Ctrl+L**
  - Imports PNG, JPG, and JPEG images as frames
  - Natural filename sorting (`frame_2.png` before `frame_10.png`)
  - Existing frames are preserved; imported frames are appended

## Requirements

- Python 3.10+
- PySide6
- Pillow
- pygame (for audio preview)

## Run

```bash
python -m pip install -r requirements.txt
python main.py
```

FFmpeg is recommended for future video export support.

## Hidden menu

Press `Ctrl+M`, release, then press `Ctrl+L` to open the image-sequence importer.
