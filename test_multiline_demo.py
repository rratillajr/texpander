#!/usr/bin/env python3
"""
Demo script to show multi-line expansion functionality.
"""

from texpander import load_expansions_with_retry, parse_expansions_content

def demo_multiline_expansions():
    """Demonstrate multi-line expansion parsing."""
    print("Multi-line Expansion Demo")
    print("=" * 50)

    # Load expansions from file
    try:
        expansions = load_expansions_with_retry("expansions.txt", 3, 0.5)
        print(f"Loaded {len(expansions)} expansions\n")

        # Show some examples
        examples = ['..addr', '..sig', '..thanks', '..meeting', '..html']

        for abbrev in examples:
            if abbrev in expansions:
                expansion = expansions[abbrev]
                print(f"Abbreviation: {abbrev}")
                print("Expansion:")
                print("-" * 20)
                print(expansion)
                print("-" * 20)
                print(f"Lines: {len(expansion.splitlines())}")
                print(f"Characters: {len(expansion)}")
                print()

        # Show single-line examples for comparison
        print("Single-line examples:")
        single_examples = ['..email', '..name', '..ty', '..py']
        for abbrev in single_examples:
            if abbrev in expansions:
                print(f"{abbrev} -> {expansions[abbrev]}")

    except Exception as e:
        print(f"Error loading expansions: {e}")

if __name__ == "__main__":
    demo_multiline_expansions()