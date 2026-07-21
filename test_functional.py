#!/usr/bin/env python3
"""
Test script for the functional Text Expander.
"""

import sys
import tempfile
import time
from collections import deque
from pathlib import Path

# Import the functional modules
try:
    from texpander import (
        # Configuration functions
        load_yaml_config, apply_environment_overrides, create_config,
        # Expansion functions
        parse_expansion_line, parse_multiline_expansion, parse_expansions_content, load_expansions_with_retry,
        # Buffer functions
        create_initial_state, add_character_to_buffer, remove_character_from_buffer,
        clear_buffer, get_buffer_text, get_last_word_from_buffer,
        # Expansion logic
        find_expansion, classify_key,
        # Data structures
        AppState, Config
    )
    print("[OK] All functional modules imported successfully")
except ImportError as e:
    print(f"[FAIL] Import error: {e}")
    sys.exit(1)


def test_configuration():
    """Test configuration loading and processing."""
    print("\n--- Testing Configuration ---")

    # Test YAML loading
    try:
        config_dict = load_yaml_config("config.yaml")
        assert 'expansions' in config_dict
        assert 'timing' in config_dict
        print("[OK] YAML configuration loaded")
    except Exception as e:
        print(f"[FAIL] YAML loading failed: {e}")
        return False

    # Test environment overrides
    import os
    os.environ['TEXPANDER_LOG_LEVEL'] = 'INFO'
    os.environ['TEXPANDER_BUFFER_SIZE'] = '50'

    config_with_env = apply_environment_overrides(config_dict)
    assert config_with_env['logging']['level'] == 'INFO'
    assert config_with_env['buffer']['max_size'] == 50
    print("[OK] Environment overrides work")

    # Test config object creation
    config = create_config(config_with_env)
    assert config.log_level == 'INFO'
    assert config.max_buffer_size == 50
    print("[OK] Config object creation works")

    return True


def test_expansion_parsing():
    """Test expansion parsing functions."""
    print("\n--- Testing Expansion Parsing ---")

    # Test single-line parsing (backward compatibility)
    test_cases = [
        ("test1:expansion1", ("test1", "expansion1")),
        ("# comment", None),
        ("", None),
        ("invalid_line", None),
        ("  test2  :  expansion2  ", ("test2", "expansion2")),
    ]

    for line, expected in test_cases:
        result = parse_expansion_line(line, 1)
        assert result == expected, f"Failed for line: {line}"

    print("[OK] Single-line parsing works correctly")

    # Test multi-line parsing
    multiline_content = """# Test expansions with multi-line support
test1:This is test 1
test2: |
  This is line 1
  This is line 2
  This is line 3
test3:Single line after multiline
test4: |
  Email template:

  Dear [Name],

  Thank you for your inquiry.

  Best regards,
  John
# Comment after multiline
test5:Another single line
"""

    expansions = parse_expansions_content(multiline_content)

    # Verify we got all expansions
    assert len(expansions) == 5, f"Expected 5 expansions, got {len(expansions)}"

    # Test single-line expansions
    assert expansions['test1'] == 'This is test 1'
    assert expansions['test3'] == 'Single line after multiline'
    assert expansions['test5'] == 'Another single line'

    # Test multi-line expansions
    expected_multiline = "This is line 1\nThis is line 2\nThis is line 3"
    assert expansions['test2'] == expected_multiline, f"Expected: {repr(expected_multiline)}, Got: {repr(expansions['test2'])}"

    expected_email = "Email template:\n\nDear [Name],\n\nThank you for your inquiry.\n\nBest regards,\nJohn"
    assert expansions['test4'] == expected_email, f"Expected: {repr(expected_email)}, Got: {repr(expansions['test4'])}"

    print("[OK] Multi-line parsing works correctly")

    # Test backward compatibility - old single-line format still works
    old_format_content = """# Old format test
test1:expansion1
test2:expansion2
test3:expansion3
"""
    old_expansions = parse_expansions_content(old_format_content)
    assert len(old_expansions) == 3
    assert old_expansions['test1'] == 'expansion1'
    print("[OK] Backward compatibility maintained")

    return True


def test_buffer_operations():
    """Test buffer management functions."""
    print("\n--- Testing Buffer Operations ---")

    # Create test config
    config = Config(
        expansions_file="test.txt",
        inactivity_timeout=2.0,
        file_check_interval=1.0,
        backspace_delay=0.01,
        debounce_delay=0.05,
        max_buffer_size=10,
        log_level="DEBUG",
        log_format="%(message)s",
        max_retries=3,
        retry_delay=0.5
    )

    # Test initial state
    state = create_initial_state(config)
    assert len(state.buffer) == 0
    assert state.expansion_count == 0
    assert state.running == True
    print("[OK] Initial state creation works")

    # Test adding characters
    state = add_character_to_buffer(state, 'h')
    state = add_character_to_buffer(state, 'e')
    state = add_character_to_buffer(state, 'l')
    state = add_character_to_buffer(state, 'l')
    state = add_character_to_buffer(state, 'o')

    assert get_buffer_text(state) == 'hello'
    print("[OK] Character addition works")

    # Test character removal
    state = remove_character_from_buffer(state)
    assert get_buffer_text(state) == 'hell'
    print("[OK] Character removal works")

    # Test last word extraction
    state = add_character_to_buffer(state, 'o')
    state = add_character_to_buffer(state, ' ')
    state = add_character_to_buffer(state, 'w')
    state = add_character_to_buffer(state, 'o')
    state = add_character_to_buffer(state, 'r')
    state = add_character_to_buffer(state, 'l')
    state = add_character_to_buffer(state, 'd')

    assert get_last_word_from_buffer(state) == 'world'
    print("[OK] Last word extraction works")

    # Test buffer clearing
    state = clear_buffer(state)
    assert len(state.buffer) == 0
    assert get_buffer_text(state) == ''
    print("[OK] Buffer clearing works")

    return True


def test_expansion_logic():
    """Test expansion logic functions."""
    print("\n--- Testing Expansion Logic ---")

    # Test expansion finding
    expansions = {
        'test1': 'This is test 1',
        'test2': 'This is test 2',
        'hello': 'Hello, World!'
    }

    assert find_expansion('test1', expansions) == 'This is test 1'
    assert find_expansion('nonexistent', expansions) is None
    assert find_expansion('  test2  ', expansions) == 'This is test 2'  # Should strip
    print("[OK] Expansion finding works")

    # Test key classification
    from pynput import keyboard

    assert classify_key(keyboard.Key.backspace) == "backspace"
    assert classify_key(keyboard.Key.space) == "clearing"
    assert classify_key(keyboard.Key.enter) == "clearing"

    # Create a mock key with char attribute
    class MockKey:
        def __init__(self, char):
            self.char = char

    mock_key = MockKey('a')
    assert classify_key(mock_key) == "character"
    print("[OK] Key classification works")

    return True


def test_file_operations():
    """Test file operations with temporary files."""
    print("\n--- Testing File Operations ---")

    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("""# Test expansions
test1:expansion1
test2:expansion2
test3:expansion3
""")
        temp_file = f.name

    try:
        # Test loading with retry
        expansions = load_expansions_with_retry(temp_file, 3, 0.1)
        assert len(expansions) == 3
        assert expansions['test1'] == 'expansion1'
        print("[OK] File loading with retry works")

    finally:
        # Cleanup
        Path(temp_file).unlink()

    return True


def run_all_tests():
    """Run all functional tests."""
    print("Running Functional Text Expander Tests")
    print("=" * 50)

    tests = [
        test_configuration,
        test_expansion_parsing,
        test_buffer_operations,
        test_expansion_logic,
        test_file_operations
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[FAIL] Test {test.__name__} failed with exception: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Tests completed: {passed} passed, {failed} failed")

    if failed == 0:
        print("All tests passed! The functional version is working correctly.")
        return True
    else:
        print("Some tests failed. Please check the implementation.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)