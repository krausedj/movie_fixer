# MovieFixer Usage Guide

## Overview
MovieFixer optimizes movie files for fast seeking by using FFmpeg without re-transcoding and generates binary patches to track changes. This is particularly useful for media players like Jellyfin, Plex, and Kodi, which may struggle with seeking and playback performance on improperly formatted files. It supports `.mp4`, `.mkv`, `.avi`, and `.mov` files.

## Installation
Ensure the following dependencies are installed:
- Python 3
- FFmpeg
- One of the following patching tools: `bsdiff`, `xdelta3`, or `diff`

## Usage

### Basic Command
```sh
python3 movie_fixer.py /path/to/movies
```

### Options
- `-r, --recursive`  Search subdirectories for movie files.
- `-d, --data-file <file>`  Specify a JSON file to store processed file data (default: `movie_fixer_data.json`).
- `-g, --gid <group_id>`  Process only files with a specific group ID.

### Example Commands

#### Process a Directory Recursively
```sh
python3 movie_fixer.py /movies -r
```

#### Use a Custom Data File
```sh
python3 movie_fixer.py /movies -d custom_data.json
```

#### Process Only Files with a Specific Group ID
```sh
python3 movie_fixer.py /movies -g 1001
```

#### Combine All Options
```sh
python3 movie_fixer.py /movies -r -d custom_data.json -g 1001
```

## How It Works
1. **FFmpeg Processing**: Converts movie files for fast seeking.
2. **Patch Generation**: Uses `bsdiff`, `xdelta3`, or `diff` to create a patch.
3. **File Replacement**: The original file is replaced with the optimized version while preserving metadata.
4. **Tracking**: Processed files are recorded in a JSON file to prevent duplicate processing.

## Logs and Debugging
- Logs are printed to the console.
- Errors and issues are logged for troubleshooting.

## Notes
- Ensure you have write permissions in the directory.
- Patch files are created to allow restoring the original file if needed.


