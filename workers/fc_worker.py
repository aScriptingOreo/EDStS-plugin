from datetime import datetime
from queue import Queue
from threading import Thread
import logging
from typing import Dict, Any, Set
import requests
from config import config, appname

logger = logging.getLogger(f'{appname}.EDStS.fc_worker')

# Fleet Carrier related events we care about
FC_EVENTS = {
    # Core FC events
    'CarrierJump',
    'CarrierBuy', 
    'CarrierStats',
    'CarrierDockingPermission',
    'CarrierCrewServices',
    'CarrierFinance',
    'CarrierTradeOrder',
    'CarrierDepositFuel',
    
    # Ship interaction with FCs
    'Docked',          # When docked at a FC
    'Undocked',        # When leaving a FC
    'MarketBuy',       # Buying from FC market
    'MarketSell',      # Selling to FC market
    'StoredShips',     # Ship transfer to/from FC
    'ShipyardBuy',     # Buying ships from FC
    'ModuleBuy',       # Buying modules from FC
    'ModuleSell',      # Selling modules to FC
}

class FCWorker:
    def __init__(self, api_base: str, journal_endpoint: str):
        self.api_base = api_base
        self.journal_endpoint = journal_endpoint
        self.queue: Queue = Queue()
        self.worker_thread: Thread | None = None
        self.shutting_down = False
        
        # Track FC info
        self.current_carrier_id: str | None = None
        self.last_event_times: Dict[str, datetime] = {}
        
    def start(self):
        """Start the worker thread"""
        self.worker_thread = Thread(target=self._worker_loop, name='EDStS-FC-Worker')
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
    def stop(self):
        """Stop the worker thread"""
        self.shutting_down = True
        if self.queue:
            self.queue.put(None)  # Signal worker to stop
        if self.worker_thread:
            self.worker_thread.join(timeout=2)

    # Modified: filter FC events using FC_EVENTS
    def should_handle_event(self, entry: Dict[str, Any]) -> bool:
        event = entry.get("event")
        return event in FC_EVENTS

    # Modified: always queue the event regardless of content
    def process_event(self, entry: Dict[str, Any], state: Dict[str, Any]):
        if self.should_handle_event(entry):
            self.queue.put((entry, state))
        else:
            # Optionally log ignored events
            pass

    def _worker_loop(self):
        """Main worker loop"""
        while not self.shutting_down:
            try:
                item = self.queue.get()
                if item is None:  # Shutdown signal
                    break
                    
                entry, state = item
                self._handle_event(entry, state)
                
            except Exception as e:
                logger.error(f"Error in FC worker: {str(e)}")
                
    def _handle_event(self, entry: Dict[str, Any], state: Dict[str, Any]):
        """Handle a specific journal event"""
        try:
            api_key = config.get_str("edsts_api_key")
            if not api_key:
                return
                
            # Add additional state data to enrich the event
            if state.get('ShipID'):
                entry['_shipId'] = state['ShipID']
            if state.get('SystemAddress'):
                entry['_systemAddress'] = state['SystemAddress']
                
            # Submit to API using the common journal endpoint
            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "x-permissions": "EDStS"  # New header for permissions
            }
            
            response = requests.post(
                self.journal_endpoint,
                headers=headers,
                json=entry,  # Send single event as is
                timeout=10
            )
            
            if response.status_code == 401:
                logger.error("Invalid API key for event submission")
            elif response.status_code != 200:
                logger.error(f"Failed to submit event: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error handling event: {str(e)}")
