# Mosaiq scripts

## scripts/gql.py
Run GraphQL operations against the dev store and save fixtures.
Usage: `uv run python scripts/gql.py --shop <store>.myshopify.com --file apps/core/graphql/<name>.graphql --vars vars.json --save tests/fixtures/shopify/<name>.json`

## scripts/seed_dev.py
Put demo products into the dev store.

## scripts/eval_ai.py
Run the evalset (30 products) and produce a report.
