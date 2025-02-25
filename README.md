# MovieFixer Usage Guide

## Overview
MovieFixer optimizes movie files for fast seeking using FFmpeg without re-transcoding. It also generates binary patches to track changes, preserving file attributes and enabling easy reversion if needed. This is particularly useful for media players like Jellyfin, Plex, and Kodi, which may struggle with seeking and playback performance on improperly formatted files. Supported file formats include `.mp4`, `.mkv`, `.avi`, and `.mov`.

## Installation
Ensure the following dependencies are installed:
- Python 3
- FFmpeg
- `diff` (required for patch generation)

## Usage

### Basic Command
```sh
python3 movie_fixer.py /path/to/movies
```

### Options
- `-r, --recursive`  Process subdirectories recursively.
- `-f, --force`  Force processing even if patch files exist.
- `-g, --gid <group_id>`  Process only files with a specific group ID.

### Example Commands
#### Process a Directory Recursively
```sh
python3 movie_fixer.py /movies -r
```

#### Force Processing of All Files
```sh
python3 movie_fixer.py /movies -f
```

#### Process Only Files with a Specific Group ID
```sh
python3 movie_fixer.py /movies -g 1001
```

#### Combine All Options
```sh
python3 movie_fixer.py /movies -r -f -g 1001
```

## How It Works
1. **FFmpeg Processing**: Converts movie files for fast seeking using `-c copy` to avoid re-transcoding. The `-movflags +faststart` option moves the movie's metadata (moov atom) to the beginning of the file, allowing faster streaming and seeking. The `-fflags +genpts+igndts` ensures proper timestamp generation for better playback compatibility.
2. **Patch Generation**: Uses `diff --binary` to create a patch file capturing differences between the original and optimized files.
3. **File Replacement**: The original file is replaced with the optimized version while preserving metadata and attributes.
4. **Tracking**: Patch files are stored alongside the movie file to enable reversion, if needed.

## Logs and Debugging
- Logs are printed to the console in real time.
- Errors and issues are logged for troubleshooting.

## Notes
- Patch files are named `<file_path>.<timestamp>.v2.diff` and stored in the same directory as the movie file.
- To revert a processed file to its original version, use:
  ```sh
  patch -R <file_path> <patch_file>
  ```
- Ensure you have write permissions in the directory to allow file replacement and patch creation.

## Why Use MovieFixer?
Many media players struggle with playback and seeking issues caused by improper file formatting. MovieFixer eliminates these issues by ensuring files are optimized for fast seeking, improving playback performance without unnecessary re-encoding.

