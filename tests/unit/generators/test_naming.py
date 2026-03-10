"""Unit tests for tool naming convention (TASK-012, TASK-018)."""

import pytest

from api2mcp.core.ir_schema import Endpoint, HttpMethod
from api2mcp.generators.naming import (
    derive_tool_name,
    resolve_collisions,
    sanitize_name,
)


class TestSanitizeName:
    """Tests for sanitize_name()."""

    def test_simple_lowercase(self) -> None:
        assert sanitize_name("listPets") == "listpets"

    def test_camel_case(self) -> None:
        assert sanitize_name("getUserById") == "getuserbyid"

    def test_special_characters_replaced(self) -> None:
        assert sanitize_name("list-pets!v2") == "list_pets_v2"

    def test_multiple_underscores_collapsed(self) -> None:
        assert sanitize_name("list___pets") == "list_pets"

    def test_leading_trailing_stripped(self) -> None:
        assert sanitize_name("__list_pets__") == "list_pets"

    def test_empty_string(self) -> None:
        assert sanitize_name("") == ""

    def test_all_special_chars(self) -> None:
        assert sanitize_name("---") == ""

    def test_numbers_preserved(self) -> None:
        assert sanitize_name("v2_list_pets") == "v2_list_pets"


class TestDeriveToolName:
    """Tests for derive_tool_name()."""

    def _make_endpoint(
        self,
        path: str = "/pets",
        method: HttpMethod = HttpMethod.GET,
        operation_id: str = "",
    ) -> Endpoint:
        return Endpoint(path=path, method=method, operation_id=operation_id)

    def test_uses_operation_id_when_present(self) -> None:
        ep = self._make_endpoint(operation_id="listPets")
        assert derive_tool_name(ep) == "listpets"

    def test_fallback_to_method_path(self) -> None:
        ep = self._make_endpoint(path="/pets", method=HttpMethod.GET, operation_id="")
        assert derive_tool_name(ep) == "get_pets"

    def test_path_with_parameter(self) -> None:
        ep = self._make_endpoint(
            path="/pets/{petId}", method=HttpMethod.GET, operation_id=""
        )
        assert derive_tool_name(ep) == "get_pets_petid"

    def test_nested_path(self) -> None:
        ep = self._make_endpoint(
            path="/users/{userId}/posts/{postId}",
            method=HttpMethod.DELETE,
            operation_id="",
        )
        assert derive_tool_name(ep) == "delete_users_userid_posts_postid"

    def test_post_method(self) -> None:
        ep = self._make_endpoint(path="/pets", method=HttpMethod.POST, operation_id="")
        assert derive_tool_name(ep) == "post_pets"

    def test_graphql_query(self) -> None:
        ep = self._make_endpoint(
            path="/graphql", method=HttpMethod.QUERY, operation_id="getUser"
        )
        assert derive_tool_name(ep) == "getuser"


class TestResolveCollisions:
    """Tests for resolve_collisions()."""

    def _make_endpoint(
        self,
        path: str,
        method: HttpMethod = HttpMethod.GET,
        operation_id: str = "",
    ) -> Endpoint:
        return Endpoint(path=path, method=method, operation_id=operation_id)

    def test_no_collisions(self) -> None:
        endpoints = [
            self._make_endpoint("/pets", HttpMethod.GET, "listPets"),
            self._make_endpoint("/pets", HttpMethod.POST, "createPet"),
            self._make_endpoint("/pets/{petId}", HttpMethod.GET, "showPetById"),
        ]
        result = resolve_collisions(endpoints)
        assert result["listPets"] == "listpets"
        assert result["createPet"] == "createpet"
        assert result["showPetById"] == "showpetbyid"

    def test_collision_resolved_with_suffix(self) -> None:
        # Two endpoints that would produce the same name
        endpoints = [
            self._make_endpoint("/pets", HttpMethod.GET, "list_items"),
            self._make_endpoint("/items", HttpMethod.GET, "list_items_copy"),
            # These two intentionally collide when sanitized if they have same operation_id base
        ]
        result = resolve_collisions(endpoints)
        names = list(result.values())
        assert len(names) == len(set(names)), f"Names are not unique: {names}"

    def test_collision_from_fallback_names(self) -> None:
        # Two endpoints without operation_id but same method, different paths
        # that produce the same sanitized name
        ep1 = self._make_endpoint("/pet-items", HttpMethod.GET, "")
        ep2 = self._make_endpoint("/pet_items", HttpMethod.GET, "")
        endpoints = [ep1, ep2]
        result = resolve_collisions(endpoints)
        names = list(result.values())
        assert len(set(names)) == 2, f"Names not unique: {names}"

    def test_empty_list(self) -> None:
        assert resolve_collisions([]) == {}

    def test_single_endpoint(self) -> None:
        endpoints = [self._make_endpoint("/pets", HttpMethod.GET, "listPets")]
        result = resolve_collisions(endpoints)
        assert result == {"listPets": "listpets"}

    def test_actual_collision_different_operation_ids_same_sanitized(self) -> None:
        # Operation IDs that sanitize to the same name
        endpoints = [
            self._make_endpoint("/a", HttpMethod.GET, "list-pets"),
            self._make_endpoint("/b", HttpMethod.GET, "list_pets"),
        ]
        result = resolve_collisions(endpoints)
        names = list(result.values())
        assert len(set(names)) == len(names), f"Collision not resolved: {names}"
