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
    """A utility class to process movie files and generate reverse binary diff patches using xdelta3.

    This script uses FFmpeg to fix movie files for fast seeking and generates a reverse patch file
    using `xdelta3` to allow reverting from the patched file back to the original. The reverse patch
    file transforms the patched file to the original file when applied with 
    `xdelta3 -d -s <patched_file> <patch_file> <original_file>`.

    Patch files are named `<file_path>.<timestamp>.xdelta3` and stored in the same directory as the movie file.
    """

    def __init__(self, directory, recursive, force, target_gid):
        """Initialize the MovieFixer with processing options.

        Args:
            directory (str): Directory to search for movie files.
            recursive (bool): If True, search subdirectories recursively.
            force (bool): If True, process files even if patch files exist.
            target_gid (int or None): Group ID to filter files; None means no filtering.

        Raises:
            Exception: If `xdelta3` tool is not available on the system.
        """
        self.directory = Path(directory).resolve()
        self.recursive = recursive
        self.force = force
        self.target_gid = target_gid
        # Supported movie file extensions
        self.movie_extensions = {'.mp4', '.mkv', '.avi', '.mov'}
        # Verify that xdelta3 is available
        if not shutil.which('xdelta3'):
            raise Exception("The 'xdelta3' tool is required but not found in PATH")

    def has_patch_files(self, file_path):
        """Check if patch files exist for the given movie file.

        Looks for files starting with the movie filename and ending with '.xdelta3' in the same directory.

        Args:
            file_path (Path): Path to the movie file.

        Returns:
            bool: True if any patch files exist, False otherwise.
        """
        file_base = file_path.name
        dir_path = file_path.parent
        for filename in os.listdir(dir_path):
            if filename.startswith(file_base) and filename.endswith('.xdelta3'):
                logger.debug(f"Found patch file: {filename} for {file_path}")
                return True
        logger.debug(f"No patch files found for {file_path}")
        return False

    def generate_reverse_patch(self, original_file, patched_file):
        """Generate a reverse binary diff patch from the patched file to the original file.

        Creates a patch file named `<original_file>.<timestamp>.xdelta3`. This patch transforms
        the patched file back to the original file when applied with 
        `xdelta3 -d -s <patched_file> <patch_file> <original_file>`.

        Args:
            original_file (Path): Path to the original movie file.
            patched_file (Path): Path to the FFmpeg-processed movie file.

        Returns:
            str or None: Path to the generated patch file, or None if generation fails or files are identical.
        """
        timestamp = int(time.time())
        patch_file = f"{original_file}.{timestamp}.xdelta3"
        # Command to generate a reverse binary diff patch (patched -> original)
        cmd = ['xdelta3', '-e', '-s', str(patched_file), str(original_file), str(patch_file)]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            # Check if patch file was created and is non-empty
            if not os.path.exists(patch_file) or os.path.getsize(patch_file) == 0:
                logger.warning(f"No differences found between {original_file} and {patched_file}")
                if os.path.exists(patch_file):
                    os.unlink(patch_file)
                return None
            # Preserve original file attributes on the patch file
            original_stat = os.stat(original_file)
            self.copy_file_attributes(patch_file, original_stat)
            logger.info(f"Generated reverse patch file: {patch_file}")
            return patch_file
        except subprocess.CalledProcessError as e:
            logger.error(f"xdelta3 failed for {original_file} with exit code {e.returncode}: {e.stderr}")
            if os.path.exists(patch_file):
                os.unlink(patch_file)
            return None
        except Exception as e:
            logger.error(f"Reverse patch generation failed for {original_file}: {e}")
            if os.path.exists(patch_file):
                os.unlink(patch_file)
            return None

    def process_file(self, file_path):
        """Process a movie file with FFmpeg and generate a reverse patch for reverting changes.

        Skips processing if patch files exist and force mode is off, or if the file doesn’t match
        the target group ID (if specified). Replaces the original file with the patched version
        and generates a reverse patch file.

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
            '-map', '0',
            '-c', 'copy', '-map_metadata', '0',
            '-movflags', '+faststart',
            '-fflags', '+genpts+igndts',
            '-v', 'info',
            '-progress', 'pipe:1',
            '-y',  # Overwrite output file if it exists
            '-nostdin',
            str(patched_file)
        ]
        patch_file = None
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

            # Generate reverse patch before replacing the original file
            patch_file = self.generate_reverse_patch(original_file=file_path, patched_file=patched_file)
            if patch_file is None:
                raise Exception("Reverse patch generation failed or files are identical")

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
    parser = argparse.ArgumentParser(description='Fix movie files for fast seeking and generate reverse xdelta3 patches')
    parser.add_argument('directory', help='Directory containing movie files')
    parser.add_argument('-r', '--recursive', action='store_true', help='Process subdirectories recursively')
    parser.add_argument('-f', '--force', action='store_true', help='Force processing even if patch files exist')
    parser.add_argument('-g', '--gid', type=int, default=None, help='Process only files with this group ID')
    args = parser.parse_args()
    fixer = MovieFixer(args.directory, args.recursive, args.force, args.gid)
    fixer.run()

if __name__ == '__main__':
    main()