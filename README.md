# JAM - Cross-Chain Event Listener & Relayer Simulation

This repository contains a Python-based simulation of a critical component in a cross-chain bridge: the event listener and transaction relayer. The script is designed to monitor events on a source blockchain, and in response, trigger corresponding actions on a destination blockchain. This project serves as an architectural blueprint for building robust, modular, and resilient off-chain infrastructure for decentralized applications.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (e.g., Ethereum) to another (e.g., Polygon). A common mechanism for this is "lock-and-mint":

1.  **Lock**: A user sends tokens to a smart contract on the source chain, which locks them.
2.  **Event Emission**: The source chain contract emits an event (e.g., `TokensLocked`) containing details of the transaction (user, amount, etc.).
3.  **Listen & Verify**: Off-chain services, often called "relayers" or "validators," listen for this event. They wait for a certain number of block confirmations to ensure the transaction is final and not part of a blockchain reorganization (re-org).
4.  **Relay & Mint**: After verification, the relayer constructs and signs a transaction on the destination chain. This transaction calls a function (e.g., `mint`) on the destination contract to create an equivalent amount of wrapped tokens for the user.

This script simulates steps 3 and 4. It continuously polls a source chain for `TokensLocked` events and simulates the process of constructing, signing, and submitting a `mint` transaction to a destination chain.

## Code Architecture

The script is designed with a clear separation of concerns, using distinct classes for different responsibilities. This makes the system easier to understand, maintain, and extend.

-   **`ConfigManager`**: Handles loading all necessary configurations (RPC URLs, private keys, contract addresses) from a `.env` file. It centralizes configuration and validates that all required parameters are present at startup.

-   **`BlockchainConnector`**: An abstraction layer for connecting to a blockchain via `web3.py`. It manages the Web3 provider instance and checks connection status, handling details like injecting middleware for Proof-of-Authority (PoA) chains.

-   **`ContractEventListener`**: The core listening component. It's responsible for:
    -   Creating an event filter on a specific contract.
    -   Periodically polling for new event logs.
    -   Managing state (i.e., the last block it has processed) to prevent duplicate event handling.
    -   Implementing a basic re-org detection mechanism to enhance robustness.
    -   Invoking a callback function for each valid event it finds.

-   **`CrossChainTransactionSigner`**: Simulates the relayer's action on the destination chain. It:
    -   Receives event data from the listener.
    -   Constructs a new transaction (e.g., a `mint` call) based on the event data.
    -   Signs the transaction using a securely-loaded private key.
    -   Simulates sending the transaction by POSTing it to a mock API endpoint, mimicking interaction with a relayer service or public mempool.

-   **`BridgeOrchestrator`**: The main class that ties everything together. It:
    -   Initializes all other components.
    -   Injects dependencies (e.g., passes the `TransactionSigner`'s `mint` method as a callback to the `EventListener`).
    -   Contains the main application loop that drives the polling process.

This architecture promotes modularity. For example, to support a new blockchain, you would only need to update the configuration. To handle a different event, you could instantiate another `ContractEventListener` without changing the existing logic.

## How it Works

1.  **Initialization**: The script starts by running `if __name__ == "__main__":`.
2.  **Configuration**: `ConfigManager` loads all required parameters from the `.env` file.
3.  **Connection**: The `BridgeOrchestrator` creates two `BlockchainConnector` instances: one for the source chain and one for the destination chain.
4.  **Component Setup**: The orchestrator initializes the `CrossChainTransactionSigner` (for the destination chain) and the `ContractEventListener` (for the source chain).
5.  **Callback Injection**: The key connection is made here: the `simulate_mint_tokens` method from the signer instance is passed as the `on_event_callback` to the event listener.
6.  **Polling Loop**: The orchestrator starts its `run()` method, which enters an infinite loop.
7.  **Event Scanning**: Inside the loop, `event_listener.poll_for_events()` is called. It fetches the latest block number and scans the range of blocks from its last processed block up to `latest_block - REORG_CONFIRMATION_BLOCKS`.
8.  **Event Handling**: If any `TokensLocked` events are found, the listener iterates through them and calls the injected callback (`simulate_mint_tokens`) for each one, passing the event data.
9.  **Transaction Relaying**: The `simulate_mint_tokens` method receives the event, builds a `mint` transaction for the destination chain, signs it with the relayer's private key, and POSTs the signed raw transaction to a mock API endpoint.
10. **Wait**: After a polling cycle, the script sleeps for `POLLING_INTERVAL_SECONDS` before starting over from step 7.

## Usage Example

Follow these steps to run the simulation.

### 1. Prerequisites

-   Python 3.8+
-   Access to RPC URLs for two EVM-compatible blockchains (e.g., from Infura, Alchemy, or a local node). You can use testnets like Ethereum Sepolia and Polygon Mumbai.
-   An account with a private key on the destination chain, funded with a small amount of gas tokens.

### 2. Installation

Clone the repository and install the required dependencies:

```bash
git clone https://github.com/your-username/jam.git
cd jam
pip install -r requirements.txt
```

### 3. Configuration

Create a `.env` file in the root of the project directory and populate it with your specific details. **Do not commit this file to version control.**

**`.env` file example:**

```env
# --- Source Chain (e.g., Ethereum Sepolia) ---
SOURCE_CHAIN_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"
SOURCE_BRIDGE_CONTRACT_ADDRESS="0x..."

# --- Destination Chain (e.g., Polygon Mumbai) ---
DEST_CHAIN_RPC_URL="https://polygon-mumbai.infura.io/v3/YOUR_INFURA_PROJECT_ID"
DEST_BRIDGE_CONTRACT_ADDRESS="0x..."

# --- Relayer Configuration ---
# The private key of the account that will sign and send transactions on the destination chain.
# IMPORTANT: Use a key from a temporary/burner wallet for testing. DO NOT use a key with real funds.
RELAYER_PRIVATE_KEY="0x..."

# --- Application Settings ---
# Time in seconds between polling for new events.
POLLING_INTERVAL_SECONDS=15
# Number of blocks to wait for confirmation to avoid re-orgs.
REORG_CONFIRMATION_BLOCKS=5
```

### 4. Running the Script

Execute the main script from your terminal:

```bash
python script.py
```

The script will start, connect to both chains, and begin polling for events. You will see log messages in your console indicating its status, any new events it finds, and the simulated transaction relaying process.

To stop the script, press `Ctrl+C`.
