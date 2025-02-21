#!/usr/bin/env python3

import argparse
import os
import time
import subprocess
import json
from pathlib import Path
import logging
import shutil
import stat

# Setup logging with timestamp, level, and message format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MovieFixer:
    """A class to process movie files, generate patches, and maintain file attributes."""
    
    def __init__(self, directory, recursive, data_file, target_gid):
        """Initialize the MovieFixer with directory and processing options.

        Args:
            directory (str): The directory to search for movie files.
            recursive (bool): Whether to search subdirectories recursively.
            data_file (str): Path to the JSON file storing processed file data.
            target_gid (int or None): Group ID to filter files; None means no filtering.
        """
        # Resolve the directory path to an absolute path
        self.directory = Path(directory).resolve()
        self.recursive = recursive
        self.data_file = Path(data_file)
        self.target_gid = target_gid
        # Load previously processed files or start with an empty dict
        self.processed_files = self.load_processed_files()
        # Define supported movie file extensions
        self.movie_extensions = {'.mp4', '.mkv', '.avi', '.mov'}
        # Detect which patch tool is available
        self.patch_tool = self.detect_patch_tool()

    def detect_patch_tool(self):
        """Detect which binary patch tool is available on the system.

        Returns:
            str: Name of the detected patch tool ('bsdiff', 'xdelta3', or 'diff').

        Raises:
            Exception: If no suitable patch tool is found.
        """
        # Check for available patch tools in order of preference
        for tool in ['bsdiff', 'xdelta3', 'diff']:
            if shutil.which(tool):
                logger.info(f"Using {tool} for patch generation")
                return tool
        raise Exception("No suitable patch tool found (bsdiff, xdelta3, or diff required)")

    def load_processed_files(self):
        """Load the dictionary of previously processed files from the data file.

        Returns:
            dict: Dictionary of processed files, empty if file doesn't exist or is corrupted.
        """
        # Check if the data file exists
        if self.data_file.exists():
            try:
                # Attempt to load the JSON data
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Corrupted data file {self.data_file}, starting fresh")
        # Return empty dict if file doesn't exist or is invalid
        return {}

    def save_processed_files(self):
        """Save the processed files dictionary to the persistent data file."""
        # Write the processed files dict to the JSON file with indentation
        with open(self.data_file, 'w') as f:
            json.dump(self.processed_files, f, indent=2)

    def generate_patch(self, original_file, patched_file):
        """Generate a reverse binary patch file with a timestamped filename.

        Args:
            original_file (str or Path): Path to the original movie file.
            patched_file (str or Path): Path to the FFmpeg-processed movie file.

        Returns:
            str or None: Path to the generated patch file, or None if generation fails.
        """
        # Generate a unique timestamp for the patch filename
        timestamp = int(time.time())
        patch_ext = '.patch' if self.patch_tool in ['bsdiff', 'xdelta3'] else '.diff'
        patch_file = f"{original_file}.{timestamp}{patch_ext}"
        # Get original file stats for attribute copying
        original_stat = os.stat(original_file)
        
        try:
            # Select and execute the appropriate patch tool
            if self.patch_tool == 'bsdiff':
                cmd = ['bsdiff', str(original_file), str(patched_file), patch_file]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            elif self.patch_tool == 'xdelta3':
                cmd = ['xdelta3', '-e', '-s', str(original_file), str(patched_file), patch_file]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            else:  # diff
                cmd = ['diff', '--binary', str(original_file), str(patched_file)]
                logger.debug(f"Running diff command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                # diff returns 1 for differences, >1 for errors
                if result.returncode > 1:
                    raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
                if not result.stdout:
                    raise Exception("diff produced no output")
                # Write diff output to file
                with open(patch_file, 'w') as f:
                    f.write(result.stdout)

            # Verify patch file was created and has content
            if not os.path.exists(patch_file) or os.path.getsize(patch_file) == 0:
                raise Exception("Generated patch file is missing or empty")

            # Apply original file's ownership and permissions to patch
            self.copy_file_attributes(patch_file, original_stat)
            
            logger.info(f"Generated patch: {patch_file}")
            return patch_file
        except subprocess.CalledProcessError as e:
            logger.error(f"Patch generation failed for {original_file} with command {' '.join(cmd)}")
            logger.error(f"Exit code: {e.returncode}")
            logger.error(f"Stdout: {e.stdout}")
            logger.error(f"Stderr: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating patch for {original_file}: {e}")
            return None

    def process_file(self, file_path):
        """Process a single movie file with FFmpeg and generate a patch.

        Args:
            file_path (str or Path): Path to the movie file to process.
        """
        # Resolve the file path to an absolute path
        file_path = Path(file_path).resolve()
        file_key = str(file_path)

        # Skip if file was already processed
        if file_key in self.processed_files:
            logger.info(f"Skipping already processed file: {file_path}")
            return

        # Check if file has a supported movie extension
        if file_path.suffix.lower() not in self.movie_extensions:
            return

        # Verify GID if specified
        try:
            file_stat = os.stat(file_path)
            if self.target_gid is not None and file_stat.st_gid != self.target_gid:
                logger.info(f"Skipping {file_path}: GID {file_stat.st_gid} does not match target {self.target_gid}")
                return
        except Exception as e:
            logger.error(f"Failed to check GID for {file_path}: {e}")
            return

        logger.info(f"Processing: {file_path}")
        # Create temporary output filename
        patched_file = file_path.with_suffix('.patched' + file_path.suffix)
        # Store original file stats
        original_stat = os.stat(file_path)

        # FFmpeg command to optimize file for fast seeking
        cmd = [
            'ffmpeg', '-i', str(file_path),
            '-c', 'copy', '-map_metadata', '0',
            '-movflags', '+faststart',
            '-v', 'info',
            '-progress', 'pipe:1',
            '-y',          # Overwrite output without prompting
            '-nostdin',    # Disable interactive input
            str(patched_file)
        ]

        try:
            logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")
            # Launch FFmpeg process with real-time output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Stream FFmpeg output to console
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    print(line.strip())

            # Wait for FFmpeg to complete with a timeout
            try:
                return_code = process.wait(timeout=300)
                if return_code != 0:
                    raise subprocess.CalledProcessError(return_code, cmd, output="See console output above")
            except subprocess.TimeoutExpired:
                process.kill()
                raise Exception(f"FFmpeg timed out after 300 seconds for {file_path}")

            # Generate patch file before modifying original
            patch_file = self.generate_patch(file_path, patched_file)
            if not patch_file:
                raise Exception("Patch generation failed")

            # Replace original file with processed version
            os.unlink(file_path)
            os.rename(patched_file, file_path)
            # Restore original ownership and permissions
            self.copy_file_attributes(file_path, original_stat)

            # Store processing details
            file_info = {
                'original_file': str(file_path),
                'patch_file': patch_file,
                'patch_tool': self.patch_tool,
                'timestamp': time.time()
            }

            # Update and save processed files record
            self.processed_files[file_key] = file_info
            self.save_processed_files()
            logger.info(f"Successfully processed: {file_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed for {file_path} with exit code {e.returncode}. See console output for details.")
            # Clean up temporary file on failure
            if patched_file.exists():
                os.unlink(patched_file)
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            # Clean up both temporary and patch files on failure
            if patched_file.exists():
                os.unlink(patched_file)
            if patch_file and os.path.exists(patch_file):
                os.unlink(patch_file)

    def copy_file_attributes(self, dst_path, original_stat):
        """Copy ownership and read/write permissions from original_stat to dst_path.

        Args:
            dst_path (str or Path): Destination file path to apply attributes to.
            original_stat (os.stat_result): Stat object containing original file attributes.

        Raises:
            PermissionError: If the operation lacks sufficient permissions.
            Exception: For other unexpected errors during attribute copying.
        """
        try:
            # Set UID and GID from original file
            os.chown(dst_path, original_stat.st_uid, original_stat.st_gid)
            # Filter to only read/write permissions
            perms = original_stat.st_mode & (stat.S_IRUSR | stat.S_IWUSR | 
                                          stat.S_IRGRP | stat.S_IWGRP | 
                                          stat.S_IROTH | stat.S_IWOTH)
            os.chmod(dst_path, perms)
            logger.debug(f"Copied attributes to {dst_path}: UID={original_stat.st_uid}, GID={original_stat.st_gid}, Mode={oct(perms)}")
        except PermissionError as e:
            logger.error(f"Permission denied when setting attributes on {dst_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to copy attributes to {dst_path}: {e}")
            raise

    def run(self):
        """Execute the movie fixing process on all applicable files in the directory."""
        # Verify the directory exists before proceeding
        if not self.directory.exists():
            logger.error(f"Directory {self.directory} does not exist")
            return

        # Process files recursively or in top-level directory only
        if self.recursive:
            for file_path in self.directory.rglob('*'):
                self.process_file(file_path)
        else:
            for file_path in self.directory.glob('*'):
                self.process_file(file_path)

def main():
    """Parse command-line arguments and run the MovieFixer."""
    # Set up argument parser with description and options
    parser = argparse.ArgumentParser(description='Fix movie files for fastseek')
    parser.add_argument('directory', help='Directory to search for movie files')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='Search recursively through subdirectories')
    parser.add_argument('-d', '--data-file', default='movie_fixer_data.json',
                        help='Persistent data file location')
    parser.add_argument('-g', '--gid', type=int, default=None,
                        help='Only process files with this group ID')

    # Parse command-line arguments
    args = parser.parse_args()

    # Create and run the MovieFixer instance
    fixer = MovieFixer(args.directory, args.recursive, args.data_file, args.gid)
    fixer.run()

if __name__ == '__main__':
    main()
