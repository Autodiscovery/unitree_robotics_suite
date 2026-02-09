#!/usr/bin/env python3
"""
Script to update task descriptions in recorded episodes.

This script allows you to modify the task descriptions (goal, desc, steps)
in all episodes of a dataset without affecting the actual recorded data.

Usage:
    python update_task_descriptions.py --dataset suitcase_to_waist_2 \
        --goal "New goal description" \
        --desc "New detailed description" \
        --steps "step1: ...; step2: ...; step3: ..."
"""

import json
import os
import argparse
from pathlib import Path
import shutil
from datetime import datetime


def backup_dataset(dataset_dir):
    """Create a backup of the dataset before modification"""
    backup_dir = f"{dataset_dir}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"Creating backup at: {backup_dir}")
    shutil.copytree(dataset_dir, backup_dir)
    return backup_dir


def update_task_descriptions(dataset_dir, new_goal=None, new_desc=None, new_steps=None, dry_run=False):
    """
    Update task descriptions for all episodes in a dataset.
    
    Args:
        dataset_dir: Path to the dataset directory
        new_goal: New goal description (optional)
        new_desc: New detailed description (optional)
        new_steps: New step-by-step description (optional)
        dry_run: If True, only show what would be changed without modifying files
    """
    dataset_path = Path(dataset_dir)
    
    if not dataset_path.exists():
        print(f"Error: Dataset directory not found: {dataset_dir}")
        return
    
    episodes = sorted(dataset_path.glob("episode_*"))
    
    if not episodes:
        print(f"Error: No episodes found in {dataset_dir}")
        return
    
    print(f"Found {len(episodes)} episodes in {dataset_dir}")
    print()
    
    # Show current descriptions from first episode
    first_episode = episodes[0]
    first_json = first_episode / "data.json"
    
    with open(first_json, 'r') as f:
        sample_data = json.load(f)
    
    print("Current task descriptions (from first episode):")
    print(f"  Goal:  {sample_data['text']['goal']}")
    print(f"  Desc:  {sample_data['text']['desc']}")
    print(f"  Steps: {sample_data['text']['steps']}")
    print()
    
    if not any([new_goal, new_desc, new_steps]):
        print("No new descriptions provided. Nothing to update.")
        return
    
    print("New task descriptions:")
    if new_goal:
        print(f"  Goal:  {new_goal}")
    if new_desc:
        print(f"  Desc:  {new_desc}")
    if new_steps:
        print(f"  Steps: {new_steps}")
    print()
    
    if dry_run:
        print("DRY RUN - No files will be modified")
        return
    
    # Confirm before proceeding
    response = input(f"Update {len(episodes)} episodes? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Cancelled.")
        return
    
    # Update all episodes
    updated_count = 0
    for episode_dir in episodes:
        json_path = episode_dir / "data.json"
        
        try:
            # Read the JSON file
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Update text section
            if new_goal:
                data['text']['goal'] = new_goal
            if new_desc:
                data['text']['desc'] = new_desc
            if new_steps:
                data['text']['steps'] = new_steps
            
            # Write back
            with open(json_path, 'w') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            updated_count += 1
            print(f"✓ Updated {episode_dir.name}")
            
        except Exception as e:
            print(f"✗ Error updating {episode_dir.name}: {e}")
    
    print()
    print(f"Successfully updated {updated_count}/{len(episodes)} episodes")


def main():
    parser = argparse.ArgumentParser(
        description="Update task descriptions in recorded episodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Update all descriptions for suitcase_to_waist_2 dataset
  python update_task_descriptions.py --dataset teleop/utils/data/suitcase_to_waist_2 \\
      --goal "Pick suitcase from table and secure to waist mount" \\
      --desc "Bimanual manipulation task" \\
      --steps "step1: grasp; step2: lift; step3: secure"
  
  # Dry run to see what would change
  python update_task_descriptions.py --dataset teleop/utils/data/suitcase_to_waist_2 \\
      --goal "New goal" --dry-run
  
  # Update only the goal description
  python update_task_descriptions.py --dataset teleop/utils/data/suitcase_to_waist_2 \\
      --goal "New goal description"
        """
    )
    
    parser.add_argument('--dataset', type=str, required=True,
                        help='Path to the dataset directory (e.g., teleop/utils/data/suitcase_to_waist_2)')
    parser.add_argument('--goal', type=str, default=None,
                        help='New goal description')
    parser.add_argument('--desc', type=str, default=None,
                        help='New detailed description')
    parser.add_argument('--steps', type=str, default=None,
                        help='New step-by-step description')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be changed without modifying files')
    parser.add_argument('--backup', action='store_true',
                        help='Create a backup of the dataset before modification')
    
    args = parser.parse_args()
    
    # Create backup if requested
    if args.backup and not args.dry_run:
        backup_dataset(args.dataset)
    
    # Update descriptions
    update_task_descriptions(
        args.dataset,
        new_goal=args.goal,
        new_desc=args.desc,
        new_steps=args.steps,
        dry_run=args.dry_run
    )


if __name__ == '__main__':
    main()
