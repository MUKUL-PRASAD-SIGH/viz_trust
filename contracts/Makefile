# Loads .env if present, so deploy targets pick up RPC URL and keys.
-include .env
export

.PHONY: build test deploy-local deploy-sepolia clean fmt

build:
	forge build

test:
	forge test -vv

clean:
	forge clean

fmt:
	forge fmt

# Deploys to a running `anvil` and writes ../deployments/local.json. Uses Anvil's default
# accounts; no .env needed. Re-run after every anvil restart.
deploy-local:
	python script/deploy_local.py

# Requires .env with BASE_SEPOLIA_RPC_URL and PRIVATE_KEY. Copy .env.example to .env and
# fill it in. Never commit .env. Writes ../deployments/base-sepolia.json. No verification.
deploy-sepolia:
	python script/deploy_sepolia.py
