import logging
from pynput import keyboard
import time
import os

log_level = os.getenv('LOGLEVEL', 'DEBUG').upper()
if log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
    log_level = 'DEBUG'  # Default to DEBUG if invalid level is set
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info(f"Logging level set to: {log_level}")

def load_expansions(file_path):
    """
    Load expansions from a file.
    Each line in the file should be in the format: abbreviation:expansion
    """
    expansions = {}
    try:
        with open(file_path, 'r') as file:
            for line in file:
                if ':' in line:
                    abbreviation, expansion = line.strip().split(':', 1)
                    expansions[abbreviation.strip()] = expansion.strip()
        logging.info(f"Loaded expansions: {expansions}")
    except Exception as e:
        logging.error(f"Error loading expansions: {e}")
    return expansions




def on_press(key):
    try:
        global start_time
        if start_time is not None:
            elapsed_time = time.time() - start_time
            if elapsed_time > 2:  # Reset buffer if no key pressed for 2 seconds
                typed_text.clear()
                logging.debug("Buffer cleared due to inactivity.")
        else:
            start_time = time.time()

        if hasattr(key, 'char') and key.char:
            typed_text.append(key.char)
            logging.debug(f"Typed character: {key.char}")
        elif key in {keyboard.Key.backspace}:
            if typed_text:
                logging.debug("Backspace pressed, removing last character.")
                typed_text.pop()
        elif key in {keyboard.Key.space, keyboard.Key.enter}:
            #typed_text.append(' ')
            #process_typed_text()
            typed_text.clear()
    except Exception as e:
        logging.error(f"Error on key press: {e}")

def on_release(key):
    global start_time
    start_time = time.time()
    process_typed_text()


def process_typed_text():
    try:
        word = ''.join(typed_text).strip()
        logging.debug(f"Typed word: {word}")

        if word in expansions:
            expanded_text = expansions[word]
            logging.debug(f"Expanding: {word} -> {expanded_text}")

            # Simulate pressing backspace to delete the abbreviation and space
            backspace_count = len(word)# + 1
            for _ in range(backspace_count):
                controller.tap(keyboard.Key.backspace)
                logging.debug("Pressed backspace")
                time.sleep(0.01)

            # Simulate typing the expanded text
            #for char in expanded_text + ' ':
            for char in expanded_text:
                controller.type(char)
                logging.debug(f"Typed character: {char}")

            typed_text.clear()

    except Exception as e:
        logging.error(f"Error processing typed text: {e}")



if __name__ == "__main__":
    # Load expansions from the file, create this file with your abbreviations
    # e.g.
    # hello:Hello, World!
    expansions = load_expansions('expansions.txt')

    typed_text = []  # Buffer to store typed characters
    controller = keyboard.Controller()  # Initialize the controller

    # Initialize start time for inactivity tracking
    start_time = None

    try:
        with keyboard.Events() as events:
            for event in events:
                if event.key == keyboard.Key.esc:
                    raise KeyboardInterrupt  # Exit on Escape key press
                else:
                    #print('Received event {}'.format(event))
                    #if an object is pynput.keyboard.Events.Press
                    if isinstance(event, keyboard.Events.Press):
                        on_press(event.key)
                    elif isinstance(event, keyboard.Events.Release):
                        on_release(event.key)
                    else:
                        logging.debug(f"Received event: {event}")
                    print(type(event))
    except KeyboardInterrupt:
        logging.info("Text expander stopped.")
    except Exception as e:
        logging.error(f"Error starting listener: {e}")
    
