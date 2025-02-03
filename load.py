import tkinter as tk
import logging
import webbrowser
import myNotebook as nb
from config import config, appname
import requests
from threading import Timer
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from queue import Queue
from threading import Thread
from workers.fc_worker import FCWorker
import time  # Add missing import
from urllib.request import Request, urlopen  # Can be removed if not used elsewhere
from permissions import get_permissions_header  # Added import

logger = logging.getLogger(f'{appname}.EDStS')

REGISTER_USER_URL = "https://edsts.7thseraph.org/api/auth/register"
API_BASE = "https://edsts.7thseraph.org"
CHECK_INTERVAL = 600  # Verify API key every 60 seconds
JOURNAL_ENDPOINT = f"{API_BASE}/api/journal/event"

class EDStSState:
    """State management for EDStS plugin"""
    def __init__(self):
        self.status_label = None
        self.verification_timer = None
        self.last_event_times = {}
        self.event_queue = Queue()
        self.connection_state = {
            "is_connected": False,
            "last_activity_check": None
        }
        self.worker_thread = None
        self.shutting_down = False
        self.fc_worker = FCWorker(API_BASE, JOURNAL_ENDPOINT)

this = EDStSState()

def should_process_event(event_name: str, timestamp: str) -> bool:
    """
    Determine if we should process this event.
    Now only check if the event is among the important events.
    """
    if event_name not in IMPORTANT_EVENTS:
        return False
    return True

def worker() -> None:
    """Background worker to process events individually."""
    while not this.shutting_down:
        try:
            event = this.event_queue.get(timeout=5)
            if event is None:  # Shutdown signal
                break
            logger.debug(f"Processing event: {event.get('event')}")
            success = submit_journal_event(event)
            if not success:
                logger.debug("Submission failed, retrying after delay")
                time.sleep(5)
        except Exception as e:
            logger.error(f"Worker thread error: {e}")
            time.sleep(5)

def submit_journal_event(event: dict) -> bool:
    """Submit a single journal event to the EDStS API"""
    if not this.connection_state["is_connected"]:
        logger.debug("Not connected, skipping event submission")
        return False
        
    try:
        api_key = config.get_str("edsts_api_key")
        if not api_key:
            logger.debug("No API key, skipping event submission")
            return False

        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "x-permissions": get_permissions_header(config)  # Use common helper
        }
        
        logger.debug(f"Submitting event: {event.get('event')}")
        
        response = requests.post(
            JOURNAL_ENDPOINT,
            headers=headers,
            json=event,
            timeout=10
        )
        
        logger.debug(f"API response: {response.status_code}")
        
        if response.status_code == 401:
            this.connection_state["is_connected"] = False
            return False
        elif response.status_code != 200:
            logger.error(f"Failed to submit event: {response.status_code}")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"EDStS API: Failed to submit journal event - {str(e)}")
        return False

def check_api_activity() -> bool:
    """Check if the API is active and responding"""
    try:
        api_key = config.get_str("edsts_api_key")
        if not api_key:
            return False
        response = requests.get(f"{API_BASE}/api/auth/verify", params={"key": api_key}, timeout=5)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"API activity check failed: {str(e)}")
        return False

def verify_api_key(api_key: str) -> bool:
    try:
        # Make a single verification request
        response = requests.get(f"{API_BASE}/api/auth/verify", params={"key": api_key}, timeout=5)
        result = response.json()
        is_valid = result.get("valid", False)
        # Convert string "True"/"False" to bool if needed
        if isinstance(is_valid, str):
            is_valid = is_valid.lower() == "true"
        this.connection_state["is_connected"] = is_valid
        logger.info(f"API key verification returned: {result}")
        return is_valid
    except Exception as e:
        this.connection_state["is_connected"] = False
        logger.error(f"API verification failed: {str(e)}")
        return False

def update_status_label():
    if not this.status_label:
        return
    
    api_key = config.get_str("edsts_api_key")
    if not api_key:
        this.status_label["text"] = "EDStS API: Disconnected ✖️"
        return

    is_valid = verify_api_key(api_key)
    this.status_label["text"] = "EDStS API: Connected ✔️" if is_valid else "EDStS API: Disconnected ✖️"

def schedule_verification():
    if this.verification_timer:
        this.verification_timer.cancel()
    this.verification_timer = Timer(CHECK_INTERVAL, periodic_check)
    this.verification_timer.daemon = True
    this.verification_timer.start()

def periodic_check():
    update_status_label()
    schedule_verification()

def plugin_start3(plugin_dir: str) -> str:
    """
    Plugin init hook. Must return the plugin name to be used in preferences tab.
    """
    logger.info("EDStS plugin loaded")
    this.worker_thread = Thread(target=worker, name='EDStS worker')
    this.worker_thread.daemon = True
    this.worker_thread.start()
    this.fc_worker.start()
    return "EDStS"

def plugin_stop() -> None:
    logger.info("EDStS plugin stopping")
    this.shutting_down = True
    this.event_queue.put(None)  # Signal worker to stop
    if this.worker_thread:
        this.worker_thread.join(timeout=2)
    this.fc_worker.stop()

def perform_oauth() -> None:
    webbrowser.open(REGISTER_USER_URL)
    logger.info("Opened Discord OAuth URL")

def save_api_key(api_key: str, status_label: tk.Label) -> None:
    """Save API key and verify it"""
    if not api_key:
        status_label["text"] = "Please enter an API key"
        return
        
    config.set("edsts_api_key", api_key)
    logger.info("EDStS API key saved")
    
    if verify_api_key(api_key):
        status_label["text"] = "API Key verified and saved ✔️"
    else:
        status_label["text"] = "Invalid API Key ✖️"
    
    update_status_label()  # Update main window status

def clear_api_key(api_key_var: tk.StringVar, key_status_label: tk.Label) -> None:
    """Clear the API key from config and UI"""
    config.delete("edsts_api_key")
    api_key_var.set("")
    key_status_label["text"] = "API Key cleared"
    logger.info("EDStS API key cleared")
    update_status_label()  # Update main window status

def save_user_permissions(permissions: str, label: tk.Label) -> None:
    config.set("edsts_user_permissions", permissions)
    label["text"] = "User permissions saved"

def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> nb.Frame:
    """
    Create plugin preferences tab. Must return an nb.Frame.
    """
    frame = nb.Frame(parent)
    frame.columnconfigure(1, weight=1)

    # Discord Authentication Section
    nb.Label(frame, text="Step 1: Discord Authentication").grid(row=0, column=0, sticky=tk.W, padx=10, pady=(10,0))
    nb.Label(frame, text="Click below to connect with Discord and get your API key:").grid(row=1, column=0, sticky=tk.W, padx=10)
    nb.Button(frame, text="Connect via Discord", command=perform_oauth).grid(row=2, column=0, sticky=tk.W, padx=10, pady=(0,10))
    
    # EDStS API Key Section
    nb.Label(frame, text="Step 2: Enter your EDStS API Key").grid(row=3, column=0, sticky=tk.W, padx=10, pady=(10,0))
    nb.Label(frame, text="After Discord authentication, paste your API key here:").grid(row=4, column=0, sticky=tk.W, padx=10)
    
    api_key_var = tk.StringVar(value=config.get_str("edsts_api_key") or "")
    api_entry = nb.Entry(frame, textvariable=api_key_var, width=40)
    api_entry.grid(row=5, column=0, sticky=tk.W, padx=10)
    
    # Status label for API key verification
    key_status_label = tk.Label(frame, text="")
    key_status_label.grid(row=6, column=0, sticky=tk.W, padx=10, pady=(5,0))
    
    # Save and Clear buttons
    nb.Button(frame, text="Save API Key", command=lambda: save_api_key(api_key_var.get(), key_status_label)).grid(row=7, column=0, sticky=tk.W, padx=10, pady=(10,0))
    nb.Button(frame, text="Clear API Key", command=lambda: clear_api_key(api_key_var, key_status_label)).grid(row=8, column=0, sticky=tk.W, padx=10, pady=(5,10))
    
    # User Permissions Section
    nb.Label(frame, text="User Permissions (comma separated)").grid(row=9, column=0, sticky=tk.W, padx=10, pady=(10,0))
    user_perm_var = tk.StringVar(value=config.get_str("edsts_user_permissions") or "")
    user_perm_entry = nb.Entry(frame, textvariable=user_perm_var, width=40)
    user_perm_entry.grid(row=10, column=0, sticky=tk.W, padx=10)
    nb.Button(frame, text="Save Permissions", command=lambda: save_user_permissions(user_perm_var.get(), key_status_label)).grid(row=11, column=0, sticky=tk.W, padx=10, pady=(10,0))
    
    frame.api_key_var = api_key_var
    return frame

def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Save any changed preferences."""
    if hasattr(frame, 'api_key_var'):
        config.set('edsts_api_key', frame.api_key_var.get())

def plugin_app(parent):
    """
    Create our main UI element in EDMC's main window.
    Returns just the frame for the main window display.
    """
    frame = tk.Frame(parent)
    # Keep the status label for connection state display
    this.status_label = tk.Label(frame, text="EDStS API: Disconnected ✖️")
    this.status_label.pack(padx=10)
    frame.columnconfigure(0, weight=1)
    
    # Make sure frame is displayed even if empty
    frame.grid(sticky=tk.EW)
    update_status_label()
    schedule_verification()
    
    return frame  # Just return the frame, not a tuple

def journal_entry(
    cmdr: str, 
    is_beta: bool, 
    system: str, 
    station: str, 
    entry: Dict[str, Any], 
    state: Dict[str, Any]
) -> Optional[str]:
    """Process journal entries and delegate to worker for submission."""
    if not this.connection_state["is_connected"]:
        return None

    event_type = entry.get('event')
    logger.debug(f"Received event: {event_type}")

    # Delegate all events to the FC worker for handling.
    this.fc_worker.process_event(entry, state)
    return None

# ...existing code...
