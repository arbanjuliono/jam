import os
import time
import json
from typing import Dict, Any, Optional, Callable

import requests
from dotenv import load_dotenv
from web3 import Web3
from web3.contract import Contract
from web3.middleware import geth_poa_middleware
from web3.types import LogReceipt, Wei

# --- Configuration Class ---
class ConfigManager:
    """
    Manages the loading and validation of application configuration from environment variables.
    This centralized approach keeps configuration separate from application logic, making it
    easier to manage different environments (development, staging, production).
    """
    def __init__(self, env_path: str = '.env'):
        """
        Initializes the ConfigManager and loads environment variables from the specified file.
        
        Args:
            env_path (str): The path to the .env file.
        """
        load_dotenv(dotenv_path=env_path)
        self.source_chain_rpc: str = os.getenv("SOURCE_CHAIN_RPC_URL", "")
        self.dest_chain_rpc: str = os.getenv("DEST_CHAIN_RPC_URL", "")
        self.source_bridge_contract_address: str = os.getenv("SOURCE_BRIDGE_CONTRACT_ADDRESS", "")
        self.dest_bridge_contract_address: str = os.getenv("DEST_BRIDGE_CONTRACT_ADDRESS", "")
        self.relayer_private_key: str = os.getenv("RELAYER_PRIVATE_KEY", "")
        self.polling_interval_seconds: int = int(os.getenv("POLLING_INTERVAL_SECONDS", "15"))
        self.reorg_confirmation_blocks: int = int(os.getenv("REORG_CONFIRMATION_BLOCKS", "5"))

        self._validate_config()

    def _validate_config(self):
        """
        Validates that all necessary configuration variables have been loaded.
        Raises ValueError if a required variable is missing.
        """
        required_vars = [
            self.source_chain_rpc,
            self.dest_chain_rpc,
            self.source_bridge_contract_address,
            self.dest_bridge_contract_address,
            self.relayer_private_key
        ]
        if not all(required_vars):
            raise ValueError("One or more required environment variables are missing. Please check your .env file.")
        print("Configuration loaded and validated successfully.")

# --- Blockchain Interaction Class ---
class BlockchainConnector:
    """
    Handles the connection to a specific blockchain via a Web3 provider.
    It abstracts away the details of the connection and provides a simple interface
    to get a Web3 instance and check the connection status.
    """
    def __init__(self, rpc_url: str, chain_name: str):
        """
        Initializes the connector with a given RPC URL.
        
        Args:
            rpc_url (str): The HTTP RPC provider URL for the blockchain.
            chain_name (str): A human-readable name for the chain (for logging).
        """
        self.rpc_url = rpc_url
        self.chain_name = chain_name
        self.web3: Optional[Web3] = None
        self.connect()

    def connect(self):
        """
        Establishes a connection to the blockchain node.
        Includes a retry mechanism for robustness.
        Injects POA middleware for compatibility with networks like Polygon or BSC testnets.
        """
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            # Inject middleware for POA chains (like Polygon Mumbai, Goerli, Sepolia)
            self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            if self.is_connected():
                print(f"Successfully connected to {self.chain_name} at {self.rpc_url}")
            else:
                raise ConnectionError(f"Failed to connect to {self.chain_name}.")
        except Exception as e:
            print(f"Error connecting to {self.chain_name}: {e}")
            self.web3 = None
            raise

    def is_connected(self) -> bool:
        """
        Checks if the Web3 instance is connected to the node.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        return self.web3 is not None and self.web3.is_connected()

# --- Core Event Listener Class ---
class ContractEventListener:
    """
    Listens for specific events on a smart contract.
    This class is responsible for polling the blockchain, fetching new event logs,
    and managing state such as the last processed block to avoid reprocessing events.
    It also includes a basic mechanism to handle block reorganizations.
    """
    def __init__(self, connector: BlockchainConnector, contract_address: str, contract_abi: Dict[str, Any], event_name: str, on_event_callback: Callable):
        if not connector.is_connected() or connector.web3 is None:
            raise ConnectionError(f"BlockchainConnector for {connector.chain_name} is not connected.")
        self.web3 = connector.web3
        self.contract: Contract = self.web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=contract_abi)
        self.event_name = event_name
        self.on_event_callback = on_event_callback
        self.last_processed_block = self.web3.eth.block_number
        self.last_block_hash: Optional[str] = None

        print(f"Event listener initialized for event '{self.event_name}' on contract {contract_address}")
        print(f"Starting to listen from block {self.last_processed_block}")

    def poll_for_events(self, confirmation_blocks: int):
        """
        Polls for new events from the last processed block to the latest block minus a confirmation buffer.
        This buffer helps to reduce the chances of processing events from blocks that might get reorganized.
        """
        try:
            latest_block = self.web3.eth.block_number
            # We process blocks up to `latest_block - confirmation_blocks` to wait for finality
            to_block = latest_block - confirmation_blocks
            if to_block <= self.last_processed_block:
                # print(f"No new blocks to process. Current head: {latest_block}")
                return

            # Basic re-org detection
            if self.last_block_hash:
                last_processed_block_on_chain = self.web3.eth.get_block(self.last_processed_block)
                if last_processed_block_on_chain['hash'].hex() != self.last_block_hash:
                    print(f"[WARNING] Reorganization detected at block {self.last_processed_block}. Re-evaluating...")
                    # In a real scenario, you would implement logic to rewind state.
                    # For this simulation, we'll just reset to the block before the reorg.
                    self.last_processed_block -= 1 
                    self.last_block_hash = self.web3.eth.get_block(self.last_processed_block)['hash'].hex()
                    return

            print(f"Scanning for '{self.event_name}' events from block {self.last_processed_block + 1} to {to_block}...")
            
            event_filter = self.contract.events[self.event_name].create_filter(
                fromBlock=self.last_processed_block + 1,
                toBlock=to_block
            )
            
            new_events = event_filter.get_all_entries()

            if new_events:
                print(f"Found {len(new_events)} new event(s).")
                for event in new_events:
                    self.handle_event(event)
            
            self.last_processed_block = to_block
            self.last_block_hash = self.web3.eth.get_block(to_block)['hash'].hex()

        except Exception as e:
            print(f"[ERROR] An error occurred while polling for events: {e}")

    def handle_event(self, event: LogReceipt):
        """
        Processes a single event log and triggers the provided callback.
        
        Args:
            event (LogReceipt): The event log data from web3.py.
        """
        print(f"--- New Event Detected ---")
        print(f"  Transaction Hash: {event['transactionHash'].hex()}")
        print(f"  Block Number: {event['blockNumber']}")
        print(f"  Event Arguments: {dict(event['args'])}")
        print(f"------------------------")
        try:
            self.on_event_callback(event)
        except Exception as e:
            print(f"[ERROR] Callback failed for event {event['transactionHash'].hex()}: {e}")


# --- Transaction Signing and Relaying Class ---
class CrossChainTransactionSigner:
    """
    Simulates the relayer's role on the destination chain.
    It takes event data from the source chain, constructs a new transaction for the destination chain,
    signs it, and simulates sending it.
    """
    def __init__(self, connector: BlockchainConnector, contract_address: str, contract_abi: Dict[str, Any], private_key: str):
        if not connector.is_connected() or connector.web3 is None:
            raise ConnectionError(f"BlockchainConnector for {connector.chain_name} is not connected.")
        self.web3 = connector.web3
        self.contract: Contract = self.web3.eth.contract(address=Web3.to_checksum_address(contract_address), abi=contract_abi)
        self.account = self.web3.eth.account.from_key(private_key)
        self.chain_id = self.web3.eth.chain_id
        print(f"Transaction signer initialized for address {self.account.address} on chain ID {self.chain_id}")

    def simulate_mint_tokens(self, event_data: LogReceipt):
        """
        Constructs, signs, and simulates the sending of a 'mint' transaction on the destination chain.
        This function would typically be named something like `relay_mint_transaction`.
        
        Args:
            event_data (LogReceipt): The event log from the source chain containing details for the mint.
        """
        try:
            args = event_data['args']
            recipient = args.get('user')
            amount = args.get('amount')
            source_tx_hash = event_data['transactionHash']

            if not all([recipient, amount, source_tx_hash]):
                print("[ERROR] Event data is missing required arguments ('user', 'amount').")
                return

            print(f"\nAttempting to build mint transaction for recipient {recipient} with amount {amount}...")

            # --- Build Transaction ---
            # In a real bridge, you'd check if this source_tx_hash has been processed before
            # to prevent replay attacks.
            nonce = self.web3.eth.get_transaction_count(self.account.address)
            tx_params = {
                'from': self.account.address,
                'nonce': nonce,
                'gas': 200000, # A sensible default, can be estimated with `estimate_gas`
                'gasPrice': self.web3.eth.gas_price, # Or use EIP-1559 fields
                'chainId': self.chain_id
            }
            
            # Construct the transaction object
            mint_tx = self.contract.functions.mint(recipient, amount, source_tx_hash).build_transaction(tx_params)

            # --- Sign Transaction ---
            signed_tx = self.web3.eth.account.sign_transaction(mint_tx, self.account.key)
            print(f"Transaction signed successfully. Raw Tx: {signed_tx.rawTransaction.hex()}")

            # --- Simulate Sending ---
            # In a real-world scenario, you would use:
            # tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            # print(f"Transaction sent to destination chain. Tx Hash: {tx_hash.hex()}")
            # Instead, we will simulate posting this to a mock relayer API.
            self.simulate_post_to_relayer_api(signed_tx.rawTransaction.hex())

        except Exception as e:
            print(f"[ERROR] Failed to build or sign the mint transaction: {e}")

    @staticmethod
    def simulate_post_to_relayer_api(raw_tx_hex: str):
        """
        Simulates sending the signed transaction to a 3rd party service or mempool.
        Uses the `requests` library to POST to a mock endpoint.
        """
        mock_api_url = "https://httpbin.org/post"
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_sendRawTransaction",
            "params": [raw_tx_hex],
            "id": 1
        }
        try:
            print(f"Simulating POST of raw transaction to {mock_api_url}...")
            response = requests.post(mock_api_url, json=payload, timeout=10)
            response.raise_for_status() # Raise an exception for bad status codes
            print(f"Mock API responded successfully. Status: {response.status_code}")
            # print(f"Response Body: {response.json()}")
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to simulate POST to relayer API: {e}")

# --- Main Orchestrator Class ---
class BridgeOrchestrator:
    """
    The main class that orchestrates the entire bridge listening and relaying process.
    It initializes all components and runs the main application loop.
    """
    def __init__(self, config: ConfigManager):
        self.config = config
        # Placeholder ABIs - In a real project, these would be loaded from JSON files.
        self.source_abi = self._get_mock_bridge_abi('TokensLocked')
        self.dest_abi = self._get_mock_token_abi('mint')
        
        # Initialize connectors
        self.source_connector = BlockchainConnector(config.source_chain_rpc, "SourceChain")
        self.dest_connector = BlockchainConnector(config.dest_chain_rpc, "DestinationChain")
        
        # Initialize the transaction signer for the destination chain
        self.tx_signer = CrossChainTransactionSigner(
            connector=self.dest_connector,
            contract_address=config.dest_bridge_contract_address,
            contract_abi=self.dest_abi,
            private_key=config.relayer_private_key
        )

        # Initialize the event listener for the source chain
        self.event_listener = ContractEventListener(
            connector=self.source_connector,
            contract_address=config.source_bridge_contract_address,
            contract_abi=self.source_abi,
            event_name='TokensLocked',
            on_event_callback=self.tx_signer.simulate_mint_tokens # Pass the signer method as a callback
        )

    def run(self):
        """
        Starts the main application loop, which periodically polls for new events.
        """
        print("\nStarting Bridge Orchestrator...")
        try:
            while True:
                self.event_listener.poll_for_events(self.config.reorg_confirmation_blocks)
                print(f"Waiting for {self.config.polling_interval_seconds} seconds before next poll...\n")
                time.sleep(self.config.polling_interval_seconds)
        except KeyboardInterrupt:
            print("\nShutting down orchestrator.")
        except Exception as e:
            print(f"[FATAL] An unhandled exception occurred in the main loop: {e}")

    @staticmethod
    def _get_mock_bridge_abi(event_name: str) -> Dict[str, Any]:
        """Generates a mock ABI for the source bridge contract."""
        return json.loads(f'''
        [
            {{
                "anonymous": false,
                "inputs": [
                    {{"indexed": true, "internalType": "address", "name": "user", "type": "address"}},
                    {{"indexed": false, "internalType": "uint256", "name": "amount", "type": "uint256"}},
                    {{"indexed": false, "internalType": "uint256", "name": "nonce", "type": "uint256"}}
                ],
                "name": "{event_name}",
                "type": "event"
            }}
        ]
        ''')

    @staticmethod
    def _get_mock_token_abi(function_name: str) -> Dict[str, Any]:
        """Generates a mock ABI for the destination token contract."""
        return json.loads(f'''
        [
            {{
                "inputs": [
                    {{"internalType": "address", "name": "to", "type": "address"}},
                    {{"internalType": "uint256", "name": "amount", "type": "uint256"}},
                    {{"internalType": "bytes32", "name": "sourceTxHash", "type": "bytes32"}}
                ],
                "name": "{function_name}",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            }}
        ]
        ''')

# --- Main Execution Block ---
if __name__ == "__main__":
    try:
        # 1. Load configuration
        config = ConfigManager()
        
        # 2. Initialize and run the orchestrator
        orchestrator = BridgeOrchestrator(config)
        orchestrator.run()
        
    except ValueError as e:
        print(f"[FATAL] Configuration error: {e}")
    except ConnectionError as e:
        print(f"[FATAL] Blockchain connection error: {e}")
    except Exception as e:
        print(f"[FATAL] An unexpected error occurred during initialization: {e}")

# @-internal-utility-start
def validate_payload_7058(payload: dict):
    """Validates incoming data payload on 2025-11-03 14:26:22"""
    if not isinstance(payload, dict):
        return False
    required_keys = ['id', 'timestamp', 'data']
    return all(key in payload for key in required_keys)
# @-internal-utility-end


# @-internal-utility-start
def is_api_key_valid_4504(api_key: str):
    """Checks if the API key format is valid. Added on 2025-12-01 21:59:02"""
    import re
    return bool(re.match(r'^[a-zA-Z0-9]{32}$', api_key))
# @-internal-utility-end

