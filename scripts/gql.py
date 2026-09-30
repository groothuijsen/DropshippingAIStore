#!/usr/bin/env python3
"""CLI tool for running GraphQL queries against the dev store.

Usage:
    python scripts/gql.py shop_info
    python scripts/gql.py product_get '{"id": "gid://shopify/Product/123"}'
"""

import argparse
import json
import sys

from apps.core.shopify_client import ShopifyGraphQLClient, load_query


def main():
    parser = argparse.ArgumentParser(description="Run Shopify GraphQL queries")
    parser.add_argument("query", help="Name of the .graphql file (without extension)")
    parser.add_argument("variables", nargs="?", default="{}", help="JSON variables")
    parser.add_argument("--shop", default="localhost:3000", help="Shop domain")
    parser.add_argument("--token", default="shpat_test", help="Access token")
    parser.add_argument("--version", default="2026-07", help="API version")
    args = parser.parse_args()

    query = load_query(args.query)
    variables = json.loads(args.variables)

    client = ShopifyGraphQLClient(args.shop, args.token, args.version)
    try:
        result = client.execute(query, variables)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
