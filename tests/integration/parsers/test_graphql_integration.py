"""Integration tests for the GraphQL parser (F3.1).

Tests full schema parsing end-to-end and complex schemas.
Real-API (GitHub/Shopify) tests are optional and skipped when network
is unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api2mcp.core.ir_schema import HttpMethod, ParameterLocation
from api2mcp.parsers.graphql import GraphQLParser

try:
    import graphql  # noqa: F401
    HAS_GRAPHQL_CORE = True
except ImportError:
    HAS_GRAPHQL_CORE = False

pytestmark_gql = pytest.mark.skipif(
    not HAS_GRAPHQL_CORE, reason="graphql-core not installed"
)

# ---------------------------------------------------------------------------
# Complex SDL schema
# ---------------------------------------------------------------------------

ECOMMERCE_SDL = """
\"\"\"Product in an e-commerce catalogue\"\"\"
type Product {
  id: ID!
  name: String!
  description: String
  price: Float!
  inStock: Boolean!
  tags: [String!]!
  variants: [ProductVariant!]!
}

type ProductVariant {
  id: ID!
  sku: String!
  price: Float!
  inventory: Int!
}

type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}

type ProductConnection {
  edges: [ProductEdge!]!
  pageInfo: PageInfo!
  totalCount: Int!
}

type ProductEdge {
  node: Product!
  cursor: String!
}

input ProductFilterInput {
  minPrice: Float
  maxPrice: Float
  inStock: Boolean
  tags: [String!]
}

input CreateProductInput {
  name: String!
  description: String
  price: Float!
  tags: [String!]
}

input UpdateProductInput {
  name: String
  description: String
  price: Float
  inStock: Boolean
}

enum SortOrder {
  ASC
  DESC
}

enum ProductSortField {
  NAME
  PRICE
  CREATED_AT
}

input ProductSortInput {
  field: ProductSortField!
  order: SortOrder!
}

type Query {
  \"\"\"Get a single product\"\"\"
  product(id: ID!): Product

  \"\"\"List products with pagination and filtering\"\"\"
  products(
    first: Int
    after: String
    filter: ProductFilterInput
    sort: ProductSortInput
  ): ProductConnection!
}

type Mutation {
  \"\"\"Create a new product\"\"\"
  createProduct(input: CreateProductInput!): Product!

  \"\"\"Update an existing product\"\"\"
  updateProduct(id: ID!, input: UpdateProductInput!): Product

  \"\"\"Delete a product\"\"\"
  deleteProduct(id: ID!): Boolean!
}

type Subscription {
  \"\"\"Watch for product inventory changes\"\"\"
  inventoryChanged(productId: ID!): Product
  \"\"\"Watch for new products matching a filter\"\"\"
  newProducts(filter: ProductFilterInput): Product
}
"""


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytestmark_gql
class TestGraphQLParserEndToEnd:
    @pytest.mark.asyncio
    async def test_full_ecommerce_schema(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL, title="E-commerce API")

        assert spec.title == "E-commerce API"
        assert spec.source_format == "graphql"

        op_ids = {e.operation_id for e in spec.endpoints}
        assert {"product", "products", "createProduct", "updateProduct", "deleteProduct",
                "inventoryChanged", "newProducts"} == op_ids

    @pytest.mark.asyncio
    async def test_query_count(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        queries = [e for e in spec.endpoints if e.method == HttpMethod.QUERY]
        assert len(queries) == 2

    @pytest.mark.asyncio
    async def test_mutation_count(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        mutations = [e for e in spec.endpoints if e.method == HttpMethod.MUTATION]
        assert len(mutations) == 3

    @pytest.mark.asyncio
    async def test_subscription_count(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        subs = [e for e in spec.endpoints if e.method == HttpMethod.SUBSCRIPTION]
        assert len(subs) == 2

    @pytest.mark.asyncio
    async def test_products_pagination_params(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        products_ep = next(e for e in spec.endpoints if e.operation_id == "products")
        param_names = {p.name for p in products_ep.parameters}
        assert {"first", "after", "filter", "sort"} == param_names

    @pytest.mark.asyncio
    async def test_nested_input_object_filter(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        products_ep = next(e for e in spec.endpoints if e.operation_id == "products")
        filter_param = next(p for p in products_ep.parameters if p.name == "filter")
        assert filter_param.schema.type == "object"
        assert "minPrice" in filter_param.schema.properties
        assert "maxPrice" in filter_param.schema.properties

    @pytest.mark.asyncio
    async def test_enum_sort_param(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        # sort arg is ProductSortInput which contains enums
        products_ep = next(e for e in spec.endpoints if e.operation_id == "products")
        sort_param = next(p for p in products_ep.parameters if p.name == "sort")
        assert sort_param.schema.type == "object"
        assert "field" in sort_param.schema.properties
        assert sort_param.schema.properties["field"].type == "string"
        assert set(sort_param.schema.properties["field"].enum) == {
            "NAME", "PRICE", "CREATED_AT"
        }

    @pytest.mark.asyncio
    async def test_list_field_in_response(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        products_ep = next(e for e in spec.endpoints if e.operation_id == "products")
        # Returns ProductConnection which has edges: [ProductEdge!]!
        resp_schema = products_ep.responses[0].schema
        assert resp_schema is not None
        assert resp_schema.type == "object"

    @pytest.mark.asyncio
    async def test_models_include_object_types(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        assert "Product" in spec.models
        assert "ProductVariant" in spec.models
        assert "PageInfo" in spec.models

    @pytest.mark.asyncio
    async def test_create_product_required_params(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        create_ep = next(e for e in spec.endpoints if e.operation_id == "createProduct")
        input_param = next(p for p in create_ep.parameters if p.name == "input")
        # name and price are required in CreateProductInput
        assert "name" in input_param.schema.required
        assert "price" in input_param.schema.required
        # description is optional
        assert "description" not in input_param.schema.required

    @pytest.mark.asyncio
    async def test_all_params_have_body_location(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        for ep in spec.endpoints:
            for param in ep.parameters:
                assert param.location == ParameterLocation.BODY

    @pytest.mark.asyncio
    async def test_subscription_metadata_flag(self) -> None:
        parser = GraphQLParser()
        spec = await parser.parse(ECOMMERCE_SDL)
        subs = [e for e in spec.endpoints if e.method == HttpMethod.SUBSCRIPTION]
        for sub in subs:
            assert sub.metadata.get("subscription") is True


@pytestmark_gql
class TestGraphQLParserFromFile:
    @pytest.mark.asyncio
    async def test_parse_sdl_file(self, tmp_path: Path) -> None:
        schema_file = tmp_path / "ecommerce.graphql"
        schema_file.write_text(ECOMMERCE_SDL, encoding="utf-8")
        parser = GraphQLParser()
        spec = await parser.parse(schema_file)
        assert spec.title == "Ecommerce"  # derived from filename

    @pytest.mark.asyncio
    async def test_parse_introspection_json_file(self, tmp_path: Path) -> None:
        # Build minimal introspection JSON
        data = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": None,
                "subscriptionType": None,
                "types": [
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "description": None,
                        "fields": [
                            {
                                "name": "ping",
                                "description": "Health check",
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            }
                        ],
                        "inputFields": None,
                        "enumValues": None,
                        "possibleTypes": None,
                    }
                ],
            }
        }
        json_file = tmp_path / "introspection.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        parser = GraphQLParser()
        spec = await parser.parse(json_file)
        assert any(e.operation_id == "ping" for e in spec.endpoints)

    @pytest.mark.asyncio
    async def test_parse_missing_file_raises(self) -> None:
        from api2mcp.core.exceptions import ParseException
        parser = GraphQLParser()
        with pytest.raises(ParseException, match="not found"):
            await parser.parse(Path("/nonexistent/path/schema.graphql"))


@pytestmark_gql
class TestGraphQLParserIntrospectionEndToEnd:
    """Test complete introspection JSON parsing round-trip."""

    @pytest.mark.asyncio
    async def test_introspection_with_input_object(self) -> None:
        data = {
            "__schema": {
                "queryType": {"name": "Query"},
                "mutationType": {"name": "Mutation"},
                "subscriptionType": None,
                "types": [
                    {
                        "kind": "SCALAR", "name": "String", "description": None,
                        "fields": None, "inputFields": None,
                        "enumValues": None, "possibleTypes": None,
                    },
                    {
                        "kind": "SCALAR", "name": "ID", "description": None,
                        "fields": None, "inputFields": None,
                        "enumValues": None, "possibleTypes": None,
                    },
                    {
                        "kind": "INPUT_OBJECT",
                        "name": "UserInput",
                        "description": "Input for creating a user",
                        "fields": None,
                        "inputFields": [
                            {
                                "name": "name",
                                "description": "Full name",
                                "type": {
                                    "kind": "NON_NULL",
                                    "name": None,
                                    "ofType": {"kind": "SCALAR", "name": "String", "ofType": None},
                                },
                                "defaultValue": None,
                            },
                            {
                                "name": "email",
                                "description": "Email address",
                                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                                "defaultValue": None,
                            },
                        ],
                        "enumValues": None,
                        "possibleTypes": None,
                    },
                    {
                        "kind": "OBJECT",
                        "name": "User",
                        "description": "A user",
                        "fields": [
                            {
                                "name": "id",
                                "description": None,
                                "args": [],
                                "type": {"kind": "NON_NULL", "name": None,
                                         "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None}},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            },
                            {
                                "name": "name",
                                "description": None,
                                "args": [],
                                "type": {"kind": "SCALAR", "name": "String", "ofType": None},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            },
                        ],
                        "inputFields": None,
                        "enumValues": None,
                        "possibleTypes": None,
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Query",
                        "description": None,
                        "fields": [
                            {
                                "name": "getUser",
                                "description": "Get user by ID",
                                "args": [
                                    {
                                        "name": "id",
                                        "description": "User ID",
                                        "type": {
                                            "kind": "NON_NULL", "name": None,
                                            "ofType": {"kind": "SCALAR", "name": "ID", "ofType": None},
                                        },
                                        "defaultValue": None,
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "User", "ofType": None},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            }
                        ],
                        "inputFields": None,
                        "enumValues": None,
                        "possibleTypes": None,
                    },
                    {
                        "kind": "OBJECT",
                        "name": "Mutation",
                        "description": None,
                        "fields": [
                            {
                                "name": "createUser",
                                "description": "Create a user",
                                "args": [
                                    {
                                        "name": "input",
                                        "description": "User input",
                                        "type": {
                                            "kind": "NON_NULL", "name": None,
                                            "ofType": {"kind": "INPUT_OBJECT", "name": "UserInput", "ofType": None},
                                        },
                                        "defaultValue": None,
                                    }
                                ],
                                "type": {"kind": "OBJECT", "name": "User", "ofType": None},
                                "isDeprecated": False,
                                "deprecationReason": None,
                            }
                        ],
                        "inputFields": None,
                        "enumValues": None,
                        "possibleTypes": None,
                    },
                ],
            }
        }
        parser = GraphQLParser()
        spec = await parser.parse(json.dumps(data), title="User API")

        assert spec.title == "User API"
        assert len(spec.endpoints) == 2

        get_user = next(e for e in spec.endpoints if e.operation_id == "getUser")
        assert get_user.method == HttpMethod.QUERY
        id_param = next(p for p in get_user.parameters if p.name == "id")
        assert id_param.required is True
        assert id_param.schema.type == "string"

        create_user = next(e for e in spec.endpoints if e.operation_id == "createUser")
        assert create_user.method == HttpMethod.MUTATION
        input_param = next(p for p in create_user.parameters if p.name == "input")
        assert input_param.required is True
        assert input_param.schema.type == "object"
        assert "name" in input_param.schema.required
        assert "email" not in input_param.schema.required
