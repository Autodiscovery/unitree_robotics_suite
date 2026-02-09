#!/usr/bin/env python3
"""
Interactive script to update task descriptions in recorded episodes.

Simply run this script and follow the prompts to update your dataset descriptions.

Usage:
    python update_descriptions_interactive.py
"""

import json
import os
from pathlib import Path
import shutil
from datetime import datetime


def list_datasets(base_dir="teleop/utils/data"):
    """List all available datasets"""
    base_path = Path(base_dir)
    if not base_path.exists():
        # Try relative to script location
        script_dir = Path(__file__).parent
        base_path = script_dir / "data"
    
    if not base_path.exists():
        return []
    
    datasets = [d for d in base_path.iterdir() if d.is_dir() and not d.name.startswith('.')]
    return sorted(datasets)


def show_current_descriptions(dataset_dir):
    """Show current task descriptions from the first episode"""
    dataset_path = Path(dataset_dir)
    episodes = sorted(dataset_path.glob("episode_*"))
    
    if not episodes:
        print(f"Error: No episodes found in {dataset_dir}")
        return None
    
    first_json = episodes[0] / "data.json"
    
    try:
        with open(first_json, 'r') as f:
            data = json.load(f)
        return data['text'], len(episodes)
    except Exception as e:
        print(f"Error reading {first_json}: {e}")
        return None


def update_all_episodes(dataset_dir, new_goal, new_desc, new_steps):
    """Update task descriptions for all episodes"""
    dataset_path = Path(dataset_dir)
    episodes = sorted(dataset_path.glob("episode_*"))
    
    updated_count = 0
    failed = []
    
    for episode_dir in episodes:
        json_path = episode_dir / "data.json"
        
        try:
            # Read the JSON file
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Update text section
            data['text']['goal'] = new_goal
            data['text']['desc'] = new_desc
            data['text']['steps'] = new_steps
            
            # Write back
            with open(json_path, 'w') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            updated_count += 1
            
        except Exception as e:
            failed.append((episode_dir.name, str(e)))
    
    return updated_count, failed


def main():
    print("=" * 70)
    print("  Task Description Updater")
    print("=" * 70)
    print()
    
    # Step 1: List and select dataset
    print("Step 1: Select Dataset")
    print("-" * 70)
    
    datasets = list_datasets()
    
    if not datasets:
        print("No datasets found in teleop/utils/data/")
        print("Please make sure you're running this script from the correct directory.")
        return
    
    print("Available datasets:")
    for i, dataset in enumerate(datasets, 1):
        print(f"  {i}. {dataset.name}")
    print()
    
    while True:
        try:
            choice = input("Select dataset number (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                print("Cancelled.")
                return
            
            idx = int(choice) - 1
            if 0 <= idx < len(datasets):
                selected_dataset = datasets[idx]
                break
            else:
                print(f"Please enter a number between 1 and {len(datasets)}")
        except ValueError:
            print("Please enter a valid number")
    
    print()
    
    # Step 2: Show current descriptions
    print("Step 2: Current Descriptions")
    print("-" * 70)
    
    result = show_current_descriptions(selected_dataset)
    if result is None:
        return
    
    current_text, num_episodes = result
    
    print(f"Dataset: {selected_dataset.name}")
    print(f"Episodes: {num_episodes}")
    print()
    print("Current descriptions:")
    print(f"  Goal:  {current_text['goal']}")
    print(f"  Desc:  {current_text['desc']}")
    print(f"  Steps: {current_text['steps']}")
    print()
    
    # Step 3: Enter new descriptions
    print("Step 3: Enter New Descriptions")
    print("-" * 70)
    print("(Press Enter to keep current value)")
    print()
    
    new_goal = input(f"New Goal [{current_text['goal']}]:\n  ").strip()
    if not new_goal:
        new_goal = current_text['goal']
    print()
    
    new_desc = input(f"New Description [{current_text['desc']}]:\n  ").strip()
    if not new_desc:
        new_desc = current_text['desc']
    print()
    
    new_steps = input(f"New Steps [{current_text['steps']}]:\n  ").strip()
    if not new_steps:
        new_steps = current_text['steps']
    print()
    
    # Step 4: Confirm changes
    print("Step 4: Confirm Changes")
    print("-" * 70)
    print(f"Dataset: {selected_dataset.name} ({num_episodes} episodes)")
    print()
    print("New descriptions:")
    print(f"  Goal:  {new_goal}")
    print(f"  Desc:  {new_desc}")
    print(f"  Steps: {new_steps}")
    print()
    
    confirm = input("Apply these changes to all episodes? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("Cancelled.")
        return
    
    # Step 5: Update episodes
    print()
    print("Step 5: Updating Episodes")
    print("-" * 70)
    
    updated_count, failed = update_all_episodes(selected_dataset, new_goal, new_desc, new_steps)
    
    print(f"✓ Successfully updated {updated_count}/{num_episodes} episodes")
    
    if failed:
        print()
        print("Failed to update:")
        for episode_name, error in failed:
            print(f"  ✗ {episode_name}: {error}")
    
    print()
    print("=" * 70)
    print("  Update Complete!")
    print("=" * 70)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
