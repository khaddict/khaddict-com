# Cropping Bambu Lab P2S camera clips

The P2S's built-in camera records at 1920x1080. For clips used on the site, the
right ~384px get cropped off, down to 1536x1080.

## Command

```bash
ffmpeg -y -i input.mp4 -vf "crop=1536:1080:0:0" -c:v libx264 -crf 18 -preset medium -movflags +faststart output.mp4
```

- `crop=1536:1080:0:0`: keeps the leftmost 1536px, full 1080px height, from the
  top-left corner. Assumes a 1920x1080 source - check with `ffprobe` first if a
  clip comes from somewhere else:
  ```bash
  ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 input.mp4
  ```
- `-crf 18 -preset medium`: near-lossless re-encode, reasonable file size.
- `-movflags +faststart`: moves metadata to the front of the file so the
  browser can start playback without downloading the whole thing first.
- No `-c:a`: these clips have no audio track. If a clip does have one, add
  `-c:a copy` (or `-c:a aac` if the source audio codec isn't AAC).
