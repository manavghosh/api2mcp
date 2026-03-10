"""Unit tests for custom exceptions (TASK-001)."""

from api2mcp.core.exceptions import (
    API2MCPError,
    CircularRefError,
    ParseError,
    ParseException,
    RefResolutionError,
    ValidationException,
)


class TestParseError:
    def test_basic_message(self) -> None:
        err = ParseError("Something went wrong")
        assert str(err) == "[ERROR] Something went wrong"

    def test_with_line_number(self) -> None:
        err = ParseError("Bad syntax", line=42)
        assert "line 42" in str(err)

    def test_with_line_and_column(self) -> None:
        err = ParseError("Bad syntax", line=10, column=5)
        assert "line 10, col 5" in str(err)

    def test_with_path(self) -> None:
        err = ParseError("Missing field", path="info.title")
        assert "at info.title" in str(err)

    def test_warning_severity(self) -> None:
        err = ParseError("Deprecated usage", severity="warning")
        assert "[WARNING]" in str(err)

    def test_full_context(self) -> None:
        err = ParseError("Bad value", line=3, column=10, path="paths./users.get")
        result = str(err)
        assert "at paths./users.get" in result
        assert "line 3, col 10" in result


class TestParseException:
    def test_basic(self) -> None:
        exc = ParseException("Parse failed")
        assert str(exc) == "Parse failed"
        assert exc.errors == []

    def test_with_errors(self) -> None:
        errors = [
            ParseError("Error 1", line=1),
            ParseError("Error 2", line=5),
        ]
        exc = ParseException("Parse failed", errors=errors)
        result = str(exc)
        assert "Parse failed" in result
        assert "Error 1" in result
        assert "Error 2" in result
        assert len(exc.errors) == 2

    def test_is_api2mcp_error(self) -> None:
        exc = ParseException("fail")
        assert isinstance(exc, API2MCPError)


class TestValidationException:
    def test_basic(self) -> None:
        exc = ValidationException("Validation failed")
        assert "Validation failed" in str(exc)

    def test_with_errors(self) -> None:
        exc = ValidationException(
            "Invalid",
            errors=[ParseError("Missing title", path="info")],
        )
        assert len(exc.errors) == 1
        assert "Missing title" in str(exc)


class TestRefResolutionError:
    def test_basic(self) -> None:
        exc = RefResolutionError("#/components/schemas/Foo")
        assert "#/components/schemas/Foo" in str(exc)
        assert exc.ref == "#/components/schemas/Foo"

    def test_custom_message(self) -> None:
        exc = RefResolutionError("#/bad/ref", "File not found")
        assert "File not found" in str(exc)


class TestCircularRefError:
    def test_cycle_chain(self) -> None:
        chain = ["#/A", "#/B", "#/C", "#/A"]
        exc = CircularRefError(chain)
        result = str(exc)
        assert "Circular" in result
        assert "#/A -> #/B -> #/C -> #/A" in result
        assert exc.ref_chain == chain

    def test_is_ref_error(self) -> None:
        exc = CircularRefError(["#/A", "#/A"])
        assert isinstance(exc, RefResolutionError)
        assert isinstance(exc, API2MCPError)


class TestExceptionCodes:
    def test_exception_codes(self) -> None:
        from api2mcp.core.exceptions import (
            GeneratorException,
            RuntimeException,
        )

        assert ParseException("x").code == "PARSE_ERROR"
        assert ValidationException("x").code == "VALIDATION_ERROR"
        assert GeneratorException("x").code == "GENERATOR_ERROR"
        assert RuntimeException("x").code == "RUNTIME_ERROR"
        assert CircularRefError(["a", "b"]).code == "CIRCULAR_REF_ERROR"

    def test_base_code(self) -> None:
        assert API2MCPError("x").code == "API2MCP_ERROR"

    def test_ref_resolution_code(self) -> None:
        assert RefResolutionError("#/foo").code == "REF_RESOLUTION_ERROR"
