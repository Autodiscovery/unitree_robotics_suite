#!/usr/bin/env python3
"""
Renumber episode folders to be sequential starting from episode_0000.
This script handles the renaming in two phases to avoid name collisions.
"""

import os
import sys
from pathlib import Path


def renumber_episodes(data_dir, dry_run=False):
    """
    Renumber episode folders to be sequential.
    
    Args:
        data_dir: Path to the directory containing episode folders
        dry_run: If True, only print what would be done without actually renaming
    """
    data_path = Path(data_dir)
    
    if not data_path.exists():
        print(f"Error: Directory {data_dir} does not exist!")
        return False
    
    # Find all episode folders
    episode_folders = []
    for item in data_path.iterdir():
        if item.is_dir() and item.name.startswith('episode_'):
            try:
                episode_num = int(item.name.split('_')[1])
                episode_folders.append((episode_num, item))
            except (ValueError, IndexError):
                print(f"Warning: Skipping invalid folder name: {item.name}")
    
    # Sort by episode number
    episode_folders.sort(key=lambda x: x[0])
    
    if not episode_folders:
        print("No episode folders found!")
        return False
    
    print(f"\nFound {len(episode_folders)} episodes")
    print("\nRenaming plan:")
    print("-" * 60)
    
    # Show the renaming plan
    for new_idx, (old_num, old_path) in enumerate(episode_folders):
        new_name = f"episode_{new_idx:04d}"
        print(f"  {old_path.name:20s} -> {new_name}")
    
    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return True
    
    print("\n" + "=" * 60)
    print("Starting renaming process...")
    print("=" * 60)
    
    # Phase 1: Rename to temporary names to avoid conflicts
    print("\nPhase 1: Renaming to temporary names...")
    temp_names = []
    for new_idx, (old_num, old_path) in enumerate(episode_folders):
        temp_name = f"temp_episode_{new_idx:04d}"
        temp_path = data_path / temp_name
        print(f"  {old_path.name} -> {temp_name}")
        old_path.rename(temp_path)
        temp_names.append((new_idx, temp_path))
    
    # Phase 2: Rename from temporary to final names
    print("\nPhase 2: Renaming to final names...")
    for new_idx, temp_path in temp_names:
        final_name = f"episode_{new_idx:04d}"
        final_path = data_path / final_name
        print(f"  {temp_path.name} -> {final_name}")
        temp_path.rename(final_path)
    
    print("\n" + "=" * 60)
    print("✓ Renaming complete!")
    print("=" * 60)
    
    # Verify the results
    print("\nVerifying results...")
    final_episodes = sorted([d.name for d in data_path.iterdir() 
                            if d.is_dir() and d.name.startswith('episode_')])
    
    expected = [f"episode_{i:04d}" for i in range(len(episode_folders))]
    
    if final_episodes == expected:
        print(f"✓ All {len(final_episodes)} episodes are now sequentially numbered!")
        print(f"  Range: {final_episodes[0]} to {final_episodes[-1]}")
        return True
    else:
        print("✗ Warning: Verification failed!")
        print(f"  Expected: {expected}")
        print(f"  Found: {final_episodes}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python renumber_episodes.py <data_directory> [--dry-run]")
        sys.exit(1)
    
    data_dir = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    
    success = renumber_episodes(data_dir, dry_run=dry_run)
    sys.exit(0 if success else 1)
