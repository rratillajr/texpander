#!/usr/bin/env python3
"""
Text Expander - Functional Programming Version

A single-file text expansion utility using functional programming principles,
YAML configuration, and pure functions where possible.
"""

import atexit
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from functools import partial, reduce
from pathlib import Path
from typing import Dict, List, Callable, Optional, Tuple, Any, NamedTuple

import yaml
from pynput import keyboard



# =============================================================================
# Data Structures
# =============================================================================

class AppState(NamedTuple):
    """Immutable application state."""
    buffer: deque
    expansions: Dict[str, str]
    last_activity: Optional[float]
    start_time: Optional[float]
    expansion_count: int
    running: bool


class Config(NamedTuple):
    """Immutable configuration."""
    expansions_file: str
    inactivity_timeout: float
    file_check_interval: float
    backspace_delay: float
    debounce_delay: float
    max_buffer_size: int
    log_level: str
    log_format: str
    max_retries: int
    retry_delay: float


# =============================================================================
# Pure Functions - Configuration
# =============================================================================

def load_yaml_config(config_path: str = "config.yaml") -> dict:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logging.error(f"Configuration file not found: {config_path}")
        raise
    except yaml.YAMLError as e:
        logging.error(f"Invalid YAML configuration: {e}")
        raise


def apply_environment_overrides(config_dict: dict) -> dict:
    """
    Apply environment variable overrides to configuration.

    Args:
        config_dict: Base configuration dictionary

    Returns:
        Configuration with environment overrides applied
    """
    overrides = {
        'TEXPANDER_LOG_LEVEL': ('logging', 'level'),
        'TEXPANDER_BUFFER_SIZE': ('buffer', 'max_size'),
        'TEXPANDER_TIMEOUT': ('timing', 'inactivity_timeout'),
        'TEXPANDER_FILE': ('expansions', 'file'),
    }

    result = config_dict.copy()

    for env_var, (section, key) in overrides.items():
        if env_var in os.environ:
            value = os.environ[env_var]

            # Type conversion
            if key in ['max_size']:
                value = int(value)
            elif key in ['inactivity_timeout']:
                value = float(value)

            if section not in result:
                result[section] = {}
            result[section][key] = value

    return result


def create_config(config_dict: dict) -> Config:
    """
    Create immutable Config object from dictionary.

    Args:
        config_dict: Configuration dictionary

    Returns:
        Immutable Config object
    """
    return Config(
        expansions_file=config_dict['expansions']['file'],
        inactivity_timeout=config_dict['timing']['inactivity_timeout'],
        file_check_interval=config_dict['timing']['file_check_interval'],
        backspace_delay=config_dict['timing']['backspace_delay'],
        debounce_delay=config_dict['timing']['debounce_delay'],
        max_buffer_size=config_dict['buffer']['max_size'],
        log_level=config_dict['logging']['level'],
        log_format=config_dict['logging']['format'],
        max_retries=config_dict['performance']['max_retries'],
        retry_delay=config_dict['performance']['retry_delay']
    )


# =============================================================================
# Pure Functions - Expansion Management
# =============================================================================

def parse_expansion_line(line: str, line_num: int) -> Optional[Tuple[str, str]]:
    """
    Parse a single expansion line (backward compatibility function).

    Args:
        line: Line to parse
        line_num: Line number for error reporting

    Returns:
        Tuple of (abbreviation, expansion) or None if invalid
    """
    line = line.strip()

    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return None

    if ':' not in line:
        logging.warning(f"Invalid format on line {line_num}: missing ':' separator")
        return None

    parts = line.split(':', 1)
    if len(parts) != 2:
        return None

    abbreviation = parts[0].strip()
    expansion = parts[1].strip()

    if not abbreviation:
        logging.warning(f"Empty abbreviation on line {line_num}")
        return None

    # Handle empty expansion for single-line (will be caught later)
    if not expansion and not expansion == '':
        logging.warning(f"Empty expansion on line {line_num}")
        return None

    return abbreviation, expansion


def parse_multiline_expansion(lines: List[str], start_index: int) -> Optional[Tuple[str, str, int]]:
    """
    Parse a YAML-style multi-line expansion.

    Args:
        lines: List of all lines in the file
        start_index: Index of the line starting the expansion

    Returns:
        Tuple of (abbreviation, expansion, next_line_index) or None if invalid
    """
    line = lines[start_index].strip()

    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return None

    if ':' not in line:
        return None

    parts = line.split(':', 1)
    if len(parts) != 2:
        return None

    abbreviation = parts[0].strip()
    right_side = parts[1].strip()

    if not abbreviation:
        return None

    # Check if this is a multi-line expansion (ends with ' |')
    if right_side == '|':
        # Multi-line literal block
        expansion_lines = []
        i = start_index + 1

        # Collect indented lines
        while i < len(lines):
            current_line = lines[i]

            # Empty line - include in expansion
            if not current_line.strip():
                expansion_lines.append('')
                i += 1
                continue

            # Check if line is indented (starts with spaces)
            if current_line.startswith('  '):
                # Remove exactly 2 spaces of indentation
                expansion_lines.append(current_line[2:])
                i += 1
            else:
                # Non-indented line means end of multi-line block
                break

        if not expansion_lines:
            logging.warning(f"Empty multi-line expansion for '{abbreviation}' on line {start_index + 1}")
            return None

        # Join lines with newlines, removing trailing empty lines
        while expansion_lines and not expansion_lines[-1].strip():
            expansion_lines.pop()

        expansion = '\n'.join(expansion_lines)
        return abbreviation, expansion, i

    elif right_side:
        # Single-line expansion (backward compatibility)
        return abbreviation, right_side, start_index + 1

    else:
        # Empty expansion
        logging.warning(f"Empty expansion for '{abbreviation}' on line {start_index + 1}")
        return None


def parse_expansions_content(content: str) -> Dict[str, str]:
    """
    Parse expansions from file content, supporting both single-line and YAML-style multi-line.

    Args:
        content: File content as string

    Returns:
        Dictionary mapping abbreviations to expansions
    """
    expansions = {}
    lines = content.splitlines()
    i = 0

    while i < len(lines):
        # Try multi-line parsing first
        result = parse_multiline_expansion(lines, i)
        if result:
            abbreviation, expansion, next_i = result
            expansions[abbreviation] = expansion
            i = next_i
        else:
            # Skip this line and continue
            i += 1

    return expansions


def load_expansions_with_retry(file_path: str, max_retries: int, retry_delay: float) -> Dict[str, str]:
    """
    Load expansions from file with retry logic.

    Args:
        file_path: Path to expansions file
        max_retries: Maximum retry attempts
        retry_delay: Delay between retries

    Returns:
        Dictionary of expansions

    Raises:
        FileNotFoundError: If file doesn't exist after retries
    """
    for attempt in range(max_retries):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            expansions = parse_expansions_content(content)
            logging.info(f"Loaded {len(expansions)} expansions from {file_path}")
            return expansions

        except FileNotFoundError:
            if attempt == max_retries - 1:
                raise
            logging.warning(f"File not found, attempt {attempt + 1}/{max_retries}")
            time.sleep(retry_delay)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logging.warning(f"Error loading expansions, attempt {attempt + 1}/{max_retries}: {e}")
            time.sleep(retry_delay)

    return {}


def get_file_modification_time(file_path: str) -> Optional[float]:
    """
    Get file modification time safely.

    Args:
        file_path: Path to file

    Returns:
        Modification time or None if error
    """
    try:
        return Path(file_path).stat().st_mtime
    except Exception:
        return None


# =============================================================================
# Pure Functions - Buffer Management
# =============================================================================

def create_initial_state(config: Config) -> AppState:
    """
    Create initial application state.

    Args:
        config: Configuration object

    Returns:
        Initial AppState
    """
    return AppState(
        buffer=deque(maxlen=config.max_buffer_size),
        expansions={},
        last_activity=None,
        start_time=time.time(),
        expansion_count=0,
        running=True
    )


def add_character_to_buffer(state: AppState, char: str) -> AppState:
    """
    Add character to buffer and update state.

    Args:
        state: Current state
        char: Character to add

    Returns:
        New state with character added
    """
    new_buffer = state.buffer.copy()
    new_buffer.append(char)

    return state._replace(
        buffer=new_buffer,
        last_activity=time.time()
    )


def remove_character_from_buffer(state: AppState) -> AppState:
    """
    Remove last character from buffer.

    Args:
        state: Current state

    Returns:
        New state with character removed
    """
    if not state.buffer:
        return state

    new_buffer = state.buffer.copy()
    new_buffer.pop()

    return state._replace(
        buffer=new_buffer,
        last_activity=time.time()
    )


def clear_buffer(state: AppState) -> AppState:
    """
    Clear the buffer.

    Args:
        state: Current state

    Returns:
        New state with cleared buffer
    """
    return state._replace(
        buffer=deque(maxlen=state.buffer.maxlen),
        last_activity=None
    )


def should_clear_buffer_for_inactivity(state: AppState, timeout: float) -> bool:
    """
    Check if buffer should be cleared due to inactivity.

    Args:
        state: Current state
        timeout: Inactivity timeout in seconds

    Returns:
        True if buffer should be cleared
    """
    if state.last_activity is None:
        return False

    return time.time() - state.last_activity > timeout


def get_buffer_text(state: AppState) -> str:
    """
    Get buffer content as string.

    Args:
        state: Current state

    Returns:
        Buffer content as string
    """
    return ''.join(state.buffer)


def get_last_word_from_buffer(state: AppState) -> str:
    """
    Get the last word from buffer.

    Args:
        state: Current state

    Returns:
        Last word in buffer
    """
    text = get_buffer_text(state)
    if not text:
        return ""

    # Find last whitespace
    for i in range(len(text) - 1, -1, -1):
        if text[i].isspace():
            return text[i + 1:]

    return text


# =============================================================================
# Pure Functions - Expansion Logic
# =============================================================================

def find_expansion(word: str, expansions: Dict[str, str]) -> Optional[str]:
    """
    Find expansion for a word.

    Args:
        word: Word to expand
        expansions: Dictionary of expansions

    Returns:
        Expansion text or None if not found
    """
    return expansions.get(word.strip())


def should_process_key_for_expansion(key) -> bool:
    """
    Determine if a key should trigger expansion processing.

    Args:
        key: Keyboard key

    Returns:
        True if key should trigger processing
    """
    # Process on printable characters
    if hasattr(key, 'char') and key.char and key.char.isprintable():
        return True

    return False


def should_clear_buffer_for_key(key) -> bool:
    """
    Determine if a key should clear the buffer.

    Args:
        key: Keyboard key

    Returns:
        True if buffer should be cleared
    """
    clearing_keys = {
        keyboard.Key.space,
        keyboard.Key.enter,
        keyboard.Key.tab,
        keyboard.Key.left,
        keyboard.Key.right,
        keyboard.Key.up,
        keyboard.Key.down,
        keyboard.Key.home,
        keyboard.Key.end,
        keyboard.Key.page_up,
        keyboard.Key.page_down
    }

    return key in clearing_keys


def classify_key(key) -> str:
    """
    Classify a key into a category.

    Args:
        key: Keyboard key

    Returns:
        Key category string
    """
    if key == keyboard.Key.backspace:
        return "backspace"
    elif should_clear_buffer_for_key(key):
        return "clearing"
    elif hasattr(key, 'char') and key.char and key.char.isprintable():
        return "character"
    else:
        return "other"


# =============================================================================
# Higher-Order Functions
# =============================================================================

def create_debounced_processor(func: Callable, delay: float) -> Callable:
    """
    Create a debounced version of a function.

    Args:
        func: Function to debounce
        delay: Minimum delay between calls

    Returns:
        Debounced function
    """
    last_call_time = [0.0]  # Use list for mutable reference

    def debounced(*args, **kwargs):
        current_time = time.time()
        if current_time - last_call_time[0] >= delay:
            last_call_time[0] = current_time
            return func(*args, **kwargs)

    return debounced


def create_file_watcher(file_path: str, callback: Callable, interval: float) -> Callable:
    """
    Create a file watcher function.

    Args:
        file_path: Path to watch
        callback: Function to call on changes
        interval: Check interval in seconds

    Returns:
        Function to start watching
    """
    def watch():
        last_modified = get_file_modification_time(file_path)

        while True:
            time.sleep(interval)
            current_modified = get_file_modification_time(file_path)

            if current_modified and current_modified != last_modified:
                last_modified = current_modified
                try:
                    callback()
                except Exception as e:
                    logging.error(f"Error in file change callback: {e}")

    return watch


# =============================================================================
# Side Effects - I/O Operations
# =============================================================================

def setup_logging(config: Config) -> None:
    """
    Setup logging configuration.

    Args:
        config: Configuration object
    """
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper()),
        format=config.log_format,
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Reduce pynput noise
    logging.getLogger('pynput').setLevel(logging.WARNING)


def perform_text_expansion(abbreviation: str, expansion: str, backspace_delay: float) -> None:
    """
    Perform the actual text expansion.

    Args:
        abbreviation: Text to replace
        expansion: Replacement text
        backspace_delay: Delay between backspace operations
    """
    controller = keyboard.Controller()

    # Delete the abbreviation
    for _ in range(len(abbreviation)):
        controller.tap(keyboard.Key.backspace)
        if backspace_delay > 0:
            time.sleep(backspace_delay)

    # Type the expansion
    controller.type(expansion)
    logging.info(f"Expanded '{abbreviation}' -> '{expansion}'")


# =============================================================================
# Main Application Logic
# =============================================================================

def create_keyboard_event_handler(state_ref: List[AppState], config: Config) -> Tuple[Callable, Callable]:
    """
    Create keyboard event handlers.

    Args:
        state_ref: Mutable reference to application state
        config: Configuration object

    Returns:
        Tuple of (on_press, on_release) handlers
    """
    processing_expansion = [False]  # Mutable flag

    def on_press(key):
        if processing_expansion[0]:
            return

        try:
            current_state = state_ref[0]

            # Clear buffer if inactive
            if should_clear_buffer_for_inactivity(current_state, config.inactivity_timeout):
                current_state = clear_buffer(current_state)
                logging.debug("Buffer cleared due to inactivity")

            key_type = classify_key(key)

            if key_type == "character":
                char = getattr(key, 'char', None)
                if char:
                    current_state = add_character_to_buffer(current_state, char)
                    logging.debug(f"Added character: '{char}'")

            elif key_type == "backspace":
                current_state = remove_character_from_buffer(current_state)
                logging.debug("Removed character (backspace)")

            elif key_type == "clearing":
                # Process for expansion before clearing
                word = get_last_word_from_buffer(current_state)
                if word:
                    expansion = find_expansion(word, current_state.expansions)
                    if expansion:
                        processing_expansion[0] = True
                        try:
                            perform_text_expansion(word, expansion, config.backspace_delay)
                            current_state = current_state._replace(
                                expansion_count=current_state.expansion_count + 1
                            )
                        finally:
                            processing_expansion[0] = False

                current_state = clear_buffer(current_state)
                logging.debug(f"Buffer cleared due to key: {key}")

            state_ref[0] = current_state

        except Exception as e:
            logging.error(f"Error in key press handler: {e}")

    def on_release(key):
        if processing_expansion[0]:
            return

        try:
            if should_process_key_for_expansion(key):
                current_state = state_ref[0]
                word = get_last_word_from_buffer(current_state)

                if word:
                    expansion = find_expansion(word, current_state.expansions)
                    if expansion:
                        processing_expansion[0] = True
                        try:
                            perform_text_expansion(word, expansion, config.backspace_delay)
                            current_state = current_state._replace(
                                expansion_count=current_state.expansion_count + 1
                            )
                            current_state = clear_buffer(current_state)
                        finally:
                            processing_expansion[0] = False

                        state_ref[0] = current_state

        except Exception as e:
            logging.error(f"Error in key release handler: {e}")

    return on_press, on_release


def create_expansion_reloader(state_ref: List[AppState], config: Config) -> Callable:
    """
    Create function to reload expansions.

    Args:
        state_ref: Mutable reference to application state
        config: Configuration object

    Returns:
        Function to reload expansions
    """
    def reload_expansions():
        try:
            logging.info("Reloading expansions...")
            new_expansions = load_expansions_with_retry(
                config.expansions_file,
                config.max_retries,
                config.retry_delay
            )

            current_state = state_ref[0]
            state_ref[0] = current_state._replace(expansions=new_expansions)

        except Exception as e:
            logging.error(f"Failed to reload expansions: {e}")

    return reload_expansions


def run_keyboard_listener(on_press: Callable, on_release: Callable, state_ref: List[AppState]) -> None:
    """
    Run the keyboard event listener.

    Args:
        on_press: Key press handler
        on_release: Key release handler
        state_ref: Mutable reference to application state
    """
    try:
        with keyboard.Events() as events:
            for event in events:
                if not state_ref[0].running:
                    break

                if isinstance(event, keyboard.Events.Press):
                    on_press(event.key)
                elif isinstance(event, keyboard.Events.Release):
                    on_release(event.key)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
    except Exception as e:
        logging.error(f"Error in keyboard event loop: {e}")


def setup_signal_handlers(state_ref: List[AppState]) -> None:
    """
    Setup signal handlers for graceful shutdown.

    Args:
        state_ref: Mutable reference to application state
    """
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        current_state = state_ref[0]
        state_ref[0] = current_state._replace(running=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def print_startup_info(config: Config, expansions: Dict[str, str]) -> None:
    """
    Print startup information.

    Args:
        config: Configuration object
        expansions: Loaded expansions
    """
    print("=" * 60)
    print("  Text Expander - Functional Programming Version")
    print("=" * 60)
    print(f"  Expansions file: {config.expansions_file}")
    print(f"  Loaded expansions: {len(expansions)}")
    print(f"  Buffer size: {config.max_buffer_size}")
    print(f"  Log level: {config.log_level}")
    print("=" * 60)
    print("  Press Ctrl+C to stop")
    print("=" * 60)


def print_shutdown_info(state: AppState) -> None:
    """
    Print shutdown information.

    Args:
        state: Final application state
    """
    if state.start_time:
        runtime = time.time() - state.start_time
        logging.info(f"Text expander ran for {runtime:.1f} seconds")
        logging.info(f"Total expansions performed: {state.expansion_count}")


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> int:
    """
    Main entry point for the functional text expander.

    Returns:
        Exit code
    """
    try:
        # Load and process configuration
        config_dict = load_yaml_config()
        config_dict = apply_environment_overrides(config_dict)
        config = create_config(config_dict)

        # Setup logging
        setup_logging(config)
        logging.info("Starting Text Expander (Functional Version)")

        # Load initial expansions
        expansions = load_expansions_with_retry(
            config.expansions_file,
            config.max_retries,
            config.retry_delay
        )

        # Create initial state
        initial_state = create_initial_state(config)
        state_with_expansions = initial_state._replace(expansions=expansions)

        # Mutable reference to state (necessary for callbacks)
        state_ref = [state_with_expansions]

        # Setup signal handlers
        setup_signal_handlers(state_ref)

        # Create event handlers
        on_press, on_release = create_keyboard_event_handler(state_ref, config)

        # Create and start file watcher
        reload_expansions = create_expansion_reloader(state_ref, config)
        file_watcher = create_file_watcher(
            config.expansions_file,
            reload_expansions,
            config.file_check_interval
        )

        watcher_thread = threading.Thread(target=file_watcher, daemon=True)
        watcher_thread.start()

        # Print startup info
        print_startup_info(config, expansions)

        # Run main event loop
        run_keyboard_listener(on_press, on_release, state_ref)

        # Print shutdown info
        print_shutdown_info(state_ref[0])

        return 0

    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
        return 0
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())