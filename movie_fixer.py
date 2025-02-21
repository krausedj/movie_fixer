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

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MovieFixer:
    def __init__(self, directory, recursive, data_file, target_gid):
        self.directory = Path(directory).resolve()
        self.recursive = recursive
        self.data_file = Path(data_file)
        self.target_gid = target_gid
        self.processed_files = self.load_processed_files()
        self.movie_extensions = {'.mp4', '.mkv', '.avi', '.mov'}
        self.patch_tool = self.detect_patch_tool()

    def detect_patch_tool(self):
        """Detect available binary patch tool."""
        for tool in ['bsdiff', 'xdelta3', 'diff']:
            if shutil.which(tool):
                logger.info(f"Using {tool} for patch generation")
                return tool
        raise Exception("No suitable patch tool found (bsdiff, xdelta3, or diff required)")

    def load_processed_files(self):
        """Load previously processed files from the persistent data file."""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logger.error(f"Corrupted data file {self.data_file}, starting fresh")
        return {}

    def save_processed_files(self):
        """Save processed files to persistent data file."""
        with open(self.data_file, 'w') as f:
            json.dump(self.processed_files, f, indent=2)

    def generate_patch(self, original_file, patched_file):
        """Generate a reverse binary patch file with timestamp in filename."""
        timestamp = int(time.time())
        patch_ext = '.patch' if self.patch_tool in ['bsdiff', 'xdelta3'] else '.diff'
        patch_file = f"{original_file}.{timestamp}{patch_ext}"
        original_stat = os.stat(original_file)
        
        try:
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
                if result.returncode > 1:
                    raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
                if not result.stdout:
                    raise Exception("diff produced no output")
                with open(patch_file, 'w') as f:
                    f.write(result.stdout)

            if not os.path.exists(patch_file) or os.path.getsize(patch_file) == 0:
                raise Exception("Generated patch file is missing or empty")

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
        """Process a single movie file."""
        file_path = Path(file_path).resolve()
        file_key = str(file_path)

        if file_key in self.processed_files:
            logger.info(f"Skipping already processed file: {file_path}")
            return

        if file_path.suffix.lower() not in self.movie_extensions:
            return

        try:
            file_stat = os.stat(file_path)
            if self.target_gid is not None and file_stat.st_gid != self.target_gid:
                logger.info(f"Skipping {file_path}: GID {file_stat.st_gid} does not match target {self.target_gid}")
                return
        except Exception as e:
            logger.error(f"Failed to check GID for {file_path}: {e}")
            return

        logger.info(f"Processing: {file_path}")
        patched_file = file_path.with_suffix('.patched' + file_path.suffix)
        original_stat = os.stat(file_path)

        cmd = [
            'ffmpeg', '-i', str(file_path),
            '-c', 'copy', '-map_metadata', '0',
            '-movflags', '+faststart',
            '-v', 'info',
            '-progress', 'pipe:1',
            '-y',
            '-nostdin',
            str(patched_file)
        ]

        try:
            logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    print(line.strip())

            try:
                return_code = process.wait(timeout=300)
                if return_code != 0:
                    raise subprocess.CalledProcessError(return_code, cmd, output="See console output above")
            except subprocess.TimeoutExpired:
                process.kill()
                raise Exception(f"FFmpeg timed out after 300 seconds for {file_path}")

            patch_file = self.generate_patch(file_path, patched_file)
            if not patch_file:
                raise Exception("Patch generation failed")

            os.unlink(file_path)
            os.rename(patched_file, file_path)
            self.copy_file_attributes(file_path, original_stat)

            file_info = {
                'original_file': str(file_path),
                'patch_file': patch_file,
                'patch_tool': self.patch_tool,
                'timestamp': time.time()
            }

            self.processed_files[file_key] = file_info
            self.save_processed_files()
            logger.info(f"Successfully processed: {file_path}")

        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg failed for {file_path} with exit code {e.returncode}. See console output for details.")
            if patched_file.exists():
                os.unlink(patched_file)
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")
            if patched_file.exists():
                os.unlink(patched_file)
            if patch_file and os.path.exists(patch_file):
                os.unlink(patch_file)

    def copy_file_attributes(self, dst_path, original_stat):
        """Copy only ownership and read/write permissions from original_stat to dst_path."""
        try:
            os.chown(dst_path, original_stat.st_uid, original_stat.st_gid)
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
        """Main execution method."""
        if not self.directory.exists():
            logger.error(f"Directory {self.directory} does not exist")
            return

        if self.recursive:
            for file_path in self.directory.rglob('*'):
                self.process_file(file_path)
        else:
            for file_path in self.directory.glob('*'):
                self.process_file(file_path)

def main():
    parser = argparse.ArgumentParser(description='Fix movie files for fastseek')
    parser.add_argument('directory', help='Directory to search for movie files')
    parser.add_argument('-r', '--recursive', action='store_true',
                       help='Search recursively through subdirectories')
    parser.add_argument('-d', '--data-file', default='movie_fixer_data.json',
                       help='Persistent data file location')
    parser.add_argument('-g', '--gid', type=int, default=None,
                       help='Only process files with this group ID')

    args = parser.parse_args()

    fixer = MovieFixer(args.directory, args.recursive, args.data_file, args.gid)
    fixer.run()

if __name__ == '__main__':
    main()
