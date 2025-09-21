#!/usr/bin/env python3
import os
import re
import argparse
import subprocess
from pathlib import Path
from collections import defaultdict

def get_episode_groups(input_folder):
    # Pattern to handle full-width hash and flexible whitespace
    pattern = r'[＃#](\d+)-(\d+)\s*.*?\[(\d{4}-\d{2}-\d{2})\]\[.*?\]\.mp4'
    
    episode_groups = defaultdict(list)
    
    print(f"Scanning input folder: {input_folder}")
    for filename in os.listdir(input_folder):
        if filename.endswith('.mp4'):
            match = re.match(pattern, filename, re.UNICODE)
            if match:
                episode_num, part_num, date = match.groups()
                episode_groups[(episode_num, date)].append(filename)
                print(f"Found matching file: {filename} (Episode: {episode_num}, Part: {part_num}, Date: {date})")
            else:
                print(f"Skipping file (no match): {filename}")
    
    if not episode_groups:
        print("No matching files found in the input folder.")
    else:
        print(f"Found {len(episode_groups)} episode groups: {list(episode_groups.keys())}")
    
    return episode_groups

def create_ffmpeg_concat_file(files, output_path):
    concat_file = output_path / 'concat_list.txt'
    with open(concat_file, 'w', encoding='utf-8') as f:
        for file in files:
            f.write(f"file '{file}'\n")
    print(f"Created concat file: {concat_file}")
    return concat_file

def concatenate_videos(input_folder, custom_tag):
    input_path = Path(input_folder)
    output_folder = input_path / 'merged'
    
    print(f"Creating output folder: {output_folder}")
    output_folder.mkdir(exist_ok=True)
    
    episode_groups = get_episode_groups(input_folder)
    
    if not episode_groups:
        print("No episode groups to process. Exiting.")
        return
    
    for (episode_num, date), files in episode_groups.items():
        print(f"Processing episode {episode_num} (date: {date}) with files (before sorting): {files}")
        # Sort files by part number
        try:
            # Use a more specific regex to extract part number
            files.sort(key=lambda x: int(re.match(r'[＃#]\d+-(\d+)', x, re.UNICODE).group(1)))
            print(f"Sorted files for episode {episode_num}: {files}")
        except (AttributeError, ValueError) as e:
            print(f"Error sorting files for episode {episode_num}: {e}")
            print(f"Skipping episode {episode_num} due to sorting failure.")
            continue
        
        output_file = output_folder / f"{custom_tag}_E{episode_num}_merged_{date}.mkv"
        concat_file = create_ffmpeg_concat_file([input_path / f for f in files], output_folder)
        
        ffmpeg_cmd = [
            'ffmpeg',
            '-y',  # Auto-overwrite
            '-f', 'concat',
            '-safe', '0',
            '-i', str(concat_file),
            '-map', '0',
            '-c', 'copy',
            str(output_file)
        ]
        
        print(f"Running FFmpeg command: {' '.join(ffmpeg_cmd)}")
        try:
            result = subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
            print(f"Successfully created: {output_file}")
            print(f"FFmpeg output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"Error processing episode {episode_num}: {e}")
            print(f"FFmpeg error output: {e.stderr}")
        except FileNotFoundError:
            print("Error: FFmpeg not found. Please ensure FFmpeg is installed and in your PATH.")
        finally:
            concat_file.unlink()
            print(f"Cleaned up concat file: {concat_file}")

def main():
    parser = argparse.ArgumentParser(description='Concatenate video files with similar episode numbers')
    parser.add_argument('input_folder', help='Input folder containing video files')
    parser.add_argument('custom_tag', help='Custom tag for output filename')
    
    args = parser.parse_args()
    
    input_folder = os.path.abspath(args.input_folder)
    if not os.path.exists(input_folder):
        print(f"Error: Input folder '{input_folder}' does not exist")
        return
    
    print(f"Starting processing with input folder: {input_folder}, custom tag: {args.custom_tag}")
    concatenate_videos(input_folder, args.custom_tag)

if __name__ == '__main__':
    main()