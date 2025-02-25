#!/usr/bin/env python3

import argparse
import os
import time
import subprocess
from pathlib import Path
import logging
import shutil
import stat

# Configure logging with timestamp, level, and message
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MovieFixer:
    """A utility class to process movie files, generate binary diff patches, and preserve file attributes.

    This script uses FFmpeg to fix movie files for fast seeking and generates a patch file using `diff`
    to record differences between the original and patched files. The patch file can be used to:
    - Transform the original file to the patched file: `patch <original_file> <patch_file>`
    - Revert the patched file back to the original: `patch -R <file_path> <patch_file>` (after processing,
      <file_path> contains the patched file).

    Patch files are named `<file_path>.<timestamp>.v2.diff` and stored in the same directory as the movie file.
    """

    def __init__(self, directory, recursive, force, target_gid):
        """Initialize the MovieFixer with processing options.

        Args:
            directory (str): Directory to search for movie files.
            recursive (bool): If True, search subdirectories recursively.
            force (bool): If True, process files even if patch files exist.
            target_gid (int or None): Group ID to filter files; None means no filtering.

        Raises:
            Exception: If the `diff` tool is not available on the system.
        """
        self.directory = Path(directory).resolve()
        self.recursive = recursive
        self.force = force
        self.target_gid = target_gid
        # Supported movie file extensions
        self.movie_extensions = {'.mp4', '.mkv', '.avi', '.mov'}
        # Verify that diff is available
        if not shutil.which('diff'):
            raise Exception("The 'diff' tool is required but not found in PATH")

    def has_patch_files(self, file_path):
        """Check if patch files exist for the given movie file.

        Looks for files starting with the movie filename and ending with '.v2.diff' in the same directory.

        Args:
            file_path (Path): Path to the movie file.

        Returns:
            bool: True if any patch files exist, False otherwise.
        """
        file_base = file_path.name  # e.g., "movie.mp4"
        dir_path = file_path.parent  # e.g., "/path/to"
        for filename in os.listdir(dir_path):
            if filename.startswith(file_base) and filename.endswith('.v2.diff'):
                logger.debug(f"Found patch file: {filename} for {file_path}")
                return True
        logger.debug(f"No patch files found for {file_path}")
        return False

    def generate_patch(self, original_file, patched_file):
        """Generate a binary diff patch from the original to the patched file.

        Creates a patch file named `<original_file>.<timestamp>.v2.diff`. This patch transforms
        the original file into the patched file when applied with `patch`. To revert from the
        patched file (post-processing) to the original, use `patch -R`.

        Args:
            original_file (Path): Path to the original movie file.
            patched_file (Path): Path to the FFmpeg-processed movie file.

        Returns:
            str or None: Path to the generated patch file, or None if generation fails or files are identical.
        """
        timestamp = int(time.time())
        patch_file = f"{original_file}.{timestamp}.v2.diff"
        # Command to generate a binary diff patch
        cmd = ['diff', '--binary', str(original_file), str(patched_file)]
        try:
            # Redirect diff output to the patch file
            with open(patch_file, 'w') as f:
                result = subprocess.run(cmd, stdout=f, text=True)
            # diff returns: 0 (identical), 1 (different), >1 (error)
            if result.returncode > 1:
                raise subprocess.CalledProcessError(result.returncode, cmd)
            # Preserve original file attributes on the patch file
            original_stat = os.stat(original_file)
            self.copy_file_attributes(patch_file, original_stat)
            logger.info(f"Generated patch file: {patch_file}")
            return patch_file
        except subprocess.CalledProcessError as e:
            logger.error(f"diff failed for {original_file} with exit code {e.returncode}")
            if os.path.exists(patch_file):
                os.unlink(patch_file)
            return None
        except Exception as e:
            logger.error(f"Patch generation failed for {original_file}: {e}")
            if os.path.exists(patch_file):
                os.unlink(patch_file)
            return None

    def process_file(self, file_path):
        """Process a movie file with FFmpeg and generate a patch for changes.

        Skips processing if patch files exist and force mode is off, or if the file doesn’t match
        the target group ID (if specified). Replaces the original file with the patched version
        and generates a patch file.

        Args:
            file_path (str or Path): Path to the movie file to process.
        """
        file_path = Path(file_path).resolve()
        # Skip if already processed and not in force mode
        if not self.force and self.has_patch_files(file_path):
            logger.info(f"Skipping already processed file: {file_path}")
            return
        # Validate file extension
        if file_path.suffix.lower() not in self.movie_extensions:
            return
        # Check group ID if specified
        try:
            file_stat = os.stat(file_path)
            if self.target_gid is not None and file_stat.st_gid != self.target_gid:
                logger.info(f"Skipping {file_path}: GID {file_stat.st_gid} does not match target {self.target_gid}")
                return
        except Exception as e:
            logger.error(f"Failed to stat {file_path} for GID check: {e}")
            return

        logger.info(f"Starting processing of: {file_path}")
        patched_file = file_path.with_suffix('.patched' + file_path.suffix)
        original_stat = os.stat(file_path)
        # FFmpeg command to fix the movie file
        cmd = [
            'ffmpeg', '-i', str(file_path),
            '-c', 'copy', '-map_metadata', '0',
            '-movflags', '+faststart',
            '-fflags', '+genpts+igndts',
            '-v', 'info',
            '-progress', 'pipe:1',
            '-y',  # Overwrite output file if it exists
            '-nostdin',
            str(patched_file)
        ]
        patch_file = None  # Initialize to avoid undefined variable in cleanup
        try:
            # Execute FFmpeg and stream output
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1, universal_newlines=True)
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    print(line.strip())
            return_code = process.wait(timeout=900)  # 15-minute timeout
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, cmd, output="Check console output")

            # Generate patch before replacing the original file
            patch_file = self.generate_patch(file_path, patched_file)
            if patch_file is None:
                raise Exception("Patch generation failed or files are identical")

            # Replace original file with patched version
            os.unlink(file_path)
            os.rename(patched_file, file_path)
            # Restore original file attributes
            self.copy_file_attributes(file_path, original_stat)
            logger.info(f"Successfully processed and replaced: {file_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed for {file_path} with exit code {e.returncode}. See console for details")
            if patched_file.exists():
                os.unlink(patched_file)
        except Exception as e:
            logger.error(f"Processing failed for {file_path}: {e}")
            # Cleanup temporary files on failure
            if patched_file.exists():
                os.unlink(patched_file)
            if patch_file and os.path.exists(patch_file):
                os.unlink(patch_file)

    def copy_file_attributes(self, dst_path, original_stat):
        """Copy ownership and permissions from the original file to the destination file.

        Args:
            dst_path (str or Path): Path to the file to modify.
            original_stat (os.stat_result): Stat object of the original file.

        Raises:
            PermissionError: If permission is denied during attribute setting.
            Exception: For other failures in attribute copying.
        """
        try:
            # Set ownership (UID and GID)
            os.chown(dst_path, original_stat.st_uid, original_stat.st_gid)
            # Copy read/write permissions only
            perms = original_stat.st_mode & (stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
            os.chmod(dst_path, perms)
            logger.debug(f"Set attributes on {dst_path}: UID={original_stat.st_uid}, GID={original_stat.st_gid}, Mode={oct(perms)}")
        except PermissionError as e:
            logger.error(f"Permission denied setting attributes on {dst_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to set attributes on {dst_path}: {e}")
            raise

    def run(self):
        """Process all applicable movie files in the specified directory."""
        if not self.directory.exists():
            logger.error(f"Directory does not exist: {self.directory}")
            return
        # Choose iteration method based on recursive flag
        iterator = self.directory.rglob('*') if self.recursive else self.directory.glob('*')
        for file_path in iterator:
            self.process_file(file_path)

def main():
    """Parse command-line arguments and initiate the MovieFixer."""
    parser = argparse.ArgumentParser(description='Fix movie files for fast seeking and generate diff patches')
    parser.add_argument('directory', help='Directory containing movie files')
    parser.add_argument('-r', '--recursive', action='store_true', help='Process subdirectories recursively')
    parser.add_argument('-f', '--force', action='store_true', help='Force processing even if patch files exist')
    parser.add_argument('-g', '--gid', type=int, default=None, help='Process only files with this group ID')
    args = parser.parse_args()
    fixer = MovieFixer(args.directory, args.recursive, args.force, args.gid)
    fixer.run()

if __name__ == '__main__':
    main()
